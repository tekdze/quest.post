#!/usr/bin/env python3
"""Aday haberi Turkce post metnine cevirir. Gemini + uslup filtresi.

GEMINI_API_KEY gerekir (.env dosyasindan veya ortam degiskeninden).

Is bolumu net: LLM SADECE metin yazar. Tasarima, tier'a, gorsel secimine
karisamaz. Cikti dogrudan render.py'in bekledigi semaya oturur.

Tek istisna uzunluk: kac sayfa yazilacagina model karar veriyor, cunku bunu
ancak metni yazan bilir. Ama SINIRLARI kod uyguluyor (check_structure):
1-10 sayfa, ilk sayfa cover, son sayfa outro, en fazla bir rakam sayfasi.

Kullanim:
    py -3.12 src/write.py --list-models          # once bunu calistir
    py -3.12 src/write.py --index 1              # candidates.json'daki 1. aday
    py -3.12 src/write.py --index 1 --tier A --out state/draft.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = ROOT / "state" / "candidates.json"
# Elle calistirma ciktisi. produce.py kendi id'siyle drafts/ altina yaziyor.
DEFAULT_OUT = ROOT / "state" / "drafts" / "_elle.json"

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Surum SABITLENDI (3.7-flash surekli 503 donuyordu, 3.6 stabil). "gemini-flash-latest" gibi takma ad kullanilmiyor:
# model sessizce degisirse uslup da degisir, 300. post 1. postla ayni olmaz.
DEFAULT_MODEL = "gemini-3.6-flash"
# QA ve menu gibi yardimci isler AYRI modelde. Sebep kota: gunluk limit
# model basina ve esit degil - 3.6-flash gunde 20 istek, flash-lite 500
# (AI Studio rate limit panelinden okundu). Kart METNI 3.6'da kaliyor
# (surum sabit karari, uslup), yardimci isler bol havuzda.
HELPER_MODEL = "gemini-3.5-flash-lite"
MAX_ATTEMPTS = 3

# Sayfa sayisi ARTIK SABIT DEGIL. Eskiden istem "3-5 sayfa" diyordu ve tek
# cumlelik bir duyuru da, uc kaynagin ayrinti verdigi bir haber de ayni
# uzunlukta cikiyordu: birinde dolgu, digerinde eksik anlatim.
# Uzunlugu haberin derinligi belirler, SINIRLARI kod uygular - modele
# "ne kadar gerekiyorsa" demek yeterli degil (bkz. tier dersi: serbestlik
# verilirse abartir). Ust sinir Instagram carousel siniri.
MIN_PAGES = 1
MAX_PAGES = 10
PAGE_TYPES = {"cover", "text", "numbers", "outro"}

# Gecici HTTP hatalari icin yeniden deneme (503 = model yogun).
HTTP_RETRIES = 4
# Bu kodlardan biri geldiginde ana modelden yedege dusuluyor. 429 kota,
# 503 yogunluk, 500/502 sunucu tarafi - hepsinde "post uretememektense
# baska modelle uret" karari gecerli.
API_GECICI_HATALAR = ("429", "500", "502", "503")
RETRY_BACKOFF = 5  # saniye, her denemede katlaniyor

# Sabit kategori listesi. LLM buradan secer, serbest yazamaz - kicker metni
# her postta ayni sozluk icinden gelsin diye.
# Hepsi OLAY tipi: kutu haberde NE OLDUGUNU soyler, konunun ne oldugunu
# degil. Eskiden listede "studyo" vardi ve o bir olay degil bir OZNE'ydi;
# olcum (20260831-the-blood-of-dawnwalker): haber uc ayri yayinin INCELEMESI
# idi ama listede "inceleme" yoktu, model mecburen "studyo" secti ve kapak
# kutusu haberi yanlis bildirdi. Kusur modelde degil, sozlukte eksiklikti.
CATEGORIES = [
    "duyuru", "çıkış", "inceleme", "fragman", "güncelleme", "gecikme",
    "sızıntı", "etkinlik", "finansman", "kapanma", "demo", "tartışma",
]

# Son sayfanin soru tipi. Her uretimde rastgele biri secilir.
#
# Neden var: model serbest birakilinca her postta ayni kalibi yaziyordu -
# "... ister miydiniz?", "... dener miydiniz". Bunlar cevabi "evet" olan
# sorular, yani okurun soyleyecek bir seyi olmuyor ve yorum gelmiyor.
# Tip vermek kalibi kiriyor; yasagi style.py uyguluyor.
SORU_TIPLERI = {
    "tercih": "iki seçenek sun, okur birini seçsin "
              "(ornek: \"kotu olmak mi daha eglenceli, sevimli olmak mi\")",
    "karşıt görüş": "olayin tartismali yanini sor, okuru taraf tutmaya cagir "
                    "(ornek: \"bu bir ozellik mi yoksa zaman kaybi mi\")",
    "kişisel deneyim": "okurun kendi hikayesini cagir "
                       "(ornek: \"senin rafinda boyle bir kose olsa ne koyardin\")",
    "sebep": "okura NEDEN diye sor, aciklama istesin "
             "(ornek: \"gezegeni hastalik gibi sarmak neden bu kadar cekici\")",
    "somut ayrıntı": "haberdeki BELIRLI bir detay uzerine sor, genel konu "
                     "uzerine degil",
}

# Her uretimde rastgele biri secilir. Sabit acilis kalibi olusmasini engeller.
WRITING_MODES = {
    "gözlem": "olayın somut bir detayına odaklan, genel yorum yapma",
    "karşılaştırma": "benzer bir örneğe veya rakibe kıyasla anlat",
    "tarihsel not": "olayın geçmişiyle bağlantısını kur",
    "sayısal detay": "kaynaktaki rakamların ne anlama geldiğini aç",
    "karşı görüş": "olaya şüpheyle yaklaş, zayıf tarafını söyle",
}


# ------------------------------------------------------------------ anahtar

def load_env() -> None:
    """.env dosyasini ortam degiskenlerine yukle. Bagimlilik istemez."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api_key() -> str:
    load_env()
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        sys.exit(
            "GEMINI_API_KEY bulunamadi.\n"
            "Proje kokune .env dosyasi ac, icine tek satir yaz:\n"
            "  GEMINI_API_KEY=anahtarin"
        )
    return key


# --------------------------------------------------------------- gemini

def api_call(path: str, payload: dict | None = None) -> dict:
    """Gemini REST cagrisi. SDK kullanilmiyor - tek bagimliliksiz istek yeter.

    503 ve 429 gecici hatalar: model o an yogun veya kota anlik dolmus.
    Bot cron ile calistigi icin bunlara dayanmasi lazim, yoksa tek bir
    yogunluk anı gunun postunu dusurur.
    """
    url = f"{API_BASE}/{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None

    for attempt in range(1, HTTP_RETRIES + 1):
        headers = {"x-goog-api-key": api_key(), "Content-Type": "application/json"}
        request = urllib.request.Request(url, data=data, headers=headers,
                                         method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503) and attempt < HTTP_RETRIES:
                wait = RETRY_BACKOFF * attempt
                print(f"  {exc.code} geldi, {wait} sn sonra tekrar "
                      f"({attempt}/{HTTP_RETRIES - 1})", file=sys.stderr)
                time.sleep(wait)
                continue
            sys.exit(f"Gemini API hatasi {exc.code}:\n{body[:600]}")
        except urllib.error.URLError as exc:
            if attempt < HTTP_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)
                continue
            sys.exit(f"Gemini API'ye ulasilamadi: {exc.reason}")
    sys.exit("Gemini API: tum denemeler tukendi")


def list_models() -> None:
    data = api_call("models")
    rows = []
    for model in data.get("models", []):
        name = model.get("name", "").removeprefix("models/")
        methods = model.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue
        rows.append((name, model.get("inputTokenLimit", 0)))
    print(f"generateContent destekleyen {len(rows)} model:")
    for name, limit in sorted(rows):
        print(f"  {name:44} girdi limiti {limit}")


def generate_gorsel(prompt: str, image_path: Path, model: str,
                    temperature: float = 0.0) -> dict:
    """Metin + GÖRSEL gönder. Kart denetimi (qa.py) bunu kullanıyor.

    Görsel `inline_data` ile gidiyor: tek çağrılık iş için dosya yükleme
    API'sine gerek yok. Uzantıdan MIME türü çıkarılıyor; ızgara JPEG
    basılıyor çünkü PNG hâli 4 MB'a çıkıyor ve base64 ile daha da şişiyor.
    """
    veri = base64.b64encode(image_path.read_bytes()).decode("ascii")
    mime = "image/jpeg" if image_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    payload = {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": mime, "data": veri}},
            {"text": prompt},
        ]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }
    data = api_call(f"models/{model}:generateContent", payload)
    aday = (data.get("candidates") or [{}])[0]
    try:
        text = aday["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        reason = data.get("promptFeedback", {}).get("blockReason",
                                                    aday.get("finishReason", "?"))
        raise GecersizCevap(f"gorsel cagrisi bos dondu (sebep: {reason})")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GecersizCevap(f"gorsel cagrisi gecersiz JSON ({exc.msg})") from exc


class GecersizCevap(Exception):
    """Model cevap verdi ama kullanilabilir JSON degil.

    Cokme sebebi degil, YENIDEN DENEME sebebi: uzun postlarda cikti
    sinirina takilip yarim JSON gelebiliyor (sayfa sayisi 10'a kadar
    cikabildigi icin risk artti). Traceback'le olmek yerine dongu bir
    daha deniyor ve modele "kisalt" diyor.
    """


def liste_al(cevap, anahtar: str) -> list:
    """Cevaptaki listeyi al. Model bazen sarmalayıcıyı atlayıp dizi döndürüyor.

    Ölçüldü (2026-08-31): hedefli onarım turu `{"metinler": [...]}` bekliyordu,
    model doğrudan `[...]` döndürdü ve üretim `AttributeError: 'list' object
    has no attribute 'get'` ile düştü. Şema net yazılsa bile bu olabiliyor,
    o yüzden iki biçim de kabul ediliyor.
    """
    if isinstance(cevap, list):
        return cevap
    if isinstance(cevap, dict):
        deger = cevap.get(anahtar)
        return deger if isinstance(deger, list) else []
    return []


def generate(prompt: str, model: str, temperature: float) -> dict:
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }
    data = api_call(f"models/{model}:generateContent", payload)
    aday = (data.get("candidates") or [{}])[0]
    # Neden bittigi onemli: MAX_TOKENS ise cikti yarim kaldi demektir,
    # SAFETY ise icerik engellenmis. Ikisi ayri sorun, mesajda gorunsun.
    bitis = aday.get("finishReason", "?")
    try:
        text = aday["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        reason = data.get("promptFeedback", {}).get("blockReason", bitis)
        if bitis == "MAX_TOKENS":
            raise GecersizCevap("cikti sinira takildi, hic metin donmedi")
        sys.exit(f"Gemini bos cevap dondu (sebep: {reason})\n{json.dumps(data)[:400]}")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise GecersizCevap(
            f"gecersiz JSON ({exc.msg}), bitis={bitis}, {len(text)} karakter"
        ) from exc


# ---------------------------------------------------------------- istem

SCHEMA = """{
  "cikarim": [
    {"olgu": "kaynaktaki SOMUT bir bilgi, tek cümle Türkçe",
     "alinti": "bu bilginin dayandığı kaynak metinden BIREBIR kopyalanmış İngilizce parça, en az 5 kelime"}
  ],
  "game": "haberin konusu olan oyunun veya şirketin adı",
  "search_name": "haberin ASIL konusu olan oyunun TAM ve INGILIZCE adi, surum numarasi dahil (ornek: The Witcher 3: Wild Hunt). Haber bir oyunu konu almiyorsa null",
  "image_candidates": ["haber metninde adi gecen ve GORSELI bu haberi temsil edebilecek oyunlarin tam Ingilizce adlari, onem sirasiyla, en fazla 3. search_name doluysa onu buraya tekrar yazma. Uygun oyun yoksa bos liste"],
  "series_fallback": ["ayni serinin/evrenin gorsel bakimindan zengin baska oyunlarinin tam Ingilizce adlari, en fazla 2. Sadece konu oyununun gorseli yetmezse kullanilacak. Uygun yoksa bos liste"],
  "representative_games": ["haberde adi GECMESE BILE bu haberi gorsel olarak temsil edebilecek oyunlarin tam Ingilizce adlari, en fazla 3, en uygundan baslayarak. Yalnizca yukaridakilerin hicbiri tutmazsa kullanilir"],
  "category": "listeden biri",
  "studio": "görsel kredisi için stüdyo adı, bilinmiyorsa null",
  "is_leak": true veya false,
  "caption": "Instagram gönderi açıklaması. 2-4 cümle, kartlarda yazanı TEKRARLAMAZ, haberin bağlamını verir. En fazla 2 hashtag, sonda.",
  "pages": [
    (asagidakiler sayfa TIPLERININ bicimi, sabit bir liste degil. kac sayfa
     ve hangi tipte yazacagini SAYFA SAYISI kurali soyluyor. text sayfasi
     birden fazla olabilir, numbers ve outro hic olmayabilir.)
    {"type": "cover", "title": "kapak başlığı, en fazla 8 kelime"},
    {"type": "text", "title": "3-5 kelime", "paragraph": "2-3 cümle",
     "dayanak": 0,
     "bullets": ["madde", "madde"], "bullet_dayanak": [1, 2]},
    {"type": "numbers", "title": "3-5 kelime",
     "metrics": [{"value": "18 m$", "label": "ne olduğu, en fazla 8 kelime"}]},
    {"type": "outro", "question": "tek soru, 6-12 kelime",
     "ctas": ["tek yumuşak çağrı"]}
  ]
}"""


# style.py deterministik: yasak kalip, emoji, buyuk harf yakalar ama YAZIM
# HATASI yakalayamaz - bir uretimde "dusunceleinizi" cikip karta basilmisti.
# Bu ikinci goz onu yakalamak icin. Karar kumesi SINIRLI ve somut: serbest
# birakilan model her metinde "daha iyi olabilir" der, yeniden uretim
# tetiklenir ve kota bosa gider.
QA_SCHEMA = """{
  "gozlem": "metni okudugunu gosteren tek cumle - neyi anlatiyor",
  "sorunlar": [
    {"alan": "pages[1].paragraph gibi yol",
     "tur": "yazim | kaynak_disi | anlamsiz",
     "aciklama": "tek cumle, somut"}
  ]
}"""


def qa_prompt(spec: dict, source_text: str) -> str:
    metinler = []
    for path, text in style.strings_of(spec):
        metinler.append(f"{path}: {text}")
    return "\n".join([
        "Asagida bir Instagram gonderisi icin uretilmis Turkce metinler var.",
        "Kaynak haber Ingilizce, metinler ondan yazildi.",
        "",
        "ONCE OKU, SONRA KARAR VER. 'gozlem' alanina metnin neyi anlattigini",
        "tek cumleyle yaz - bu, metne gercekten baktigindan emin olmak icin.",
        "",
        "SADECE su uc seyi bildir:",
        "  yazim      - yazim/imla hatasi, dusuk cumle, bozuk kelime",
        "               (ornek: 'dusunceleinizi', 'gelistirci')",
        "  kaynak_disi - kaynakta OLMAYAN bir iddia, sayi veya isim",
        "  anlamsiz   - cevrilirken anlami kaymis, Turkcesi tuhaf cumle",
        "",
        "BILDIRME: uslup tercihleri, 'daha iyi olabilir', 'daha vurucu",
        "olabilirdi', uzunluk yorumu, baslik onerisi. Bunlar senin isin degil.",
        "Metin kusursuz degilse bile bu uc kategoriye girmiyorsa SUS.",
        "Hicbir sorun yoksa 'sorunlar' bos liste olsun - bu normaldir.",
        "",
        "KAYNAK METIN:",
        source_text[:3000],
        "",
        "URETILEN METINLER:",
        *metinler,
        "",
        "SADECE su semada JSON dondur:",
        QA_SCHEMA,
    ])


def llm_review(spec: dict, source_text: str, model: str | None = None) -> list[str]:
    """LLM ikinci gozu. Bos liste = temiz.

    Hata durumunda BOS liste doner: QA'nin kendisi uretimi durdurmamali.
    """
    try:
        cevap = generate(qa_prompt(spec, source_text), model or HELPER_MODEL,
                         temperature=0.0)
    except SystemExit:
        print("  qa: model cevap vermedi, atlaniyor")
        return []

    gozlem = (cevap.get("gozlem") or "").strip() if isinstance(cevap, dict) else ""
    if gozlem:
        print(f"  qa gozlem: {gozlem[:70]}")

    problems = []
    for row in liste_al(cevap, "sorunlar"):
        tur = (row.get("tur") or "").strip()
        if tur not in ("yazim", "kaynak_disi", "anlamsiz"):
            continue  # karar kumesi disina cikmis, yok sayilir
        alan = (row.get("alan") or "?").strip()
        aciklama = (row.get("aciklama") or "").strip()
        problems.append(f"{alan}: [{tur}] {aciklama}")
    return problems


# Alintinin kaynakta gectigini dogrularken aranan kelime orani. Birebir
# eslesme istenmiyor: model tirnak, kesme isareti ve bosluklari sessizce
# duzeltiyor ve tam eslesme sarti ret oranini gereksiz sisiriyor. Ama
# %70 esik uydurmayi geciremez - uydurulmus alintinin kaynakla ortak
# kelimesi bu kadar olmuyor.
ALINTI_ESIK = 0.7
ALINTI_MIN_KELIME = 4
# Postun ayakta kalmasi icin gereken en az dogrulanmis olgu sayisi.
# Kaynagin uzunluguna gore olceklenir: model serbest birakilinca AZ olgu
# cikariyor (olcum: 1100 karakterlik uc kaynakli bir incelemeden yalnizca
# 3 olgu cikardi ve incelemelerin YARGISI - yani haberin ta kendisi -
# listeye hic girmedi). "kac bulursan o kadar" demek yetmiyor; tier
# dersinin tersi bu: serbestlik abartmaya degil TEMBELLIGE goturuyor
# cunku az olgu cikarmak az is demek.
MIN_OLGU = 2
BOL_KAYNAK_ESIK = 600      # karakter
MIN_OLGU_BOL = 4


def olgu_hedefi(source_text: str) -> int:
    return MIN_OLGU_BOL if len(source_text) > BOL_KAYNAK_ESIK else MIN_OLGU


# Kategori basina, postta MUTLAKA cevaplanmasi gereken soru. Kategori bir
# OLAY tipi oldugu icin her tipin kendi zorunlu bilgisi var ve bunlar
# birbirinin yerine gecmiyor: inceleme postunda "oyun nasil bulunmus"
# yoksa post haberi hic vermemis olur, duyuru postunda "ne zaman" yoksa
# okurun elinde bir sey kalmaz.
KATEGORI_SLOTLARI = {
    "inceleme": "kaynaklar oyunu NASIL buldu (genel yargi) ve en cok neyi elestirdi",
    "duyuru": "tam olarak NE duyuruldu ve ne zaman gelecegi belliyse o",
    "çıkış": "oyun NEREDE cikti (platformlar) ve fiyat/erisim bilgisi varsa o",
    "fragman": "fragmanda GORULEN somut sey - genel izlenim degil",
    "güncelleme": "NE degisti ve bu kimi etkiliyor",
    "gecikme": "yeni tarih ne ve gerekce aciklandi mi",
    "sızıntı": "ne sizdi ve kaynagin ne kadar guvenilir oldugu",
    "kapanma": "kac kisi etkilendi ve sebep aciklandi mi",
    "finansman": "ne kadar ve kimden",
}


def _kelimeler(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def dogrulanmis_olgular(draft: dict, source_text: str) -> tuple[set[int], list[str]]:
    """`cikarim` icindeki hangi olgular gercekten kaynaga dayaniyor?

    LLM veri verir, KOD dogrular - diakritik onarimindaki `fold`
    karsilastirmasiyla ayni desen. Model bir olguyu uydurursa alintisini
    kaynakta gosteremez ve o olgu dusur.
    """
    kaynak = set(_kelimeler(source_text))
    gecerli: set[int] = set()
    problems: list[str] = []

    for i, olgu in enumerate(draft.get("cikarim") or []):
        if not isinstance(olgu, dict):
            problems.append(f"cikarim[{i}]: nesne degil")
            continue
        alinti = str(olgu.get("alinti") or "")
        kelimeler = _kelimeler(alinti)
        if len(kelimeler) < ALINTI_MIN_KELIME:
            problems.append(f"cikarim[{i}]: alinti cok kisa "
                            f"({len(kelimeler)} kelime), en az {ALINTI_MIN_KELIME} olmali")
            continue
        oran = sum(1 for k in kelimeler if k in kaynak) / len(kelimeler)
        if oran < ALINTI_ESIK:
            problems.append(f"cikarim[{i}]: alinti kaynakta bulunamadi "
                            f"(kelimelerin %{oran * 100:.0f}'i tutuyor). "
                            f"kaynaktan BIREBIR kopyala, kendi cumleni yazma")
            continue
        gecerli.add(i)

    return gecerli, problems


def check_dayanak(draft: dict, source_text: str) -> list[str]:
    """Her govde cumlesi kaynaktan AYRI bir olguya dayanmak zorunda.

    Neden var: 22 kuralin hepsi YASAKTI ve hicbir sey soylemeyen cumle
    hicbir yasagi ihlal edemez. Olcum (20260831-the-blood-of-dawnwalker):
    "siradan gozuken arayislar oyuncuyu hizlica karanlik atmosfere cekiyor"
    maddesi 22 kuralin 22'sini de gecti. Oysa kaynakta o maddenin yerini
    alacak SOMUT bir anekdot vardi (turba kazicisi cukura dusuyor, magarada
    bir ses duyuluyor) ve model onu soyutlayip attigi icin post bosaldi.

    Mekanizma: model once `cikarim` listesini yaziyor (semada ilk sirada,
    yani metni kendi cikarimina KOSULLANARAK yaziyor), sonra her paragraf
    ve her madde o listeden bir numara gosteriyor.

    Numara TEKRAR EDILEMEZ. Bunun yan etkisi tasarim geregi: kaynakta 6
    olgu varsa post 6 govde alanindan uzun olamaz. Yani sayfa sayisi artik
    modelin tahminine degil kaynagin YOGUNLUGUNA bagli - dolgu sayfa
    yazmak yapisal olarak imkansiz.
    """
    gecerli, problems = dogrulanmis_olgular(draft, source_text)

    # ⚠️ Olgu SAYISI bilerek ret sebebi DEGIL. Denendi ve geri alindi
    # (olcum 2026-09-01): "en az 4 olgu" kurali konunca uretim uc denemenin
    # ucunde de takildi, cunku hedefli_onar metin yazar - LISTEYE OLGU
    # EKLEYEMEZ. Yani onarilamaz bir ihlaldi ve her seferinde bir deneme
    # yakiyordu. DEVIR kurali: onarilamayan kural eklenmez.
    #
    # Uzerine dusununce esik zaten yanlis kaldirac: model 3 olgu cikarip
    # 3 govde alani yazdiysa post KISA ama durust. Asil onemli olan her
    # alanin AYRI bir olguya dayanmasi ve o zaten asagida zorunlu.
    # "Daha derin kaz" baskisi istemde duruyor, filtrede degil.
    if len(gecerli) < MIN_OLGU:
        problems.append(
            f"cikarim: yalnizca {len(gecerli)} dogrulanmis olgu var, en az "
            f"{MIN_OLGU} gerekli. alintilari kaynaktan BIREBIR kopyala")
        return problems

    kullanilan: dict[int, str] = {}

    def kullan(idx, yol: str) -> None:
        if not isinstance(idx, int) or isinstance(idx, bool):
            problems.append(f"{yol}: dayanak numarasi yok. "
                            f"cikarim listesinden bir numara yaz")
            return
        if idx not in gecerli:
            problems.append(f"{yol}: dayanak {idx} gecerli bir olgu degil "
                            f"(gecerliler: {sorted(gecerli)})")
            return
        if idx in kullanilan:
            problems.append(f"{yol}: dayanak {idx} zaten {kullanilan[idx]} "
                            f"tarafindan kullanildi. her alan AYRI bir olgu "
                            f"anlatmali, ayni seyi iki kez soyleme")
            return
        kullanilan[idx] = yol

    for index, page in enumerate(draft.get("pages") or []):
        if not isinstance(page, dict) or page.get("type") != "text":
            continue
        yol = f"pages[{index}]"
        if (page.get("paragraph") or "").strip():
            kullan(page.get("dayanak"), f"{yol}.paragraph")
        bullets = page.get("bullets") or []
        dayanaklar = page.get("bullet_dayanak") or []
        if len(dayanaklar) != len(bullets):
            problems.append(
                f"{yol}: {len(bullets)} madde var ama {len(dayanaklar)} "
                f"dayanak yazilmis. her maddenin bir dayanagi olmali")
            continue
        for i, idx in enumerate(dayanaklar):
            kullan(idx, f"{yol}.bullets[{i}]")

    return problems


def autofix_dayanak(draft: dict, source_text: str) -> dict:
    """Tekrar eden dayanak gosteren MADDELERI sil. Yeniden uretim isteme.

    DEVIR kurali: "kural mutlaksa ve duzeltmesi belirsizlik tasimiyorsa
    filtre duzeltir, modeli yeniden calistirmaz" (buyuk harf dersi).
    Burada da oyle: bir madde zaten kullanilmis bir olguyu gosteriyorsa
    o madde TANIMI GEREGI tekrardir, silmek postu bozamaz - sadece
    soylenmis bir seyi ikinci kez soylemekten kurtarir.

    Paragraflara dokunulmuyor: sayfanin govdesi silinemez, orada tekrar
    varsa yeniden uretim gerekir.
    """
    gecerli, _ = dogrulanmis_olgular(draft, source_text)
    kullanilan: set[int] = set()
    silinen = 0
    dusen_sayfa = 0
    kalan_sayfalar = []

    for page in draft.get("pages") or []:
        if not isinstance(page, dict) or page.get("type") != "text":
            kalan_sayfalar.append(page)
            continue

        # SAYFANIN GOVDESI tekrar mi? Paragraf zaten soylenmis bir olguyu
        # anlatiyorsa o sayfa dolgudur; maddeleri de ikincil kalir.
        # Sayfayi dusurmek metni bozmaz - soylenmis bir seyi ikinci kez
        # soylemekten kurtarir. "Dolgu sayfa uretme" kurali boylece
        # istemde ricadan cikip kodda kurala donusuyor.
        # Yalnizca text sayfasi dusuyor: cover ilk, outro son kaliyor,
        # yani sayfa duzeni bozulmuyor.
        idx = page.get("dayanak")
        gecerli_mi = (isinstance(idx, int) and not isinstance(idx, bool)
                      and idx in gecerli)
        if (page.get("paragraph") or "").strip() and gecerli_mi and idx in kullanilan:
            dusen_sayfa += 1
            continue
        if gecerli_mi:
            kullanilan.add(idx)
        kalan_sayfalar.append(page)

        bullets = page.get("bullets") or []
        dayanaklar = page.get("bullet_dayanak") or []
        if len(dayanaklar) != len(bullets):
            # Model duzenli olarak 2 madde yazip 1 dayanak veriyor. Bu da
            # mekanik: dayanagi olmayan madde, dayanagi olmadigi icin
            # zaten "kaynakta karsiligi gosterilememis" demektir - kisa
            # kesip atiyoruz. Model yeniden calistirilmiyor.
            kes = min(len(dayanaklar), len(bullets))
            silinen += len(bullets) - kes
            bullets, dayanaklar = bullets[:kes], dayanaklar[:kes]
        kalan_b, kalan_d = [], []
        for bullet, idx in zip(bullets, dayanaklar):
            if (isinstance(idx, int) and not isinstance(idx, bool)
                    and idx in gecerli and idx not in kullanilan):
                kullanilan.add(idx)
                kalan_b.append(bullet)
                kalan_d.append(idx)
            else:
                silinen += 1
        # Butun maddeler dusmusse sayfa paragrafiyla ayakta kalir; bos
        # `bullets` listesi card.html'i bozmuyor.
        page["bullets"] = kalan_b
        page["bullet_dayanak"] = kalan_d

    if dusen_sayfa:
        draft["pages"] = kalan_sayfalar
    if silinen or dusen_sayfa:
        print(f"  dayanak onarimi: {silinen} tekrar eden madde, "
              f"{dusen_sayfa} dolgu sayfa silindi")
    return draft


def check_structure(draft: dict) -> list[str]:
    """Sayfa düzeni denetimi. Sayfa SAYISI serbest, DÜZENİ değil.

    Uzunluk kararı modelde ama sınırı kodda: üst sınır olmadan uzun haberde
    14 sayfa yazıyor ve Instagram 10'dan fazlasını almıyor. Eksik alan da
    burada yakalanıyor - render.py'de yakalanırsa zincir kırılır, burada
    yakalanırsa yeniden üretim tetiklenir.
    """
    pages = draft.get("pages")
    if not isinstance(pages, list) or not pages:
        return ["pages: sayfa yok"]

    problems: list[str] = []
    if len(pages) > MAX_PAGES:
        problems.append(f"pages: {len(pages)} sayfa var, en fazla {MAX_PAGES} olabilir")

    for index, page in enumerate(pages):
        yol = f"pages[{index}]"
        if not isinstance(page, dict):
            problems.append(f"{yol}: sayfa bir nesne degil")
            continue
        tur = page.get("type")
        if tur not in PAGE_TYPES:
            problems.append(f"{yol}: bilinmeyen sayfa tipi {tur!r}")
            continue
        if index == 0 and tur != "cover":
            problems.append(f"{yol}: ilk sayfa cover olmali ({tur} yazilmis)")
        if index > 0 and tur == "cover":
            problems.append(f"{yol}: ikinci bir cover sayfasi var")
        if tur == "outro" and index != len(pages) - 1:
            problems.append(f"{yol}: outro yalnizca son sayfa olabilir")
        # Bos alanlar: card.html bunlari basmaya calisirken bos kutu birakir
        # ya da patlar.
        if tur in ("cover", "text", "numbers") and not (page.get("title") or "").strip():
            problems.append(f"{yol}: {tur} sayfasinin basligi bos")
        if tur == "numbers" and not (page.get("metrics") or []):
            problems.append(f"{yol}: numbers sayfasinda metrics bos")
        if tur == "outro":
            if not (page.get("question") or "").strip():
                problems.append(f"{yol}: outro sorusu bos")
            if not (page.get("ctas") or []):
                problems.append(f"{yol}: outro cagrisi bos")

    if len(pages) == 1 and pages[0].get("type") != "cover":
        problems.append("pages: tek sayfalik post yalnizca cover olabilir")
    if len(pages) > 1 and pages[-1].get("type") != "outro":
        problems.append("pages: tek sayfadan uzun postta son sayfa outro olmali")

    rakam = sum(1 for p in pages if isinstance(p, dict) and p.get("type") == "numbers")
    if rakam > 1:
        problems.append(f"pages: {rakam} rakam sayfasi var, en fazla 1 olmali")
    return problems


DIAKRITIK_SEMA = """{
  "metinler": ["duzeltilmis metin, girdiyle AYNI sirada, ayni sayida"]
}"""


def diakritik_onar(spec: dict, model: str) -> dict:
    """İşaretsiz Türkçeyi onar: metni yeniden yazdırma, işaretleri geri koy.

    Neden ayrı bir tur: yedek model (`flash-lite`) düzenli olarak "temali",
    "on incelemeler" gibi işaretsiz Türkçe yazıyor ve üslup filtresine
    takılıyor. Yeniden üretim istemek işe yaramıyordu - model aynı hatayı
    tekrarlıyor, üç deneme de yanıyor ve post hiç çıkmıyordu. Bu, ana modelin
    kotası dolduğunda sistemin fiilen durması demekti.

    İş bölümü korunuyor: LLM ÖNERİR, KOD DOĞRULAR. Dönen her metin, işaretler
    düşürüldüğünde orijinaliyle birebir aynı olmak zorunda (`style.fold`).
    Model kelime değiştirmeye kalkarsa o metin yok sayılır ve eskisi kalır -
    yani bu tur metni bozamaz, en kötü ihtimalle bir şey düzeltmez.
    """
    orijinal = [t for _, t in style.strings_of(spec)]
    if not any(style.isaretsiz(t) for t in orijinal):
        return spec

    prompt = "\n".join([
        "Aşağıdaki Türkçe metinlerde Türkçe harfler eksik yazılmış.",
        "Örnek: \"temali\" -> \"temalı\", \"on inceleme\" -> \"ön inceleme\",",
        "\"gorunuyor\" -> \"görünüyor\", \"cikis\" -> \"çıkış\".",
        "",
        "SADECE eksik işaretleri koy. Başka HİÇBİR ŞEY değiştirme:",
        "kelime ekleme, kelime çıkarma, sıra değiştirme, düzeltme yapma.",
        "Zaten doğru yazılmış metinleri olduğu gibi geri ver.",
        "İngilizce oyun adlarına dokunma (\"total war\" böyle kalır).",
        "",
        "Girdiyle AYNI SAYIDA ve AYNI SIRADA metin döndür.",
        "",
        "METİNLER:",
        *[f"{i}. {t}" for i, t in enumerate(orijinal, 1)],
        "",
        "SADECE şu şemada JSON döndür:",
        DIAKRITIK_SEMA,
    ])

    try:
        cevap = generate(prompt, model, temperature=0.0)
    except (SystemExit, GecersizCevap):
        print("  diakritik onarimi yapilamadi, atlaniyor")
        return spec

    gelen = liste_al(cevap, "metinler")
    guvenli, duzeltilen, reddedilen = [], 0, 0
    for sira, eski in enumerate(orijinal):
        yeni = gelen[sira] if sira < len(gelen) else None
        if not isinstance(yeni, str) or yeni == eski:
            guvenli.append(eski)
            continue
        # DOGRULAMA: isaretler dusurulunce metin ayni kalmali.
        if style.fold(yeni) != style.fold(eski):
            reddedilen += 1
            guvenli.append(eski)
            continue
        duzeltilen += 1
        guvenli.append(yeni)

    print(f"  diakritik onarimi: {duzeltilen} metin duzeltildi"
          + (f", {reddedilen} reddedildi (kelime degismis)" if reddedilen else ""))
    return style.replace_strings(spec, guvenli)


def hedefli_onar(spec: dict, problems: list[str], source_text: str,
                 model: str) -> dict:
    """Takılan alanları onar. Metni BAŞTAN yazdırmaz.

    Neden: bir ihlal yüzünden bütün postu çöpe atmak hem kotayı yakıyor
    hem de sonucu belirsiz - model yeni metinde başka bir kurala takılıyor.
    Ölçüldü (2026-08-31): iki üretim üst üste "3 denemede temiz çıktı
    alınamadı" diye düştü ve hiç post çıkmadı.

    İş bölümü aynı: LLM ÖNERİR, KOD DOĞRULAR. Onarılmış metin ancak
    ihlal SAYISINI düşürüyorsa kabul ediliyor; artırıyorsa ya da
    değiştirmiyorsa eski metin kalıyor. Yani bu tur postu bozamaz.
    """
    orijinal = [t for _, t in style.strings_of(spec)]
    if not orijinal or not problems:
        return spec

    prompt = "\n".join([
        "Aşağıdaki Instagram gönderisi metinleri üslup denetiminden geçemedi.",
        "",
        "BULUNAN SORUNLAR:",
        *[f"- {p}" for p in problems[:10]],
        "",
        "GÖREV: SADECE sorunlu metinleri düzelt. Sorunu olmayan metni",
        "OLDUĞU GİBİ geri ver - değiştirme, güzelleştirme, kısaltma.",
        "Düzeltirken anlamı koru: aynı şeyi kurallara uyarak söyle.",
        "",
        "Girdiyle AYNI SAYIDA ve AYNI SIRADA metin döndür.",
        "",
        "METİNLER:",
        *[f"{i}. {t}" for i, t in enumerate(orijinal, 1)],
        "",
        "SADECE şu şemada JSON döndür:",
        DIAKRITIK_SEMA,
    ])

    try:
        cevap = generate(prompt, model, temperature=0.3)
    except (SystemExit, GecersizCevap):
        print("  hedefli onarim yapilamadi, atlaniyor")
        return spec

    gelen = liste_al(cevap, "metinler")
    # UZUNLUK ESIT OLMAK ZORUNDA. Eksik liste gelirse sira kayar ve metinler
    # yanlis alanlara oturur: caption baslik yerine gecebilir. Diakritik
    # onariminda bunu fold karsilastirmasi engelliyor, burada engelleyen tek
    # sey uzunluk - onarim serbestce yeniden yaziyor, icerik kiyaslanamiyor.
    if len(gelen) != len(orijinal):
        print(f"  hedefli onarim: {len(gelen)} metin geldi, {len(orijinal)} "
              f"bekleniyordu - sira kaymasin diye atlandi")
        return spec
    yeni = [g if isinstance(g, str) and g.strip() else eski
            for g, eski in zip(gelen, orijinal)]
    aday = style.autofix_suffixes(style.autofix_lowercase(
        style.replace_strings(spec, yeni)))

    onceki = len(problems)
    sonraki = len(check_structure(aday) + check_dayanak(aday, source_text)
                  + style.review(aday, source_text))
    if sonraki < onceki:
        print(f"  hedefli onarim: {onceki} ihlal -> {sonraki}")
        return aday
    print(f"  hedefli onarim ise yaramadi ({onceki} -> {sonraki}), eski metin kaldi")
    return spec


def build_prompt(candidate: dict, source_text: str, mode: str,
                 problems: list[str] | None = None,
                 soru_tipi: str = "tercih") -> str:
    sources = ", ".join(candidate["sources"])
    mode_hint = WRITING_MODES[mode]

    parts = [
        "Bir Türkçe indie oyun haberleri instagram hesabı için post metni yazıyorsun.",
        "",
        "KAYNAK MATERYAL (İngilizce, birden fazla haber sitesinden):",
        source_text,
        "",
        f"Bu haberi {len(candidate['sources'])} kaynak yazmış: {sources}",
        "",
        "GÖREV: bu haberi Türkçeye çevirip instagram carousel metnine dönüştür.",
        f"Yazım modu: {mode} - {mode_hint}",
        "",
        "ÖNCE ÇIKARIM, SONRA YAZIM. Bu sıra zorunlu ve şemada da bu sırada.",
        "Metni yazmadan önce 'cikarim' listesini doldur: kaynakta okurun",
        "bilmediği SOMUT bilgiler. En çarpıcı olan en başa.",
        "  - somut = belirli bir olay, isim, sayı, anekdot, karşılaştırma.",
        "    \"oyun karanlık bir atmosfere sahip\" somut DEĞİL, yorumdur.",
        "    \"turba kazıcısını aramaya gidiyorsun, mağarada bir ses",
        "    duyuyorsun\" somuttur.",
        "  - her olgu için 'alinti' alanına o bilginin dayandığı kaynak",
        "    parçasını BİREBİR kopyala. İngilizce kalsın, çevirme, kısaltma.",
        "    Kaynakta olmayan bir cümle yazarsan kod yakalar ve o olgu düşer.",
        "  - kaç olgu bulursan o kadar yaz. Uydurma, ama aramadan da geçme:",
        "    kaynağın en ilginç ayrıntısı genelde en kolay atlanandır.",
        "",
        "SONRA her gövde alanı bu listeden BİR numara gösterir:",
        "  - 'dayanak': o sayfanın paragrafının dayandığı olgunun numarası",
        "  - 'bullet_dayanak': maddelerin numaraları, maddelerle AYNI sırada",
        "    ve aynı sayıda",
        "  - BİR NUMARA İKİ KEZ KULLANILAMAZ. Her paragraf ve her madde",
        "    kaynaktan AYRI bir şey anlatmak zorunda.",
        "  - Bunun doğal sonucu: 5 olgu çıkardıysan 5 gövde alanından uzun",
        "    post yazamazsın. Sayfa sayısını kaynağın verdiği malzeme",
        "    belirler. Az malzeme varsa KISA yaz, sayfa doldurmak için",
        "    aynı şeyi başka kelimelerle tekrar etme.",
        "  - cover ve outro sayfaları dayanak istemez.",
        "",
        "KURALLAR (hepsi zorunlu):",
        "1. TÜRKÇE KARAKTERLERİ DOĞRU KULLAN: ı, ş, ğ, ü, ö, ç. "
        "\"aynı\" yaz, \"ayni\" yazma. \"hazırlanıyor\" yaz, \"hazirlaniyor\" yazma. "
        "\"büyük\" yaz, \"buyuk\" yazma. Bu kuralı ihlal eden metin reddedilir.",
        "2. Tamamen küçük harf. Özel isimler de küçük. Tek istisna yok.",
        "3. Çeviri değil, yeniden anlatım. Kaynak cümleyi birebir çevirmeyeceksin.",
        "4. Kaynak metinde GEÇMEYEN hiçbir sayı yazamazsın. Sayı uydurmak yasak.",
        "   Kaynakta rakam yoksa 'numbers' sayfasını HİÇ ÜRETME.",
        "5. Yasak kelimeler: işte, peki, devrim niteliğinde, çığır açan, adeta,",
        "   tam anlamıyla, sonuç olarak, yapay zeka destekli.",
        "6. Em-dash (uzun çizgi) ve eğik tırnak kullanma. Düz tırnak ve kısa çizgi kullan.",
        "7. Emoji yok. Hashtag yok.",
        "8. Başlık ve paragraf soru cümlesiyle BAŞLAMAYACAK. Sadece son sayfada soru olur.",
        "9. 'a, b ve c' şeklinde üç öğeli liste kalıbı kurma.",
        "10. Yabancı özel isimlere Türkçe ek eklerken okunuşa göre seç:",
        "    godot'u (godot'yu DEĞİL), steam'de, unity'yi, valve'ın, xbox'ta, epic'te.",
        "11. Son sayfanın SORUSU cevabı \"evet\" olan bir soru OLAMAZ.",
        "    \"... ister misin\", \"... dener miydiniz\", \"... merak ediyor",
        "    musun\" gibi kalıplar YASAK: okurun söyleyecek bir şeyi kalmıyor.",
        "    Soru, cevaplamak için düşünmeyi gerektirmeli.",
        f"    Bu postun soru tipi: {soru_tipi} - {SORU_TIPLERI[soru_tipi]}",
        "    Soru haberdeki SOMUT bir şeye değsin, genel temenniye değil.",
        "12. Son sayfadaki çağrı SORUYU TEKRARLAMAZ. Soru zaten yorum",
        "    davetidir; çağrı ondan farklı bir cümle olmalı ya da okura",
        "    somut bir şey söylemeli. 'düşüncelerini yorumlarda paylaş' gibi",
        "    her posta uyan bir cümle yazma - o cümle her postta aynı çıkıyor",
        "    ve hesabı otomatik gösteriyor. 'beğen', 'paylaş', 'takip et'",
        "    yazma; takip daveti kartın kendisinde sabit metin olarak var.",
        "13. Okura \"SEN\" diye hitap et, \"siz\" değil. \"ne düşünüyorsun\"",
        "    yaz, \"ne düşünüyorsunuz\" yazma; \"senin rafında\" yaz,",
        "    \"raflarınızda\" yazma. Kartlar samimi ve küçük harfli; resmi",
        "    çoğul dil o tasarımla çelişiyor ve metni bülten gibi gösteriyor.",
        "14. GAZETECİ KELİMELERİ yasak: 'yapım' (oyuna oyun de), 'söz konusu',",
        "    'dikkat çekiyor', 'yer alıyor', 'imza attı', 'hayata geçiriyor'.",
        "    Edilgen kalıplardan kaç: 'taşınıyor' yerine 'taşıyor', 'sunuluyor'",
        "    yerine 'sunuyor'. Kim ne yapıyorsa onu yaz.",
        "15. Maddeler ETİKET DEĞİL, cümle olacak. 'detaylı dekorasyon",
        "    seçenekleri' bir şey söylemiyor; 'raflara istediğin maketi",
        "    yerleştirebiliyorsun' söylüyor. Her maddede bir fiil olsun.",
        "16. Metnin bir yerinde TAVIR olsun: neyi tuhaf, komik, şüpheli ya da",
        "    beklenmedik buluyoruz. Haber bültenleri tarafsızdır, bu hesap",
        "    değil. Abartma ve reklam dili değil - gözlem.",
        "17. Yazım hatası yapma. Metni yazdıktan sonra harf harf kontrol et.",
        "18. search_name ÇEVİRİLMEZ ve KISALTILMAZ. Kaynakta hangi oyundan",
        "    bahsediliyorsa onun tam İngilizce adını yaz, sürüm numarası dahil.",
        "    Haber \"the witcher 3\" hakkındaysa \"The Witcher\" yazmak HATADIR;",
        "    yanlış oyunun görselleri basılır. Haberin konusu bir oyun değilse",
        "    (etkinlik, şirket, konsol, sektör haberi) null yaz.",
        "19. image_candidates: haberin konusu bir oyun OLMASA BİLE, metinde adı",
        "    geçen ve görseli bu haberi temsil edebilecek oyunları buraya yaz.",
        "    Örnek: haber yeni bir konsol ailesi hakkında ama içinde \"Elder",
        "    Scrolls 6 o konsola özel mi olacak\" tartışılıyorsa",
        "    [\"The Elder Scrolls VI\"] yazılır - o oyunun görseli haberi",
        "    temsil eder. Sadece adı GEÇEN oyunları yaz, konuyla ilgisi",
        "    kurulamayan bir oyunu doldurma; okur görseli haberle",
        "    ilişkilendiremezse kart yanıltıcı olur.",
        "20. caption Instagram'da kartların altında görünecek metin.",
        "    Kartlarda yazanı TEKRARLAMA - okur kartları zaten gördü.",
        "    Haberin bağlamını ver: bu neden önemli, öncesinde ne olmuştu.",
        "    2-4 cümle. Sonunda en fazla 2 hashtag, küçük harf. Üslup",
        "    kuralları burada da geçerli: emoji yok, büyük harf yok,",
        "    \"işte\" gibi kalıplar yok.",
        "21. representative_games: bazı haberlerin konusu bir oyun değildir",
        "    (konsol, şirket, etkinlik, sektör, donanım). Bu kartlar şu ana",
        "    kadar görselsiz basılıyordu ve sayfa boş duruyordu.",
        "    Bu alana, haberi GÖRSEL OLARAK temsil edebilecek oyunları yaz.",
        "    Ölçütü sen belirle - sana konu konu kural vermiyorum, çünkü her",
        "    haber farklı ve doğru bağı sen kurabilirsin. Tek şart: okur",
        "    görseli gördüğünde haberle bağ kurabilmeli.",
        "    Bağ kurmanın yolu çoktur: haber bir platform/konsol hakkındaysa",
        "    o platformla özdeşleşmiş bir oyun, bir stüdyo hakkındaysa o",
        "    stüdyonun bilinen işi, bir tür veya topluluk konusuysa o türün",
        "    tanınmış örneği. Bunlar örnek, liste değil - kendi bağını kur.",
        "    Önce gerçekten dene. Yalnızca hiçbir makul bağ kuramıyorsan boş",
        "    bırak; ilgisiz bir oyun yazmak görselsiz bırakmaktan kötüdür.",
        "22. series_fallback: konu oyununun görseli az olabilir (henüz",
        "    çıkmamış oyunlarda sık). Aynı serinin/evrenin görsel bakımından",
        "    zengin oyunlarını buraya yaz - haber \"The Elder Scrolls VI\"",
        "    hakkındaysa [\"The Elder Scrolls V: Skyrim\"] gibi. Sadece",
        "    gerçekten AYNI seri olanları yaz; benzer türde başka bir oyunu",
        "    yazmak okuru yanıltır. Uygun yoksa boş liste.",
        "",
        "KAPAK BAŞLIĞI: okurun TANIDIĞI adı kullan, resmi olanı değil.",
        "Bir stüdyonun kendi adı çoğu okur için yeni bir bilgidir; o ekibin",
        "bilinen işi ise anında tanınır. \"witcher ekibinden\" yazmak",
        "\"cd projekt red ekibinden\" yazmaktan hem kısadır hem okurun",
        "durmasını sağlar. Tanınırlığı okur tarafından ölç, sektör",
        "tarafından değil. Olayın ne olduğunu başlığa sıkıştırmaya çalışma -",
        "onu kategori kutusu zaten söylüyor.",
        "",
        f"KATEGORİ listesi (birini seç): {', '.join(CATEGORIES)}",
        "Kategori haberde NE OLDUĞUNU söyler, haberin KONUSUNU değil.",
        "Seçtiğin kategorinin ZORUNLU bilgisi postta mutlaka bulunmalı -",
        "kaynakta varsa çıkarım listesine girer ve bir gövde alanında anlatılır:",
        *[f"  {k}: {v}" for k, v in KATEGORI_SLOTLARI.items()],
        "Kaynaklar bir oyunu değerlendiriyorsa kategori \"inceleme\"dir;",
        "oyunun hangi stüdyodan geldiği kategoriyi değiştirmez. Bu kutu",
        "kapakta basılıyor ve okurun olayı anlamasını sağlayan tek yer,",
        "çünkü başlık genelde oyunu tanıtır, olayı değil.",
        "",
        f"SAYFA SAYISINI ÇIKARIM LİSTESİ BELİRLER (en az {MIN_PAGES}, en "
        f"fazla {MAX_PAGES}).",
        "Her metin sayfası 2-3 olgu taşır: bir paragraf + bir iki madde.",
        "  - 2-3 olgu  -> 1 metin sayfası",
        "  - 4-6 olgu  -> 2 metin sayfası",
        "  - 7-9 olgu  -> 3 metin sayfası",
        "⚠️ HER OLGUYA AYRI SAYFA AÇMA. Dört olgu için dört sayfa yazmak",
        "postu uzatır ama zenginleştirmez; okur her kaydırmada tek cümle",
        "görür ve yarıda bırakır. Aynı sayfada duran akraba olgular birbirini",
        "güçlendirir. Yalnızca konu gerçekten değiştiğinde yeni sayfa aç.",
        "Az kartta çok şey söylemek, çok kartta az şey söylemekten iyidir.",
        "",
        "SAYFA DÜZENİ (bu kısım sabit):",
        "  - ilk sayfa her zaman cover",
        "  - 1 sayfadan uzunsa son sayfa outro, arada text sayfaları",
        "  - kaynakta anlamlı rakam varsa EN FAZLA bir numbers sayfası",
        "  - tek sayfalık postta SADECE cover olur, outro yazma",
        "",
        "is_leak: haber sızıntı, datamine veya izinsiz sızan materyale dayanıyorsa true.",
        "Bu yalnızca kartın kategori etiketini belirler. GÖRSEL ALANLARINI",
        "ETKİLEMEZ: sızıntı haberinde de search_name, image_candidates,",
        "series_fallback ve representative_games doldurulur. Görsel yine",
        "resmi materyalden seçilecek, seçimi kod yapıyor.",
        "",
        "SADECE şu şemada JSON döndür, başka hiçbir şey yazma:",
        SCHEMA,
    ]

    if problems:
        parts += [
            "",
            "ÖNCEKİ DENEMEN ŞU HATALARLA REDDEDİLDİ, bunları düzelt:",
            *[f"- {p}" for p in problems],
        ]

    return "\n".join(parts)


# ----------------------------------------------------------------- akis

def source_text_of(candidate: dict) -> str:
    """Kumedeki tum uyelerin baslik+ozetini birlestir.

    Tam makale metni cekilmiyor (kazima yapmamak icin). Birden fazla kaynagin
    ozeti bir arada zaten tek ozetten daha zengin oluyor.
    """
    blocks = []
    for member in candidate["members"]:
        blocks.append(f"[{member['source_id']}] {member['title']}\n{member['summary']}")
    return "\n\n".join(blocks)


def to_render_spec(draft: dict, tier: str, candidate: dict, index: int = 0,
                   model: str | None = None) -> dict:
    """LLM ciktisini render.py'in bekledigi tarife cevir."""
    is_leak = bool(draft.get("is_leak"))
    category = draft.get("category", "")
    if category not in CATEGORIES:
        category = "sızıntı" if is_leak else "güncelleme"

    pages = []
    for page in draft["pages"]:
        page = dict(page)
        # Gorsel secimi images.py'nin isi, burasi sadece yer tutucu.
        page["image"] = "assets/placeholder.png"
        pages.append(page)

    return {
        "_kaynak": candidate["url"],
        # /yeniden komutu ayni adayi tekrar yazdirabilsin diye sira saklaniyor.
        "_aday_index": index,
        # Adayin TAM kaydi taslakta duruyor. Sebep: /yeniden AYRI bir Actions
        # calismasinda isleniyor ve candidates.json git disi - orada dosya
        # hic yok, yani sira numarasi tek basina ise yaramiyordu (uretim
        # "basarisiz" diyordu). Yeniden taratmak da cozum degil: sira degisir
        # ve ayni numara baska habere denk gelir. menu.json ayni sebeple
        # adayin tamamini tasiyor.
        "_aday": candidate,
        "_kaynak_sayisi": candidate["source_count"],
        # Cikarim listesi taslakta KALIYOR (alt cizgi: karta basilmaz, uslup
        # denetimine girmez). Sebep: bir postun neden zayif ciktigini sonradan
        # anlamanin tek yolu, modelin kaynaktan NE cikardigini gormek. Kotu
        # post ya kotu cikarimdan gelir ya iyi cikarimin kotu kullanilmasindan
        # ve ikisi tamamen farkli sorunlar.
        "_cikarim": draft.get("cikarim") or [],
        "_is_leak": is_leak,
        # Hangi model yazdi. Ana modelin kotasi dolunca yedege dusuluyor;
        # Telegram ozetinde gorunsun ki uslup farki fark edilirse sebebi
        # bilinsin.
        "_model": model,
        "tier": tier,
        "category": category,
        # Instagram gonderi metni. Elle paylasimda da ise yariyor: /bana ile
        # kartlari elle alirken caption da Telegram'a dusuyor, kopyalayip
        # yapistiriyorsun.
        "caption": draft.get("caption", ""),
        "game": draft.get("game", ""),
        # IGDB aramasi bu alanla yapiliyor; goruntude "game" kullanilir.
        "search_name": draft.get("search_name"),
        # Haberin konusu bir oyun olmasa da metinde gecen oyunlar gorsel
        # icin kullanilabilir: "xbox konsol ailesi" haberi Elder Scrolls 6'yi
        # tartisiyorsa o oyunun gorseli haberi temsil eder. Kredi yine
        # IGDB'nin sirket verisinden geliyor, telif kurali degismiyor.
        "image_candidates": [c for c in (draft.get("image_candidates") or [])
                             if c and str(c).lower() != "none"][:3],
        # Konu oyununun gorseli sayfalara yetmezse ayni seriden tamamlanir.
        # Kapak yine konu oyunundan basilir (images.py), kredi sayfa basina.
        "series_fallback": [c for c in (draft.get("series_fallback") or [])
                            if c and str(c).lower() != "none"][:2],
        # Konusu oyun olmayan haberler (konsol, sirket, etkinlik) icin son
        # care. Adi gecen oyun yoksa kart gorselsiz kaliyordu.
        "representative_games": [c for c in (draft.get("representative_games") or [])
                                 if c and str(c).lower() != "none"][:3],
        # Kucuk harfe cevriliyor: studio artik uslup denetiminden muaf
        # (buyuk harfli Ingilizce ad olabilir) ama karta basilan her sey
        # kucuk harf. images.py bunu IGDB verisiyle zaten eziyor.
        "credit": (draft.get("studio") or "").lower() or None,
        "pages": pages,
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post metin uretici")
    ap.add_argument("--list-models", action="store_true", help="kullanilabilir modelleri listele")
    ap.add_argument("--index", type=int, default=1, help="candidates.json'daki sira (1'den baslar)")
    ap.add_argument("--tier", default="B", choices=list("CBAS"),
                    help="gecici: tier.py yazilana kadar elle veriliyor")
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))
    # VARSAYILAN ACIK: QA ayri modelde calisiyor (HELPER_MODEL, gunde 500
    # istek) ve uretim butcesini yemiyor. Yazim hatasi karta basilmadan
    # yakalansin.
    ap.add_argument("--no-qa", dest="qa", action="store_false", default=True,
                    help="LLM ikinci gozunu kapat")
    ap.add_argument("--temperature", type=float, default=0.95)
    ap.add_argument("--mode", choices=list(WRITING_MODES), default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--draft", default=None,
                    help="var olan taslagi AYNI haberle bastan yaz (/yeniden)")
    args = ap.parse_args()

    if args.list_models:
        list_models()
        return 0

    if args.draft:
        # Yeniden yazim: kaynak candidates.json degil, taslagin KENDISI.
        # O dosya git disi ve /yeniden ayri bir Actions calismasinda
        # islendigi icin orada hic bulunmuyor.
        draft_path = Path(args.draft)
        eski = json.loads(draft_path.read_text(encoding="utf-8"))
        candidate = eski.get("_aday")
        if not candidate:
            sys.exit("taslakta kaynak kaydi (_aday) yok: bu taslak eski bicimde "
                     "uretilmis, yeniden yazilamiyor.")
        index = eski.get("_aday_index", 0)
        print(f"yeniden yazim: {draft_path.name}")
    else:
        if not CANDIDATES_FILE.exists():
            sys.exit("state/candidates.json yok. Once: py -3.12 src/fetch.py")

        data = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
        candidates = data["candidates"]
        if not 1 <= args.index <= len(candidates):
            sys.exit(f"--index 1..{len(candidates)} arasinda olmali")
        candidate = candidates[args.index - 1]
        index = args.index

    source_text = source_text_of(candidate)
    mode = args.mode or random.choice(list(WRITING_MODES))
    # Son sayfanin soru tipi de her uretimde degisiyor: sabit birakilinca
    # model her postta ayni kalibi ("... ister miydiniz") yaziyordu.
    soru_tipi = random.choice(list(SORU_TIPLERI))

    print(f"aday: {candidate['title'][:70]}")
    print(f"kaynak sayisi: {candidate['source_count']} ({', '.join(candidate['sources'])})")
    print(f"yazim modu: {mode} | soru tipi: {soru_tipi}\n")

    problems: list[str] = []
    # Hicbir deneme temiz cikmazsa en az ihlalli taslak yollanir.
    en_iyi: tuple[int, dict, list[str]] | None = None
    aktif_model = args.model
    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = build_prompt(candidate, source_text, mode,
                              problems or None, soru_tipi)
        try:
            draft = generate(prompt, aktif_model, args.temperature)
        except SystemExit as exc:
            # Ana modelin gunluk kotasi 20; dolunca post hic uretilemiyordu.
            # Yedek modelin hakki 500. Uslup birebir ayni olmayabilir ama
            # style.py filtresi, QA ve kullanicinin onayi devrede - post
            # uretememektense farkli tonda uretmek daha iyi.
            #
            # ⚠️ Eskiden kosul yalnizca "429" ariyordu ve kacak veriyordu:
            # kota dolunca once 429 geliyor, api_call tekrar deniyor ve
            # SON hata 503 olabiliyor. O zaman "429 yok" deyip yedege
            # gecmeden oluyordu (olcum 2026-09-01, /uret 2). Artik GECICI
            # sayilan her API hatasi yedege dusuruyor - amac ayni: post
            # uretememektense baska modelle uretmek.
            if aktif_model == HELPER_MODEL or not any(
                    kod in str(exc) for kod in API_GECICI_HATALAR):
                raise
            print(f"\n{aktif_model} cevap vermedi ({str(exc).splitlines()[0][:60]}), "
                  f"yedek modele geciliyor: {HELPER_MODEL}\n")
            aktif_model = HELPER_MODEL
            draft = generate(prompt, aktif_model, args.temperature)
        except GecersizCevap as exc:
            # Yarim/bozuk cevap: cokme degil, yeniden deneme sebebi.
            print(f"deneme {attempt}: {exc}")
            problems = [f"cevap kullanilamadi ({exc}). daha KISA yaz: "
                        "sayfa sayisini azalt, paragraflari kisalt."]
            continue
        # Mekanik hatalar once duzeltilir: buyuk harf ve Turkce ek hatasi
        # yuzunden yeniden uretim istemek kotayi bosa harciyordu.
        draft = style.autofix_suffixes(style.autofix_lowercase(draft))
        # Tekrar eden madde silmek mekanik bir duzeltme: yeniden uretim
        # istemeye degmez ve kotayi yakar (bkz. buyuk harf dersi).
        draft = autofix_dayanak(draft, source_text)
        # Yapi denetimi once: sayfa duzeni bozuksa uslup zaten yeniden
        # yazilacak, QA'ya kota harcamanin anlami yok.
        problems = (check_structure(draft) + check_dayanak(draft, source_text)
                    + style.review(draft, source_text))

        # Isaretsiz Turkce mekanik degil ama COZULEBILIR: metni yeniden
        # yazdirmak yerine isaretleri geri koyduruyoruz (ucuz model, sonucu
        # kod dogruluyor). Yedek modelin tek engeli buydu.
        if any("Turkce karakter" in p for p in problems):
            draft = diakritik_onar(draft, HELPER_MODEL)
            problems = (check_structure(draft) + check_dayanak(draft, source_text)
                    + style.review(draft, source_text))

        # Deterministik filtre temizse ikinci goz devreye girer. Once o
        # calissin diye sonra: yasak kalip varken QA'ya para harcamanin
        # anlami yok, metin zaten yeniden yazilacak.
        if not problems and args.qa:
            problems = llm_review(draft, source_text, HELPER_MODEL)
            if problems:
                print(f"deneme {attempt}: filtre temiz, qa {len(problems)} sorun buldu")

        if not problems:
            spec = to_render_spec(draft, args.tier, candidate, index,
                                  aktif_model)
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"deneme {attempt}: temiz. {len(spec['pages'])} sayfa -> {out_path}")
            print(f"  oyun: {spec['game']} | kategori: {spec['category']} "
                  f"| sizinti: {spec['_is_leak']}")
            print(f"\nkartlari basmak icin:\n  py -3.12 src/render.py {out_path}")
            return 0

        print(f"deneme {attempt}: {len(problems)} ihlal")
        for problem in problems[:8]:
            print(f"  - {problem}")

        # Once HEDEFLI ONARIM: tum metni bastan yazdirmadan sadece takilan
        # alanlari duzelttir. Basarirsa bu denemede biter, kota yanmaz.
        draft = hedefli_onar(draft, problems, source_text, HELPER_MODEL)
        problems = (check_structure(draft) + check_dayanak(draft, source_text)
                    + style.review(draft, source_text))
        if not problems:
            spec = to_render_spec(draft, args.tier, candidate, index, aktif_model)
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
            print(f"deneme {attempt}: hedefli onarimla temiz. "
                  f"{len(spec['pages'])} sayfa -> {args.out}")
            return 0

        # En az ihlalli taslagi sakla: hicbir deneme temiz cikmazsa bunu
        # yollayacagiz. Hic post cikmamasi, kusurlu post cikmasindan kotu.
        if en_iyi is None or len(problems) < en_iyi[0]:
            en_iyi = (len(problems), draft, list(problems))

    ozet = " | ".join(p.split(": ", 1)[-1][:60] for p in problems[:3])

    if en_iyi is not None:
        # KUSURLU AMA YAYINA ADAY. Kullanici kartlarda gorup karar verir;
        # begenmezse /yeniden yazar. Eskiden bu durumda hicbir sey
        # cikmiyordu ve kullanici sebebini de bilmiyordu.
        _, draft, kalan = en_iyi
        spec = to_render_spec(draft, args.tier, candidate, index, aktif_model)
        spec["_ihlaller"] = kalan[:5]
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n{MAX_ATTEMPTS} denemede temiz cikmadi. en az ihlalli taslak "
              f"({len(kalan)} ihlal) onaya yollaniyor -> {out_path}")
        print(f"kalan ihlaller: {ozet}", file=sys.stderr)
        return 0

    # Son denemenin ihlalleri STDERR'e de yaziliyor: produce.py alt surecin
    # son stderr satirini yukari tasiyor ve Telegram mesajina o giriyor.
    print(f"\n{MAX_ATTEMPTS} denemede temiz cikti alinamadi. "
          f"son ihlaller: {ozet}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

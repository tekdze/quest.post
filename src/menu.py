#!/usr/bin/env python3
"""Günün adaylarını Telegram'a menü olarak sunar, seçimi kullanıcı yapar.

Neden var: bot kendi seçtiği haberi doğrudan üretiyordu ve kullanıcı ancak
kartlar basıldıktan sonra "bunu istemiyorum" diyebiliyordu. Görselsiz bir
haber için LLM ve render bedeli boşa gidiyordu. Menü bu kararı öne alıyor:
metin üretimi ancak kullanıcı seçtikten sonra başlar.

Üç bilgi bir arada geliyor:
  - tier (KOD hesaplar, LLM değil - renk sistemi buna bağlı)
  - görsel durumu (IGDB'de gerçekten kaç kullanılabilir görsel var)
  - öneri (LLM, sadece "görünürlük açısından ilginç mi" sorusu)

LLM'e verilen bütçe SINIRLI: tam olarak bir aday seçmek zorunda. Serbest
bırakılırsa hepsini işaretler ve öneri değersizleşir - tier.py'nin
"LLM'e serbestlik verilirse her haberi S yapar" dersi burada da geçerli.
LLM tier'a DOKUNMAZ; öneri ayrı bir sinyaldir.

Kullanım:
    py -3.12 src/menu.py                 # menu uret ve Telegram'a yolla
    py -3.12 src/menu.py --dry-run       # yollamaz, ekrana basar
    py -3.12 src/menu.py --limit 6
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import images as img  # noqa: E402
import steam  # noqa: E402
import telegram as tg  # noqa: E402
import tier as tier_module  # noqa: E402
import write as writer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = ROOT / "state" / "candidates.json"
MENU_FILE = ROOT / "state" / "menu.json"

# Menude kac aday gosterilecek. Daha fazlasi Telegram mesajini okunmaz
# yapiyor ve LLM'in secim isini zorlastiriyor.
DEFAULT_LIMIT = 6

# Menu AYRI bir model kullaniyor. Sebep: Gemini kotasi model basina
# (GenerateRequestsPerDayPerProjectPerModel, gunde 20). Menu ile post
# uretimi ayni modeli paylasirsa gunun uc menusu uretim butcesinden
# yiyor. Ayri model = ayri havuz, ve bu ToS'a uygun: ayni hesap, ayni
# proje, sadece farkli model.
#
# Hafif model hem yeterli hem COK daha genis: 3.6-flash gunde 20 istek,
# flash-lite 500 (AI Studio rate limit panelinden okundu). Menunun isi
# oyun adi cikarmak, tek cumle ozet ve aday secmek. Kart METNI yazan
# write.py surum sabit kalmali (uslup), menu icin ayni hassasiyet
# gerekmiyor.
MENU_MODEL = "gemini-3.5-flash-lite"

ONERI_SCHEMA = """{
  "adaylar": [
    {"sira": 1,
     "oyun": "haberde gecen oyunun TAM INGILIZCE adi, yoksa null",
     "seri": "ayni serinin gorsel bakimindan zengin baska oyunu (tam Ingilizce ad), yoksa null",
     "temsili": "haberin konusu bir oyun DEGILSE (konsol, sirket, etkinlik), haberi gorsel olarak temsil edebilecek bir oyun. Oyun varsa null",
     "ozet": "haberin NE oldugu, tek cumle, en fazla 12 kelime, kucuk harf"}
  ],
  "oneri": 3,
  "gerekce": "neden bu secildi, tek cumle, en fazla 12 kelime, kucuk harf"
}"""


def build_prompt(rows: list[dict]) -> str:
    satirlar = []
    for row in rows:
        satirlar.append(f"{row['sira']}. {row['title']}")
        ozet = (row.get("summary") or "").strip().replace("\n", " ")
        if ozet:
            satirlar.append(f"   {ozet[:240]}")

    return "\n".join([
        "Bir Türkçe oyun haberi hesabı için günün aday haberleri aşağıda.",
        "Üç iş yapacaksın.",
        "",
        "BİRİNCİ İŞ: her aday için haberde adı geçen oyunun tam İngilizce",
        "adını çıkar (sürüm numarası dahil). Haberde bir oyun adı geçmiyorsa",
        "null yaz. Bu ad IGDB'de aranacak, o yüzden çevirme ve kısaltma.",
        "Ayrıca 'seri' alanına aynı serinin görsel bakımından ZENGİN bir",
        "oyununu yaz (konu oyununun görseli az çıkarsa oradan tamamlanacak).",
        "Çıkmamış oyunların görseli genelde azdır, asıl orada gerekiyor.",
        "Sadece gerçekten aynı seri olanı yaz; benzer türde başka bir oyun",
        "okuru yanıltır. Uygun yoksa null.",
        "",
        "İKİNCİ İŞ: her aday için 'ozet' yaz - haberin NE olduğunu anlatan",
        "tek cümle, Türkçe, küçük harf, en fazla 12 kelime. Başlıkta zaten",
        "yazan şeyi tekrarlama; başlığın söylemediği asıl olayı söyle.",
        "Örnek: başlık 'EA Acknowledges Iron Man Gameplay Leak' ise özet",
        "'ea sızan oyun görüntülerini doğruladı ve espriyle karşılık verdi'",
        "olur. Bu özet listeye bakıp seçim yapmak için, merak uyandırmak",
        "için değil - abartma, süsleme, soru sorma.",
        "",
        "ÜÇÜNCÜ İŞ: TAM OLARAK BİR aday öner. Ölçüt tek: bu haber bir",
        "Instagram gönderisi olarak GÖRÜNÜRLÜK açısından ilginç mi -",
        "insanlar durup okur mu, paylaşır mı, yorum yazar mı.",
        "",
        "Öneri ölçütü DEĞİLDİR: haberin büyüklüğü, kaç kaynağın yazdığı,",
        "ne kadar önemli olduğu. Bunlar zaten ayrıca hesaplanıyor.",
        "Sıradan görünen ama merak uyandıran bir haber, büyük ama kuru bir",
        "duyurudan daha iyi bir öneridir.",
        "",
        "Birden fazla öneremezsin. Hiçbirini öneremem diyemezsin. En iyisini",
        "seçmek zorundasın - kıyaslama yapman için böyle.",
        "",
        "ADAYLAR:",
        *satirlar,
        "",
        "SADECE şu şemada JSON döndür, başka hiçbir şey yazma:",
        ONERI_SCHEMA,
    ])


def havuz_boyu(game: dict) -> int:
    pool = img.image_pool(game)
    return len(pool["artwork"]) + len(pool["screenshot"]) + len(pool["cover"])


def gorsel_durumu(cid: str, token: str, oyun: str | None,
                  seri: str | None = None, sayfa_tahmini: int = 4,
                  temsili: str | None = None, baslik: str | None = None) -> dict:
    """Adayın IGDB'de kullanılabilir görseli var mı, kaç tane.

    Menüde "görsel VAR/YOK" yazabilmek için. Metin üretilmeden önce
    bakılıyor: kullanıcı görselsiz bir haberi hiç seçmek zorunda kalmasın.

    Konu oyununun görseli sayfalara yetmiyorsa aynı seriden tamamlanacak
    (images.py yapıyor). Menü bunu şeffaf gösteriyor: "2 + 21 seriden".
    Seri araması sadece gerektiğinde yapılıyor, boşuna IGDB çağrısı yok.
    """
    bos = {"durum": "yok", "sayi": 0, "oyun": None, "seri_sayi": 0, "seri": None,
           "temsili": False}
    game = None
    temsili_mi = False

    if oyun:
        game, _, _ = img.find_game(cid, token, oyun)
    # Haberin konusu oyun degilse temsili oyun denenir - images.py uretimde
    # zaten bunu yapiyor, menu de ayni sonucu gostermeli. Aksi halde menu
    # "gorsel YOK" derken uretimde gorsel cikiyordu.
    if game is None and temsili:
        game, _, _ = img.find_game(cid, token, temsili)
        temsili_mi = game is not None
    # LLM oyun adini kaciririrsa basliktaki tirnakli ad denenir: "'Book Nook'
    # has you creating tiny worlds" haberinde model null dondu ama oyunun
    # IGDB'de 14, Steam'de 11 goreseli vardi ve menu "gorsel yok" dedi.
    if game is None:
        for ad in img.tirnakli_adlar(baslik or ""):
            game, _, _ = img.find_game(cid, token, ad)
            if game is not None:
                break

    if game is None:
        # IGDB bulamadi ama Steam bulabilir (kucuk indie oyunlar).
        # Menu uretimin GERCEKTEN yapacagi seyi gostermeli.
        for ad in [a for a in (oyun, temsili, *img.tirnakli_adlar(baslik or "")) if a]:
            st = steam.havuz(str(ad), en_fazla=sayfa_tahmini + 2)
            if st:
                return {"durum": "var" if len(st) >= sayfa_tahmini else "az",
                        "sayi": len(st), "oyun": st[0]["oyun"], "seri_sayi": 0,
                        "seri": None, "temsili": False, "kaynak": "steam"}
        return bos

    sayi = havuz_boyu(game)
    sonuc = {"durum": "var" if sayi >= sayfa_tahmini else "az", "sayi": sayi,
             "oyun": game["name"], "seri_sayi": 0, "seri": None,
             "temsili": temsili_mi}
    if sayi >= sayfa_tahmini or not seri:
        return sonuc

    kardes, _, _ = img.find_game(cid, token, seri)
    if kardes is None:
        return sonuc
    seri_sayi = havuz_boyu(kardes)
    if not seri_sayi:
        return sonuc
    sonuc["seri_sayi"] = seri_sayi
    sonuc["seri"] = kardes["name"]
    if sayi + seri_sayi >= sayfa_tahmini:
        sonuc["durum"] = "var"
    return sonuc


def menu_metni(rows: list[dict], oneri: int | None, gerekce: str) -> str:
    satirlar = ["bugünün adayları:", ""]
    for row in rows:
        isaret = "  ⭐" if row["sira"] == oneri else ""
        satirlar.append(f"{row['sira']}. [{row['tier']}] {row['baslik']}{isaret}")

        # Ozet basligin hemen altinda: listede gezerken once "ne haberi bu"
        # sorusu cevaplanmali, teknik ayrintilar sonra.
        if row.get("ozet"):
            satirlar.append(f"   {row['ozet']}")

        gorsel = row["gorsel"]
        if gorsel["durum"] == "yok":
            g = "görsel YOK (tipografik olur)"
        elif gorsel.get("seri_sayi"):
            # Seriden tamamlanacak: kullanici bunu bilerek secsin.
            g = f"görsel VAR ({gorsel['sayi']} + {gorsel['seri_sayi']} seriden)"
        elif gorsel["durum"] == "az":
            g = f"görsel AZ ({gorsel['sayi']}, sayfalarda tekrar eder)"
        else:
            g = f"görsel VAR ({gorsel['sayi']})"
        satir = f"   {row['kaynak_sayisi']} kaynak · {g}"
        if gorsel.get("oyun") and gorsel["durum"] != "yok":
            # Temsili oldugu yaziliyor: haberin konusu o oyun degil, sadece
            # onu gorsel olarak temsil ediyor. Kullanici bilerek secsin.
            satir += f" · {gorsel['oyun']}"
            if gorsel.get("temsili"):
                satir += " (temsili)"
            if gorsel.get("seri"):
                satir += f" + {gorsel['seri']}"
        satirlar.append(satir)

        if row["sira"] == oneri and gerekce:
            satirlar.append(f"   ⭐ {gerekce}")
        satirlar.append("")

    satirlar.append("üretmek için: /uret <numara>")
    return "\n".join(satirlar)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post aday menusu")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--dry-run", action="store_true", help="Telegram'a yollamaz")
    ap.add_argument("--model", default=MENU_MODEL)
    args = ap.parse_args()

    data = tg.read_json(CANDIDATES_FILE, None)
    if not data or not data.get("candidates"):
        sys.exit("aday bulunamadi (candidates.json bos). once: py -3.12 src/fetch.py")

    ham = data["candidates"][: args.limit]
    rows = []
    for sira, cand in enumerate(ham, 1):
        computed, _ = tier_module.compute(cand)
        rows.append({
            "sira": sira,
            "aday_index": sira,          # candidates.json'daki sira ile ayni
            "tier": computed,
            "title": cand["title"],
            "summary": (cand.get("members") or [{}])[0].get("summary", ""),
            "kaynak_sayisi": cand.get("source_count", 1),
            "url": cand.get("url"),
            # Adayin TAM kaydi menuyle birlikte tasiniyor. Sebep: uretim
            # AYRI bir Actions calismasinda yapiliyor ve candidates.json
            # git disi - o calisma repoyu temiz cekince dosyayi bulamiyor.
            # Yeniden taratmak cozum degil: sira degisir ve menudeki "1"
            # baska habere denk gelir.
            "aday": cand,
        })

    # Tek LLM cagrisi: hem oyun adlarini cikariyor hem oneriyi seciyor.
    # Ayri cagrilar bolmek gereksiz - ikisi de ayni metni okuyor.
    print(f"{len(rows)} aday LLM'e soruluyor...")
    cevap = writer.generate(build_prompt(rows), args.model, temperature=0.4)

    oyunlar, ozetler, seriler, temsililer = {}, {}, {}, {}
    for row in writer.liste_al(cevap, "adaylar"):
        try:
            sira = int(row.get("sira"))
        except (TypeError, ValueError):
            continue
        oyunlar[sira] = row.get("oyun")
        ozetler[sira] = (row.get("ozet") or "").strip()
        seriler[sira] = row.get("seri")
        temsililer[sira] = row.get("temsili")

    oneri = cevap.get("oneri") if isinstance(cevap, dict) else None
    try:
        oneri = int(oneri)
    except (TypeError, ValueError):
        oneri = None
    if oneri is not None and not any(r["sira"] == oneri for r in rows):
        print(f"uyari: LLM listede olmayan {oneri} numarasini onerdi, yok sayildi")
        oneri = None
    gerekce = (cevap.get("gerekce") or "").strip() if isinstance(cevap, dict) else ""

    # Gorsel kontrolu: LLM'in verdigi oyun adlari IGDB'de aranir.
    # Metin uretilmeden once bakiliyor, bedeli sadece birkac arama.
    cid, secret = img.credentials()
    token = img.get_token(cid, secret)
    for row in rows:
        oyun = oyunlar.get(row["sira"])
        row["oyun_adi"] = oyun
        row["ozet"] = ozetler.get(row["sira"], "")
        row["gorsel"] = gorsel_durumu(cid, token, oyun, seriler.get(row["sira"]),
                                      temsili=temsililer.get(row["sira"]),
                                      baslik=row.get("title"))
        row["baslik"] = oyun or (row["title"][:52].rstrip() + "..."
                                 if len(row["title"]) > 52 else row["title"])
        isaret = " <- ONERI" if row["sira"] == oneri else ""
        sayim = str(row["gorsel"]["sayi"])
        if row["gorsel"].get("seri_sayi"):
            sayim += f"+{row['gorsel']['seri_sayi']} seri"
        print(f"  {row['sira']}. [{row['tier']}] {row['baslik']} "
              f"| gorsel {row['gorsel']['durum']} ({sayim}){isaret}")

    metin = menu_metni(rows, oneri, gerekce)

    # Secimin hangi adaya denk geldigi burada saklaniyor: kullanici
    # "/uret 2" yazdiginda respond.py bu dosyadan aday sirasini okuyacak.
    tg.write_json(MENU_FILE, {
        "olusturuldu": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "oneri": oneri,
        "gerekce": gerekce,
        "adaylar": [{k: v for k, v in row.items() if k != "summary"} for row in rows],
    })

    if args.dry_run:
        print("\n--- menu (yollanmadi) ---")
        print(metin)
        return 0

    tg.send_text(metin)
    print("\nmenu Telegram'a yollandi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

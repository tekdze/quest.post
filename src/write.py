#!/usr/bin/env python3
"""Aday haberi Turkce post metnine cevirir. Gemini + uslup filtresi.

Faz 2 - GEMINI_API_KEY gerekir (.env dosyasindan veya ortam degiskeninden).

Is bolumu net: LLM SADECE metin yazar. Tasarima, tier'a, gorsel secimine,
sayfa sayisina karisamaz. Cikti dogrudan render.py'in bekledigi semaya oturur.

Kullanim:
    py -3.12 src/write.py --list-models          # once bunu calistir
    py -3.12 src/write.py --index 1              # candidates.json'daki 1. aday
    py -3.12 src/write.py --index 1 --tier A --out state/draft.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = ROOT / "state" / "candidates.json"
DEFAULT_OUT = ROOT / "state" / "draft.json"

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Surum SABITLENDI (3.7-flash surekli 503 donuyordu, 3.6 stabil). "gemini-flash-latest" gibi takma ad kullanilmiyor:
# model sessizce degisirse uslup da degisir, 300. post 1. postla ayni olmaz.
DEFAULT_MODEL = "gemini-3.6-flash"
MAX_ATTEMPTS = 3
# Gecici HTTP hatalari icin yeniden deneme (503 = model yogun).
HTTP_RETRIES = 4
RETRY_BACKOFF = 5  # saniye, her denemede katlaniyor

# Sabit kategori listesi. LLM buradan secer, serbest yazamaz - kicker metni
# her postta ayni sozluk icinden gelsin diye.
CATEGORIES = [
    "çıkış", "stüdyo", "güncelleme", "sızıntı", "etkinlik",
    "finansman", "kapanma", "demo", "tartışma",
]

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


def generate(prompt: str, model: str, temperature: float) -> dict:
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
        },
    }
    data = api_call(f"models/{model}:generateContent", payload)
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        reason = data.get("promptFeedback", {}).get("blockReason", "bilinmiyor")
        sys.exit(f"Gemini bos cevap dondu (sebep: {reason})\n{json.dumps(data)[:400]}")
    return json.loads(text)


# ---------------------------------------------------------------- istem

SCHEMA = """{
  "game": "haberin konusu olan oyunun veya şirketin adı",
  "search_name": "haberin ASIL konusu olan oyunun TAM ve INGILIZCE adi, surum numarasi dahil (ornek: The Witcher 3: Wild Hunt). Haber bir oyunu konu almiyorsa null",
  "image_candidates": ["haber metninde adi gecen ve GORSELI bu haberi temsil edebilecek oyunlarin tam Ingilizce adlari, onem sirasiyla, en fazla 3. search_name doluysa onu buraya tekrar yazma. Uygun oyun yoksa bos liste"],
  "series_fallback": ["ayni serinin/evrenin gorsel bakimindan zengin baska oyunlarinin tam Ingilizce adlari, en fazla 2. Sadece konu oyununun gorseli yetmezse kullanilacak. Uygun yoksa bos liste"],
  "category": "listeden biri",
  "studio": "görsel kredisi için stüdyo adı, bilinmiyorsa null",
  "is_leak": true veya false,
  "caption": "Instagram gönderi açıklaması. 2-4 cümle, kartlarda yazanı TEKRARLAMAZ, haberin bağlamını verir. En fazla 2 hashtag, sonda.",
  "pages": [
    {"type": "cover", "title": "kapak başlığı, en fazla 8 kelime"},
    {"type": "text", "title": "3-5 kelime", "paragraph": "2-3 cümle",
     "bullets": ["madde", "madde"]},
    {"type": "numbers", "title": "3-5 kelime",
     "metrics": [{"value": "18 m$", "label": "ne olduğu, en fazla 8 kelime"}]},
    {"type": "outro", "question": "tek soru, 6-12 kelime",
     "ctas": ["tek yumuşak çağrı"]}
  ]
}"""


def build_prompt(candidate: dict, source_text: str, mode: str,
                 problems: list[str] | None = None) -> str:
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
        "11. Son sayfada TEK çağrı yazılır ve yumuşak olur: okuru düşünmeye",
        "    veya yorum yazmaya davet eden bir cümle. 'beğen', 'paylaş' yazma;",
        "    takip daveti zaten kartın kendisinde sabit metin olarak var.",
        "12. Yazım hatası yapma. Metni yazdıktan sonra harf harf kontrol et.",
        "13. search_name ÇEVİRİLMEZ ve KISALTILMAZ. Kaynakta hangi oyundan",
        "    bahsediliyorsa onun tam İngilizce adını yaz, sürüm numarası dahil.",
        "    Haber \"the witcher 3\" hakkındaysa \"The Witcher\" yazmak HATADIR;",
        "    yanlış oyunun görselleri basılır. Haberin konusu bir oyun değilse",
        "    (etkinlik, şirket, konsol, sektör haberi) null yaz.",
        "14. image_candidates: haberin konusu bir oyun OLMASA BİLE, metinde adı",
        "    geçen ve görseli bu haberi temsil edebilecek oyunları buraya yaz.",
        "    Örnek: haber yeni bir konsol ailesi hakkında ama içinde \"Elder",
        "    Scrolls 6 o konsola özel mi olacak\" tartışılıyorsa",
        "    [\"The Elder Scrolls VI\"] yazılır - o oyunun görseli haberi",
        "    temsil eder. Sadece adı GEÇEN oyunları yaz, konuyla ilgisi",
        "    kurulamayan bir oyunu doldurma; okur görseli haberle",
        "    ilişkilendiremezse kart yanıltıcı olur.",
        "15. caption Instagram'da kartların altında görünecek metin.",
        "    Kartlarda yazanı TEKRARLAMA - okur kartları zaten gördü.",
        "    Haberin bağlamını ver: bu neden önemli, öncesinde ne olmuştu.",
        "    2-4 cümle. Sonunda en fazla 2 hashtag, küçük harf. Üslup",
        "    kuralları burada da geçerli: emoji yok, büyük harf yok,",
        "    \"işte\" gibi kalıplar yok.",
        "16. series_fallback: konu oyununun görseli az olabilir (henüz",
        "    çıkmamış oyunlarda sık). Aynı serinin/evrenin görsel bakımından",
        "    zengin oyunlarını buraya yaz - haber \"The Elder Scrolls VI\"",
        "    hakkındaysa [\"The Elder Scrolls V: Skyrim\"] gibi. Sadece",
        "    gerçekten AYNI seri olanları yaz; benzer türde başka bir oyunu",
        "    yazmak okuru yanıltır. Uygun yoksa boş liste.",
        "",
        f"KATEGORİ listesi (birini seç): {', '.join(CATEGORIES)}",
        "",
        "SAYFA YAPISI: 1 kapak + 1-2 metin sayfası + (rakam varsa) 1 rakam sayfası",
        "+ 1 son sayfa. Toplam 3-5 sayfa.",
        "",
        "is_leak: haber sızıntı, datamine veya izinsiz sızan materyale dayanıyorsa true.",
        "Bu durumda kartta görsel kullanılmayacak, kod bunu kendisi halleder.",
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


def to_render_spec(draft: dict, tier: str, candidate: dict, index: int = 0) -> dict:
    """LLM ciktisini render.py'in bekledigi tarife cevir."""
    is_leak = bool(draft.get("is_leak"))
    category = draft.get("category", "")
    if category not in CATEGORIES:
        category = "sızıntı" if is_leak else "güncelleme"

    pages = []
    for page in draft["pages"]:
        page = dict(page)
        # Gorsel secimi Faz 4'un isi (images.py). Simdilik yer tutucu, ama
        # sizinti haberinde ASLA gorsel konmaz - telif kurali.
        page["image"] = None if is_leak else "assets/placeholder.png"
        pages.append(page)

    return {
        "_kaynak": candidate["url"],
        # /yeniden komutu ayni adayi tekrar yazdirabilsin diye sira saklaniyor.
        "_aday_index": index,
        "_kaynak_sayisi": candidate["source_count"],
        "_is_leak": is_leak,
        "tier": tier,
        "category": category,
        # Instagram gonderi metni. Faz 6'ya kadar da ise yariyor: /bana ile
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
        # Kucuk harfe cevriliyor: studio artik uslup denetiminden muaf
        # (buyuk harfli Ingilizce ad olabilir) ama karta basilan her sey
        # kucuk harf. images.py bunu IGDB verisiyle zaten eziyor.
        "credit": None if is_leak else (draft.get("studio") or "").lower() or None,
        "pages": pages,
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post metin uretici (Faz 2)")
    ap.add_argument("--list-models", action="store_true", help="kullanilabilir modelleri listele")
    ap.add_argument("--index", type=int, default=1, help="candidates.json'daki sira (1'den baslar)")
    ap.add_argument("--tier", default="B", choices=list("CBAS"),
                    help="gecici: tier.py yazilana kadar elle veriliyor")
    ap.add_argument("--model", default=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))
    ap.add_argument("--temperature", type=float, default=0.95)
    ap.add_argument("--mode", choices=list(WRITING_MODES), default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    if args.list_models:
        list_models()
        return 0

    if not CANDIDATES_FILE.exists():
        sys.exit("state/candidates.json yok. Once: py -3.12 src/fetch.py")

    data = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
    candidates = data["candidates"]
    if not 1 <= args.index <= len(candidates):
        sys.exit(f"--index 1..{len(candidates)} arasinda olmali")
    candidate = candidates[args.index - 1]

    source_text = source_text_of(candidate)
    mode = args.mode or random.choice(list(WRITING_MODES))

    print(f"aday: {candidate['title'][:70]}")
    print(f"kaynak sayisi: {candidate['source_count']} ({', '.join(candidate['sources'])})")
    print(f"yazim modu: {mode}\n")

    problems: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = build_prompt(candidate, source_text, mode, problems or None)
        draft = generate(prompt, args.model, args.temperature)
        draft = style.autofix_suffixes(draft)
        problems = style.review(draft, source_text)

        if not problems:
            spec = to_render_spec(draft, args.tier, candidate, args.index)
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

    print(f"\n{MAX_ATTEMPTS} denemede temiz cikti alinamadi.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

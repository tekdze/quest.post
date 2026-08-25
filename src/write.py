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
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import style  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = ROOT / "state" / "candidates.json"
DEFAULT_OUT = ROOT / "state" / "draft.json"

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Surum SABITLENDI. "gemini-flash-latest" gibi takma ad kullanilmiyor:
# model sessizce degisirse uslup da degisir, 300. post 1. postla ayni olmaz.
DEFAULT_MODEL = "gemini-3.7-flash"
MAX_ATTEMPTS = 3

# Sabit kategori listesi. LLM buradan secer, serbest yazamaz - kicker metni
# her postta ayni sozluk icinden gelsin diye.
CATEGORIES = [
    "çıkış", "stüdyo", "güncelleme", "sızıntı", "etkinlik",
    "finansman", "kapanma", "demo", "tartışma",
]

# Her uretimde rastgele biri secilir. Sabit acilis kalibi olusmasini engeller.
WRITING_MODES = {
    "gözlem": "olayin somut bir detayina odaklan, genel yorum yapma",
    "karşılaştırma": "benzer bir orneke veya rakibe kiyasla anlat",
    "tarihsel not": "olayin gecmisiyle baglantisini kur",
    "sayısal detay": "kaynaktaki rakamlarin ne anlama geldigini ac",
    "karşı görüş": "olaya supheyle yaklas, zayif tarafini soyle",
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
    """Gemini REST cagrisi. SDK kullanilmiyor - tek bagimliliksiz istek yeter."""
    url = f"{API_BASE}/{path}"
    headers = {"x-goog-api-key": api_key(), "Content-Type": "application/json"}
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:600]
        sys.exit(f"Gemini API hatasi {exc.code}:\n{body}")


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
  "game": "haberin konusu olan oyunun veya sirketin adi",
  "category": "listeden biri",
  "studio": "gorsel kredisi icin studyo adi, bilinmiyorsa null",
  "is_leak": true veya false,
  "pages": [
    {"type": "cover", "title": "kapak basligi, en fazla 8 kelime"},
    {"type": "text", "title": "3-5 kelime", "paragraph": "2-3 cumle",
     "bullets": ["madde", "madde"]},
    {"type": "numbers", "title": "3-5 kelime",
     "metrics": [{"value": "18 m$", "label": "ne oldugu, en fazla 8 kelime"}]},
    {"type": "outro", "question": "tek soru, 6-12 kelime",
     "ctas": ["yumusak cagri", "yumusak cagri"]}
  ]
}"""


def build_prompt(candidate: dict, source_text: str, mode: str,
                 problems: list[str] | None = None) -> str:
    sources = ", ".join(candidate["sources"])
    mode_hint = WRITING_MODES[mode]

    parts = [
        "Bir Turkce indie oyun haberleri instagram hesabi icin post metni yaziyorsun.",
        "",
        "KAYNAK MATERYAL (Ingilizce, birden fazla haber sitesinden):",
        source_text,
        "",
        f"Bu haberi {len(candidate['sources'])} kaynak yazmis: {sources}",
        "",
        "GOREV: bu haberi Turkceye cevirip instagram carousel metnine donustur.",
        f"Yazim modu: {mode} - {mode_hint}",
        "",
        "KURALLAR (hepsi zorunlu):",
        "1. Tamamen kucuk harf. Ozel isimler de kucuk. Tek istisna yok.",
        "2. Ceviri degil, yeniden anlatim. Kaynak cumleyi birebir cevirmeyeceksin.",
        "3. Kaynak metinde GECMEYEN hicbir sayi yazamazsin. Sayi uydurmak yasak.",
        "   Kaynakta rakam yoksa 'numbers' sayfasini HIC URETME.",
        "4. Yasak kelimeler: iste, peki, devrim niteliginde, cigir acan, adeta,",
        "   tam anlamiyla, sonuc olarak, yapay zeka destekli.",
        "5. Em-dash (uzun cizgi) ve egik tirnak kullanma. Duz tirnak ve kisa cizgi kullan.",
        "6. Emoji yok. Hashtag yok.",
        "7. Baslik ve paragraf soru cumlesiyle BASLAMAYACAK. Sadece son sayfada soru olur.",
        "8. 'a, b ve c' seklinde uc ogeli liste kalibi kurma.",
        "9. Yabanci ozel isimlere Turkce ek eklerken okunusa gore sec:",
        "   godot'u (godot'yu DEGIL), steam'de, unity'yi, valve'in, xbox'ta, epic'te.",
        "10. Son sayfada 'takip et', 'begen', 'paylas' gibi cagrilar yasak.",
        "    Iki cagri da yumusak olacak: merak/dusunce davet eden cumleler.",
        "",
        f"KATEGORI listesi (birini sec): {', '.join(CATEGORIES)}",
        "",
        "SAYFA YAPISI: 1 kapak + 1-2 metin sayfasi + (rakam varsa) 1 rakam sayfasi",
        "+ 1 son sayfa. Toplam 3-5 sayfa.",
        "",
        "is_leak: haber sizinti, datamine veya izinsiz sizan materyale dayaniyorsa true.",
        "Bu durumda kartta gorsel kullanilmayacak, kod bunu kendisi halleder.",
        "",
        "SADECE su semada JSON dondur, baska hicbir sey yazma:",
        SCHEMA,
    ]

    if problems:
        parts += [
            "",
            "ONCEKI DENEMEN SU HATALARLA REDDEDILDI, bunlari duzelt:",
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


def to_render_spec(draft: dict, tier: str, candidate: dict) -> dict:
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
        "_kaynak_sayisi": candidate["source_count"],
        "_is_leak": is_leak,
        "tier": tier,
        "category": category,
        "game": draft.get("game", ""),
        "credit": None if is_leak else draft.get("studio"),
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
            spec = to_render_spec(draft, args.tier, candidate)
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

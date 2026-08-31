#!/usr/bin/env python3
"""GitHub Models sondasi. Gemini kotasindan BAGIMSIZ ikinci bir butce mi?

NEDEN
-----
Gemini kotasi model basina ve dar: gemini-3.6-flash gunde 20 istek.
Butun kalite tartismasi (cikarim turu, elestiri turu, yeniden deneme)
bu 20 sayisina carpiyor. Ikinci bir Gemini hesabi ToS ihlali ve zaten
ise yaramiyor - kota hesap katmaninda da uygulaniyor.

GitHub Models FARKLI bir saglayici, yani ayri bir butce. Ve bu projede
ozel bir avantaji var: sistem ZATEN GitHub Actions uzerinde calisiyor,
yani orada GITHUB_TOKEN hazir duruyor - yeni hesap, yeni anahtar, yeni
Secret gerekmiyor.

⚠️ BU DOSYA BIR SONDADIR, ENTEGRASYON DEGIL.
Amaci tek bir soruyu canli olarak cevaplamak: bu hesapta GitHub Models
calisiyor mu, hangi modeller var, Turkcesi nasil. DEVIR kurali: "bir
modelin panelde gorunmesi cagrilabildigi anlamina gelmiyor" - Gemini'de
oyle oldu (gemini-2.5-* listede vardi, 404 donuyordu). Cevap alinmadan
hicbir sey boru hattina baglanmiyor.

Actions icinde `permissions: models: read` gerekiyor.

Kullanim:
    py -3.12 src/ghmodels.py --probe        # calisiyor mu
    py -3.12 src/ghmodels.py --models       # hangi modeller var
    py -3.12 src/ghmodels.py --turkce       # Turkce kalitesini olc
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import style  # noqa: E402

# ⚠️ Iki ayri taban adres dolasimda ve hangisinin gecerli oldugu hesaba
# gore degisebiliyor. Sonda ikisini de deniyor: amac zaten "hangisi
# calisiyor" sorusunu OLCMEK, tahmin etmek degil.
TABANLAR = [
    "https://models.github.ai/inference",
    "https://models.inference.ai.azure.com",
]
KATALOG = "https://models.github.ai/catalog/models"

# Denenecek modeller, ucuzdan pahaliya. Isimler degismis olabilir -
# --models ciktisi gercegi soyler.
ADAY_MODELLER = [
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "microsoft/Phi-4",
]


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def token() -> str | None:
    """Actions'ta GITHUB_TOKEN hazir; yerelde GH_MODELS_TOKEN gerekiyor."""
    load_env()
    for isim in ("GH_MODELS_TOKEN", "GITHUB_TOKEN"):
        deger = os.environ.get(isim, "").strip()
        if deger:
            return deger
    return None


def _istek(url: str, jeton: str, payload: dict | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {jeton}",
                 "Content-Type": "application/json",
                 "Accept": "application/vnd.github+json"},
        method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:500]
    except urllib.error.URLError as exc:
        return 0, f"ulasilamadi: {exc.reason}"


def sor(model: str, prompt: str, jeton: str) -> tuple[str | None, str]:
    """Tek soru sor. (cevap, aciklama) doner; cevap None ise calismadi."""
    payload = {"model": model,
               "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.0}
    for taban in TABANLAR:
        kod, govde = _istek(f"{taban}/chat/completions", jeton, payload)
        if kod == 200:
            try:
                icerik = json.loads(govde)["choices"][0]["message"]["content"]
                return icerik, taban
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                return None, f"{taban}: cevap cozulemedi ({exc})"
        son = f"{taban}: {kod} {govde[:160]}"
    return None, son


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--models", action="store_true")
    ap.add_argument("--turkce", action="store_true")
    args = ap.parse_args()

    jeton = token()
    if not jeton:
        print("GH_MODELS_TOKEN / GITHUB_TOKEN yok.")
        print("Yerelde denemek icin .env'e ekle:")
        print("  GH_MODELS_TOKEN=github_pat_...   (models:read yetkisi yeter)")
        print("Actions icinde GITHUB_TOKEN zaten var, ek Secret gerekmiyor.")
        return 1

    if args.models:
        kod, govde = _istek(KATALOG, jeton)
        if kod != 200:
            print(f"KIRMIZI - katalog {kod}: {govde[:300]}")
            return 1
        try:
            modeller = json.loads(govde)
        except json.JSONDecodeError:
            print(govde[:1500])
            return 0
        for m in (modeller if isinstance(modeller, list) else modeller.get("models", [])):
            print(f"  {m.get('id') or m.get('name')}  "
                  f"({m.get('publisher', '?')})")
        return 0

    if args.turkce:
        # Gercek olcut: Gemini'nin yedek modelinde belgelenmis kusur
        # ISARETSIZ TURKCE. Yeni bir model bu isi devralacaksa once
        # burada olculmeli - hizli ve ucuz olmasi tek basina yetmez.
        soru = ("Su cumleyi duzgun Turkce olarak, tamamen kucuk harflerle "
                "ve Turkce karakterleri (ı ş ğ ü ö ç) DOGRU kullanarak "
                "yeniden yaz. Sadece cumleyi dondur:\n"
                "The studio said the update will arrive next year with "
                "bigger maps and a new difficulty setting.")
        for model in ADAY_MODELLER:
            cevap, nereden = sor(model, soru, jeton)
            if cevap is None:
                print(f"  {model:<24} CALISMADI  {nereden[:90]}")
                continue
            metin = cevap.strip()
            kusur = []
            if style.isaretsiz(metin):
                kusur.append("ISARETSIZ TURKCE")
            if any(c.isalpha() and c.upper() == c and c.lower() != c for c in metin):
                kusur.append("buyuk harf")
            durum = "TEMIZ" if not kusur else " + ".join(kusur)
            print(f"  {model:<24} {durum}")
            print(f"      {metin[:110]}")
        return 0

    # --probe (varsayilan)
    print(f"jeton bulundu ({len(jeton)} karakter)")
    calisan = 0
    for model in ADAY_MODELLER:
        cevap, nereden = sor(model, "Reply with exactly: OK", jeton)
        if cevap is None:
            print(f"  {model:<24} KIRMIZI  {nereden[:110]}")
        else:
            calisan += 1
            print(f"  {model:<24} YESIL    ({nereden.rsplit('/', 2)[0][8:]}) "
                  f"-> {cevap.strip()[:20]}")
    print(f"\n{calisan}/{len(ADAY_MODELLER)} model calisiyor")
    return 0 if calisan else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Reddit ilgi sinyali. "Kac kaynak yazdi" degil, "kac oyuncu ilgilendi".

NEDEN VAR
---------
tier.py kademeyi KAYNAK SAYISINDAN hesapliyor ve bu olcut yaygınlıgı
olcuyor, ilgincligi degil. En cok tekrarlanan haber en sirade haberdir:
her yayin ayni duyuruyu yazar. Paylasilabilir haberi (kopek poseti
mekanigi gibi) genelde bir iki kaynak yazar, o da C kademesine dusup hic
uretilmez.

Konu isisi icin iki istatistiksel yontem denenmis ve ikisi de basarisiz
olmustu (union-find zincirleme birlesti, token sicakligi "shows, dev,
version" cikardi). Sebep: istatistik "gta" ile "shows"u ayiramiyor,
ikisi de nadir. Soru SEMANTIK.

Reddit oy sayisi o semantik soruyu ZATEN cevaplamis bir olcu: insanlar
tarafindan hesaplanmis ilgincilik. Bir haberin r/Games'te 4000 oy almasi,
o haberi kac yayinin yazdigindan bagimsiz bir bilgi - ve tam olarak
eksik olan bilgi.

TELIF VE KAPSAM
---------------
Reddit burada KAYNAK degil SENSOR: gonderi metni, yorum ya da gorsel
alinmiyor. Yalnizca "su baslik su kadar ilgi gordu" sayisi okunuyor.
Haberin kendisi yine RSS'ten geliyor, dogrulama yine kaynak yayinda.

ANAHTARLAR
----------
REDDIT_CLIENT_ID ve REDDIT_CLIENT_SECRET (.env / GitHub Secrets).
Yoksa modul SESSIZCE devre disi kalir ve sistem eskisi gibi calisir -
sinyal bir iyilestirme, bagimlilik degil.

Kullanim:
    py -3.12 src/reddit.py --probe          # anahtarlari canli yokla
    py -3.12 src/reddit.py --dump           # sicak gonderileri listele
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"

# Reddit User-Agent'i CIDDIYE aliyor: jenerik ya da bos gonderirse 429
# donuyor, anahtar dogru olsa bile. Bicim Reddit'in kendi belgesindeki
# oneri: platform:uygulama:surum (by /u/kullanici)
USER_AGENT = "python:quest.post:1.0 (by /u/questpost)"

# Sinyal degeri yuksek olanlar. Genel r/gaming BILEREK disarida: mem ve
# ekran goruntusu agirlikli, haber sinyali degil gurultu uretir.
SUBREDDITS = ["Games", "pcgaming", "GamingLeaksAndRumours"]

# Uygulama jetonu ~24 saat gecerli. Her calismada yenisini almak yerine
# diske yaziliyor: Actions'ta gunde ~300 calisma var.
TOKEN_FILE = ROOT / "state" / "reddit_token.json"

# Gonderi onbellegi. Su an fetch.py gunde 3 kez calisiyor, yani gunde 9
# istek - ucretsiz katmanin (dakikada 100) binde biri. Ama bu sayi
# fetch.py'nin cagrilma sikligina bagli ve o degisebilir: watch.yml gibi
# bir is eklenirse istek sayisi sessizce carpilir.
#
# Onbellek hacmi CAGIRAN KODDAN BAGIMSIZ sinirliyor - kim ne kadar sik
# cagirirsa cagirsin, reddit'e 30 dakikada birden fazla gidilmiyor.
# Sicak gonderi listesi zaten 30 dakikada anlamli olcude degismiyor,
# yani hicbir sey kaybetmiyoruz.
ONBELLEK_FILE = ROOT / "state" / "reddit_cache.json"
ONBELLEK_DK = 30

# Baslik eslestirmede sayilmayan kelimeler. Haber basliklarinin yarisi
# bunlardan olusuyor ve dahil edilirse her sey her seye benziyor.
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for",
    "with", "is", "are", "was", "were", "be", "been", "it", "its", "this",
    "that", "as", "at", "by", "from", "has", "have", "had", "will", "would",
    "can", "could", "new", "now", "out", "up", "you", "your", "we", "all",
    "more", "about", "after", "before", "into", "than", "then", "not",
    "game", "games", "gaming", "video",
}

# Baslik benzerligi esigi. fetch.py'deki kumeleme esigiyle (0.30) ayni
# mantik ama burada is daha kolay: r/Games gonderileri genelde makalenin
# BASLIGINI birebir tasiyor.
ESLESME_ESIGI = 0.45


# ------------------------------------------------------------- anahtar

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


def kimlik() -> tuple[str, str] | None:
    load_env()
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        return None
    return cid, secret


def _istek(url: str, data: bytes | None = None,
           headers: dict | None = None) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers or {},
                                     method="POST" if data else "GET")
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(3 * attempt)
                continue
            govde = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"reddit {exc.code}: {govde}") from exc
        except urllib.error.URLError as exc:
            if attempt < 3:
                time.sleep(3 * attempt)
                continue
            raise RuntimeError(f"reddit'e ulasilamadi: {exc.reason}") from exc
    raise RuntimeError("reddit: denemeler tukendi")


def token() -> str | None:
    """Uygulama jetonu (app-only OAuth). Kullanici hesabi gerektirmez.

    `client_credentials` akisi: bot kimse adina hareket etmiyor, yalnizca
    herkese acik verileri okuyor. Yazma yetkisi YOK.
    """
    creds = kimlik()
    if creds is None:
        return None

    if TOKEN_FILE.exists():
        try:
            kayit = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            if kayit.get("bitis", 0) > time.time() + 300:
                return kayit["token"]
        except (json.JSONDecodeError, KeyError):
            pass          # bozuk onbellek: yenisini al, patlatma

    cid, secret = creds
    temel = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    cevap = _istek(
        TOKEN_URL,
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
        headers={"Authorization": f"Basic {temel}",
                 "User-Agent": USER_AGENT,
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    jeton = cevap.get("access_token")
    if not jeton:
        raise RuntimeError(f"reddit jetonu alinamadi: {str(cevap)[:200]}")

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({
        "token": jeton,
        "bitis": time.time() + int(cevap.get("expires_in", 3600)),
    }), encoding="utf-8")
    return jeton


# ------------------------------------------------------------- cekme

def sicak_gonderiler(limit: int = 50, sure: str = "day") -> list[dict]:
    """Secili subredditlerin en cok ilgi goren gonderileri.

    Bos liste dondurmek NORMAL: anahtar yoksa ya da reddit erisilemezse
    sistem sinyalsiz calismaya devam eder.
    """
    if ONBELLEK_FILE.exists():
        try:
            kayit = json.loads(ONBELLEK_FILE.read_text(encoding="utf-8"))
            if kayit.get("zaman", 0) > time.time() - ONBELLEK_DK * 60:
                return kayit["gonderiler"]
        except (json.JSONDecodeError, KeyError):
            pass          # bozuk onbellek: yenisini cek, patlatma

    jeton = token()
    if jeton is None:
        return []

    headers = {"Authorization": f"Bearer {jeton}", "User-Agent": USER_AGENT}
    gonderiler = []
    for sub in SUBREDDITS:
        url = f"{API_BASE}/r/{sub}/top?t={sure}&limit={limit}"
        try:
            cevap = _istek(url, headers=headers)
        except RuntimeError as exc:
            print(f"  reddit r/{sub}: {exc}", file=sys.stderr)
            continue
        for child in cevap.get("data", {}).get("children", []):
            veri = child.get("data") or {}
            if veri.get("stickied") or veri.get("over_18"):
                continue
            gonderiler.append({
                "baslik": veri.get("title", ""),
                "sub": sub,
                "oy": int(veri.get("score") or 0),
                "yorum": int(veri.get("num_comments") or 0),
                "url": veri.get("url") or "",
                "permalink": "https://reddit.com" + (veri.get("permalink") or ""),
            })

    # Bos sonuc ONBELLEGE YAZILMIYOR: butun subredditler hata verdiyse
    # yarim saat boyunca sinyalsiz kalmanin anlami yok, bir sonraki
    # calisma tekrar denesin.
    if gonderiler:
        ONBELLEK_FILE.parent.mkdir(parents=True, exist_ok=True)
        ONBELLEK_FILE.write_text(json.dumps(
            {"zaman": time.time(), "gonderiler": gonderiler},
            ensure_ascii=False), encoding="utf-8")
    return gonderiler


# --------------------------------------------------------- eslestirme

def _tokenlar(baslik: str) -> set[str]:
    kelimeler = re.findall(r"[a-z0-9']+", baslik.lower())
    return {k for k in kelimeler if len(k) > 2 and k not in STOPWORDS}


def benzerlik(a: str, b: str) -> float:
    """Iki baslik ne kadar ortusuyor (kucuk olana gore oranlanmis).

    Kucuk olana oranlaniyor cunku reddit baslıklari sik sik makale
    basligina ek aciklama tasiyor ("... [Digital Foundry]"). Jaccard
    kullanilsa o ekler benzerligi haksiz yere dusururdu.
    """
    ta, tb = _tokenlar(a), _tokenlar(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def isi_ekle(candidates: list[dict], gonderiler: list[dict] | None = None) -> list[dict]:
    """Her adaya reddit ilgisini yaz. Adaylari DEGISTIRIR ve dondurur.

    Eslesme bulunamayan aday sifir alir - bu bir eksiklik degil bilgi:
    reddit'te konusulmayan haber, oyuncularin ilgisini cekmemis olabilir.
    Ama TEK BASINA cezalandirmiyoruz (bkz. tier.py): sinyal yalnizca
    yukari itiyor, asagi cekmiyor. Sebep: reddit ingilizce ve pc/konsol
    agirlikli, oradaki sessizlik her zaman ilgisizlik demek degil.
    """
    if gonderiler is None:
        gonderiler = sicak_gonderiler()

    for aday in candidates:
        en_iyi, skor = None, 0.0
        for gonderi in gonderiler:
            oran = benzerlik(aday.get("title", ""), gonderi["baslik"])
            if oran >= ESLESME_ESIGI and oran > skor:
                en_iyi, skor = gonderi, oran
        if en_iyi:
            aday["reddit_oy"] = en_iyi["oy"]
            aday["reddit_yorum"] = en_iyi["yorum"]
            aday["reddit_url"] = en_iyi["permalink"]
        else:
            aday["reddit_oy"] = 0
            aday["reddit_yorum"] = 0
    return candidates


# ------------------------------------------------------------------ cli

def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true", help="anahtarlari canli yokla")
    ap.add_argument("--dump", action="store_true", help="sicak gonderileri listele")
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    if kimlik() is None:
        print("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET yok.")
        print("Modul devre disi - sistem sinyalsiz calisir.")
        return 1

    if args.probe:
        try:
            jeton = token()
        except RuntimeError as exc:
            print(f"KIRMIZI - {exc}")
            return 1
        print(f"YESIL - jeton alindi ({len(jeton)} karakter)")
        gonderiler = sicak_gonderiler(limit=5)
        print(f"YESIL - {len(gonderiler)} gonderi okundu "
              f"({', '.join('r/' + s for s in SUBREDDITS)})")
        return 0

    gonderiler = sicak_gonderiler(limit=args.limit)
    gonderiler.sort(key=lambda g: g["oy"], reverse=True)
    for g in gonderiler:
        print(f"{g['oy']:>6} oy  {g['yorum']:>5} yorum  r/{g['sub']:<22} "
              f"{g['baslik'][:80]}")
    print(f"\ntoplam {len(gonderiler)} gonderi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

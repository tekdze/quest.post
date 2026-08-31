#!/usr/bin/env python3
"""Steam mağaza görselleri: IGDB havuzunu tamamlar.

Neden var: IGDB tek kaynaktı ve bazı oyunlarda havuz 3-4 kareye düşüyordu.
Eşleştirme (`qa.py`) ancak havuzdaki kadar iyi olabiliyor - olmayan kareyi
seçemez. Steam ekran görüntüleri oyun başına 10-15 kare daha getiriyor.

Telif tarafı değişmiyor: bu kareleri **yayıncının kendisi** mağaza sayfasına
yüklüyor, yani IGDB ile aynı kategori - basın ve tanıtım için dağıtılan
materyal. Kredi de uydurulmuyor: `appdetails` geliştirici ve yayıncı adını
veriyor, kart onu basıyor.

Anahtar gerekmez: iki uç nokta da herkese açık.

Kullanım:
    py -3.12 src/steam.py "Hollow Knight Silksong"      # havuzu listele
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import images as igdb  # noqa: E402  (isim eslestirme ve esikler oradan)

SEARCH_URL = "https://steamcommunity.com/actions/SearchApps/{q}"
DETAILS_URL = "https://store.steampowered.com/api/appdetails?appids={appid}&l=english"
UA = {"User-Agent": "questpost/0.1"}

# Bir oyundan en fazla bu kadar kare alinir. Steam bazi oyunlarda 40+ kare
# tutuyor; hepsini almak hem boyut sorgusunu uzatiyor hem havuz izgarasini
# okunmaz yapiyor.
MAX_KARE = 15
# Boyut, dosyanin ilk parcasindan okunuyor: tam indirmeye gerek yok.
BASLIK_BAYT = 8192


def _al(url: str, rng: int | None = None, timeout: int = 30) -> bytes:
    headers = dict(UA)
    if rng:
        headers["Range"] = f"bytes=0-{rng}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def goruntu_boyutu(data: bytes) -> tuple[int, int] | None:
    """JPEG veya PNG başlığından genişlik/yükseklik. Bağımlılık istemez.

    Steam `appdetails` boyut bilgisi VERMİYOR, ama bulanık kart basmamak
    için ölçü şart (bkz. DEVIR: IGDB görselleri 600x338 ile 10681x7874
    arasında değişiyordu, filtre olmadan şans işi).
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return int(w), int(h)
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        isaret = data[i + 1]
        # SOF0..SOF15 (DHT/DAC haric): boyut burada yaziyor.
        if isaret in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return int(w), int(h)
        if isaret in (0xD8, 0xD9) or 0xD0 <= isaret <= 0xD7:
            i += 2
            continue
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def find_app(name: str) -> dict | None:
    """Oyunu Steam'de ara. Sürüm çakışması varsa reddet.

    Eşik ve sürüm kuralı IGDB tarafıyla ORTAK (`images.py`): "Grand Theft
    Auto VI" araması Steam'de "Grand Theft Auto V Enhanced" döndürüyor ve
    kontrolsüz bırakılsa yanlış oyunun kareleri basılırdı.
    """
    try:
        sonuc = json.loads(_al(SEARCH_URL.format(q=urllib.parse.quote(name))))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        print(f"  steam aramasi basarisiz: {exc}", file=sys.stderr)
        return None

    en_iyi, en_iyi_skor = None, 0.0
    for row in (sonuc or [])[:8]:
        ad = row.get("name") or ""
        skor = igdb.name_score(name, ad)
        if igdb.version_conflict(name, ad):
            skor -= 0.5
        if skor > en_iyi_skor:
            en_iyi, en_iyi_skor = row, skor
    if en_iyi is None or en_iyi_skor < igdb.NAME_MATCH_MIN:
        return None
    return {"appid": en_iyi["appid"], "name": en_iyi["name"], "skor": en_iyi_skor}


def app_details(appid: int | str) -> dict | None:
    try:
        veri = json.loads(_al(DETAILS_URL.format(appid=appid)))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        print(f"  steam appdetails basarisiz: {exc}", file=sys.stderr)
        return None
    kayit = (veri or {}).get(str(appid)) or {}
    return kayit.get("data") if kayit.get("success") else None


def kredi(data: dict) -> str | None:
    """Kart kredisi: önce geliştirici, yoksa yayıncı. IGDB ile aynı kural."""
    for alan in ("developers", "publishers"):
        adlar = data.get(alan) or []
        if adlar:
            return str(adlar[0]).lower()
    return None


def havuz(name: str, en_fazla: int = MAX_KARE) -> list[dict]:
    """Oyunun Steam karelerini `images.py` havuz biçiminde döndür.

    Satırlar IGDB satırlarıyla aynı alanlara sahip; ek olarak `url` (tam
    çözünürlük) ve `thumb` (ızgara önizlemesi) taşıyorlar. Böylece iki
    kaynak tek havuzda karışabiliyor ve `/gorsel 4 7 2` numaralandırması
    bozulmuyor.
    """
    app = find_app(name)
    if app is None:
        return []
    data = app_details(app["appid"])
    if not data:
        return []

    oyun_adi = data.get("name") or app["name"]
    studyo = kredi(data)
    satirlar: list[dict] = []
    for sira, kare in enumerate((data.get("screenshots") or [])[:en_fazla]):
        url = kare.get("path_full")
        if not url:
            continue
        try:
            olcu = goruntu_boyutu(_al(url, BASLIK_BAYT))
        except (urllib.error.URLError, OSError):
            continue
        if not olcu:
            continue
        w, h = olcu
        # Bulanik kart basmamak icin ayni esik (DEVIR bolum 8).
        if w < igdb.MIN_IMAGE_WIDTH or h < igdb.MIN_IMAGE_HEIGHT:
            continue
        satirlar.append({
            "id": f"steam{app['appid']}-{sira}",
            "kind": "screenshot",
            "w": w, "h": h,
            "credit": studyo,
            "oyun": oyun_adi,
            "url": url,
            "thumb": kare.get("path_thumbnail") or url,
        })
    return satirlar


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post steam gorsel havuzu")
    ap.add_argument("oyun")
    ap.add_argument("--limit", type=int, default=MAX_KARE)
    args = ap.parse_args()

    app = find_app(args.oyun)
    if app is None:
        print(f'"{args.oyun}" steam\'de bulunamadi (veya surum uyusmadi)')
        return 1
    print(f"eslesme: {app['name']} (appid {app['appid']}, benzerlik {app['skor']:.2f})")

    satirlar = havuz(args.oyun, args.limit)
    print(f"{len(satirlar)} kullanilabilir kare (>= {igdb.MIN_IMAGE_WIDTH}x"
          f"{igdb.MIN_IMAGE_HEIGHT}):")
    for sira, row in enumerate(satirlar, 1):
        print(f"  {sira:2}. {row['w']}x{row['h']} | {row['credit']} | {row['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

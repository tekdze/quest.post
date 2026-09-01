#!/usr/bin/env python3
"""Instagram uzun ömürlü jetonunu yeniler ve durumunu bildirir.

Jeton 60 günde ölüyor ve kendiliğinden yenilenmiyor. Öldüğü gün bot
paylaşamaz hale gelir; üstelik sessizce, çünkü kimse `/ok` demeden fark
edilmez. Bu yüzden aylık çalışıp jetonu tazeliyoruz.

⚠️ Yenilenen jeton YENİ bir değer: Meta'nın döndürdüğü jetonu GitHub
Secrets'a elle girmek gerekiyor - Actions kendi secret'ını yazamaz.
O yüzden betik yeni jetonu Telegram'a YOLLAMAZ (sohbete sır düşmesin);
sadece "yenilenmesi gerekiyor" der ve ne yapılacağını söyler.

Kullanım:
    py -3.12 src/refresh_token.py            # durumu bildir
    py -3.12 src/refresh_token.py --goster   # yeni jetonu EKRANA bas (yerel)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish  # noqa: E402
import telegram as tg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SURE_FILE = ROOT / "state" / "api_sure.json"

REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
# Meta 60 gun veriyor. 50 gun dolunca yenilemek guvenli: jeton hala
# gecerliyken yenilenmeli, olmus jeton yenilenemiyor.
YENILEME_GUNU = 50


def refresh(token: str) -> dict:
    params = urllib.parse.urlencode({
        "grant_type": "ig_refresh_token",
        "access_token": token,
    })
    request = urllib.request.Request(f"{REFRESH_URL}?{params}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        sys.exit(f"jeton yenilenemedi ({exc.code}):\n{body[:400]}")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="instagram jeton yenileme")
    ap.add_argument("--goster", action="store_true",
                    help="yeni jetonu ekrana bas (SADECE yerelde kullan)")
    args = ap.parse_args()

    token, _ = publish.credentials()
    sonuc = refresh(token)
    kalan_sn = int(sonuc.get("expires_in", 0))
    kalan_gun = kalan_sn // 86400
    yeni = sonuc.get("access_token", "")

    print(f"jeton yenilendi, yeni omru: {kalan_gun} gun")

    # Yenileme tarihini kaydet ki /apideadline dogru sayabilsin.
    kayit = tg.read_json(SURE_FILE, {})
    kayit["instagram"] = {
        "yenilendi": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kalan_gun": kalan_gun,
        # Sonraki ay ayni soru sorulmasin diye kayitli.
        "deger_degisti": bool(yeni and yeni != token),
    }
    tg.write_json(SURE_FILE, kayit)

    if args.goster:
        print(f"\nyeni jeton:\n{yeni}")
        return 0

    # ⚠️ Meta cogu zaman AYNI jetonu uzatiyor, yenisini vermiyor.
    # Olculdu (2026-09-01): aylik yenileme calisti, mesaj "secrets'taki
    # deger hala eski, elle gir" dedi, ama /apideadline YESILDI - cunku
    # deger degismemisti ve yapilacak bir sey yoktu.
    #
    # Eski mesaj her ay bu yanlis alarmi uretecekti. Karsilastirma
    # mekanik oldugu icin kod yapiyor. Bildirim disiplini bunu
    # gerektiriyor: her ay "bir sey yap" diyen ama gerekmeyen mesaj,
    # gercekten gerektiginde de ciddiye alinmaz.
    if yeni and yeni == token:
        tg.send_text(
            f"instagram jetonu tazelendi, ömrü {kalan_gun} gün.\n\n"
            "değer değişmedi, yapman gereken bir şey yok."
        )
        print("jeton ayni: elle islem gerekmiyor")
        return 0

    # Actions kendi secret'ini yazamaz: yeni jeton elle girilmeli.
    # Jeton Telegram'a YOLLANMAZ - sohbete sir dusmemeli.
    tg.send_text(
        "instagram jetonu yenilendi ve DEĞER DEĞİŞTİ.\n\n"
        f"yeni jetonun ömrü {kalan_gun} gün. ancak github secrets'taki değer "
        "hâlâ eski: actions kendi secret'ını yazamıyor.\n\n"
        "önce /apideadline yaz. instagram yeşilse acele yok.\n\n"
        "yapman gereken: bilgisayarda\n"
        "py -3.12 src/refresh_token.py --goster\n"
        "çalıştır, çıkan jetonu IG_ACCESS_TOKEN secret'ına yapıştır.\n"
        "(bunun için .env'inde IG_ACCESS_TOKEN olmalı)"
    )
    print("telegram'a bildirildi (jeton yollanmadi)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

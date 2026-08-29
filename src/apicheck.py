#!/usr/bin/env python3
"""Anahtarların durumunu yoklar: çalışıyor mu, kotası doldu mu, süresi bitiyor mu.

Neden canlı yoklama: sadece tarih tutmak kırılgan. Yenileme tarihini elle
girmeyi unutunca tablo yalan söyler. Yoklama "şu an gerçekten çalışıyor mu"
sorusunu cevaplar ve süreyle ilgisi olmayan sorunları (kota aşımı, iptal
edilmiş anahtar, hesap engeli) da yakalar.

Neden yine de tarih tutuluyor: yoklama "ne zaman bitecek" demez. Instagram'ın
uzun ömürlü jetonu 60 günde ölüyor ve öldüğü gün bot susar; sarı uyarı bunun
için.

    🟢 çalışıyor, süresi uzak
    🟡 süresi yaklaştı veya kota sınırına gelindi
    🔴 çalışmıyor, süresi doldu veya kota bitti

Kullanım:
    py -3.12 src/apicheck.py             # yokla ve Telegram'a yolla
    py -3.12 src/apicheck.py --dry-run   # yollamaz, ekrana basar
    py -3.12 src/apicheck.py --yenilendi instagram   # bugun yenilendi isaretle
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram as tg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SURE_FILE = ROOT / "state" / "api_sure.json"

# Omru olan anahtarlar. Omru olmayanlar (Gemini, Telegram) burada yok:
# onlar icin sadece canli yoklama anlamli.
OMURLER = {
    # Instagram uzun omurlu jeton 60 gunde oluyor, refresh_token.yml
    # yenileyecek. Su an Faz 6 yazilmadigi icin listede pasif duruyor.
    "instagram": 60,
}
# Kalan gun bu esigin altina duserse sari.
UYARI_GUNU = 15


def yesil(mesaj: str) -> tuple[str, str]:
    return "🟢", mesaj


def sari(mesaj: str) -> tuple[str, str]:
    return "🟡", mesaj


def kirmizi(mesaj: str) -> tuple[str, str]:
    return "🔴", mesaj


def yokla_gemini() -> tuple[str, str]:
    """models.list en ucuz cagri: jeton harcamaz, anahtari dogrular."""
    try:
        import write as writer
        writer.api_call("models")
    except SystemExit as exc:
        metin = str(exc)
        if "429" in metin or "RESOURCE_EXHAUSTED" in metin:
            return kirmizi("günlük kota doldu")
        if "403" in metin or "PERMISSION_DENIED" in metin:
            return kirmizi("erişim reddedildi (hesap engeli olabilir)")
        return kirmizi(metin.split("\n")[0][:60])
    except Exception as exc:                              # noqa: BLE001
        return kirmizi(f"{type(exc).__name__}: {str(exc)[:50]}")
    return yesil("çalışıyor")


def yokla_igdb() -> tuple[str, str]:
    """Uygulama jetonu her calismada yeniden aliniyor, asil sinav bu."""
    try:
        import images as img
        cid, secret = img.credentials()
        token = img.get_token(cid, secret)
        img.igdb_query(cid, token, "games", "fields name; limit 1;")
    except SystemExit as exc:
        return kirmizi(str(exc).split("\n")[0][:60])
    except Exception as exc:                              # noqa: BLE001
        return kirmizi(f"{type(exc).__name__}: {str(exc)[:50]}")
    return yesil("çalışıyor (jeton her çalışmada yenileniyor)")


def yokla_telegram() -> tuple[str, str]:
    try:
        sonuc = tg.call("getMe")
    except SystemExit as exc:
        return kirmizi(str(exc).split("\n")[0][:60])
    except Exception as exc:                              # noqa: BLE001
        return kirmizi(f"{type(exc).__name__}: {str(exc)[:50]}")
    return yesil(f"çalışıyor (@{sonuc.get('username', '?')})")


def yokla_instagram() -> tuple[str, str]:
    if not (ROOT / "src" / "publish.py").exists():
        return "⚪", "henüz kurulmadı (Faz 6)"
    return sari("publish.py var ama yoklama yazılmadı")


# Bot en son ne zaman tetiklendi. Harici tetikleyici (cron-job.org) sessizce
# durursa - token iptal olmus, servis hesabi kapanmis, is silinmis - bot
# hicbir sey soylemeden olur. Tek belirti calisma kaydinin eskimesidir.
TETIK_SARI_DK = 30
TETIK_KIRMIZI_DK = 120
RUNS_URL = ("https://api.github.com/repos/tekdze/quest.post/actions/runs"
            "?per_page=1")


def yokla_tetikleme() -> tuple[str, str]:
    """Son workflow çalışmasının üstünden ne kadar geçti."""
    try:
        request = urllib.request.Request(
            RUNS_URL, headers={"User-Agent": "questpost/0.1",
                               "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return sari(f"kontrol edilemedi ({type(exc).__name__})")

    runs = data.get("workflow_runs") or []
    if not runs:
        return kirmizi("hiç çalışma yok")

    son = runs[0]
    try:
        an = datetime.fromisoformat(son["created_at"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return sari("son çalışma zamanı okunamadı")

    dakika = int((datetime.now(timezone.utc) - an).total_seconds() // 60)
    ad = son.get("name", "?")
    if dakika >= TETIK_KIRMIZI_DK:
        return kirmizi(f"son çalışma {dakika} dk önce ({ad}) - tetikleyici durmuş olabilir")
    if dakika >= TETIK_SARI_DK:
        return sari(f"son çalışma {dakika} dk önce ({ad})")
    return yesil(f"son çalışma {dakika} dk önce ({ad})")


YOKLAMALAR = [
    ("gemini", "Gemini (metin)", yokla_gemini),
    ("igdb", "IGDB (görsel)", yokla_igdb),
    ("telegram", "Telegram (bot)", yokla_telegram),
    ("instagram", "Instagram (paylaşım)", yokla_instagram),
    ("tetikleme", "Tetikleme (Actions)", yokla_tetikleme),
]


def sure_durumu(ad: str) -> str | None:
    """Ömrü olan anahtar için kalan gün metni. Yoksa None."""
    omur = OMURLER.get(ad)
    if not omur:
        return None
    kayit = tg.read_json(SURE_FILE, {}).get(ad)
    if not kayit or not kayit.get("yenilendi"):
        return "yenilenme tarihi kayıtlı değil"
    try:
        son = datetime.fromisoformat(kayit["yenilendi"])
    except ValueError:
        return "yenilenme tarihi okunamadı"
    if son.tzinfo is None:
        son = son.replace(tzinfo=timezone.utc)
    gecen = (datetime.now(timezone.utc) - son).days
    kalan = omur - gecen
    if kalan <= 0:
        return f"süresi {-kalan} gün önce doldu"
    return f"{kalan} gün kaldı"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post anahtar durumu")
    ap.add_argument("--dry-run", action="store_true", help="Telegram'a yollamaz")
    ap.add_argument("--yenilendi", metavar="AD",
                    help="bu anahtarin bugun yenilendigini kaydet (ornek: instagram)")
    args = ap.parse_args()

    if args.yenilendi:
        kayit = tg.read_json(SURE_FILE, {})
        kayit[args.yenilendi] = {
            "yenilendi": datetime.now(timezone.utc).isoformat(timespec="seconds")
        }
        tg.write_json(SURE_FILE, kayit)
        print(f"{args.yenilendi}: yenilenme tarihi bugun olarak kaydedildi")
        return 0

    satirlar = ["anahtar durumu:", ""]
    sorunlu = 0

    for ad, baslik, yokla in YOKLAMALAR:
        isaret, mesaj = yokla()
        # Henuz kurulmamis servis icin sure satiri gurultu.
        kalan = None if isaret == "⚪" else sure_durumu(ad)

        # Yoklama gecse bile suresi yaklastiysa sariya cekilir: bugun
        # calisiyor olmasi yarin calisacagi anlamina gelmiyor.
        if isaret == "🟢" and kalan:
            if "doldu" in kalan:
                isaret = "🔴"
            else:
                try:
                    gun = int(kalan.split()[0])
                    if gun <= UYARI_GUNU:
                        isaret = "🟡"
                except (ValueError, IndexError):
                    pass

        if isaret in ("🔴", "🟡"):
            sorunlu += 1

        satir = f"{isaret} {baslik} — {mesaj}"
        if kalan:
            satir += f" · {kalan}"
        satirlar.append(satir)
        print(satir)

    satirlar.append("")
    if sorunlu:
        satirlar.append(f"{sorunlu} anahtar ilgi bekliyor.")
    else:
        satirlar.append("hepsi çalışıyor.")

    metin = "\n".join(satirlar)
    if args.dry_run:
        print("\n--- yollanmadi ---")
        return 0
    tg.send_text(metin)
    print("\ndurum Telegram'a yollandi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

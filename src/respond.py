#!/usr/bin/env python3
"""Telegram'dan gelen kararı okur ve UYGULAR. respond.yml'in çağırdığı şey bu.

İş bölümü: `telegram.py` kararı kaydeder (kayıt memuru), `respond.py` kararı
uygular (icra). Bu ayrım olmadan telegram.py hem mesajlaşma hem boru hattı
yönetimi yapardı.

    /ok      -> yayınla (Faz 6'ya kadar: kullanıcıya /bana öner)
    /bana    -> kartlar zaten yollandı, kuyruk temizlenir
    /iptal   -> kuyruk temizlenir
    /yeniden -> metin baştan yazılır, kartlar yeniden basılır, tekrar sorulur
    /c/b/a/s -> tier değişti, kartlar yeniden basılır, tekrar sorulur
    /gorsel  -> seçilen görsellerle yeniden basılır, tekrar sorulur

Kullanım:
    py -3.12 src/respond.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram as tg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PENDING_FILE = ROOT / "state" / "pending.json"


def run(script: str, *args: str) -> bool:
    command = [sys.executable, str(SRC / script), *args]
    print(f"\n$ {script} {' '.join(args)}", flush=True)
    return subprocess.run(command, cwd=ROOT).returncode == 0


def kuyrugu_temizle(pending: dict, durum: str) -> None:
    pending["durum"] = durum
    tg.write_json(PENDING_FILE, pending)


def yeniden_bas_ve_sor(pending: dict, draft: Path, cards_dir: Path,
                       gorsel_yeniden: bool = False) -> int:
    """Kartları yeniden bas ve onayı tekrar sor."""
    if gorsel_yeniden and not run("images.py", str(draft)):
        tg.send_text("görselleri yeniden seçerken hata oldu.")
        return 1
    if not run("render.py", str(draft), "--out", str(cards_dir)):
        tg.send_text("kartları basarken hata oldu.")
        return 1
    if not run("telegram.py", "send", str(draft), "--cards", str(cards_dir)):
        return 1
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post karar uygulayici")
    ap.add_argument("--skip-poll", action="store_true",
                    help="Telegram'i okuma, mevcut pending.json durumunu uygula")
    args = ap.parse_args()

    if not args.skip_poll and not run("telegram.py", "poll"):
        return 1

    pending = tg.read_json(PENDING_FILE, None)
    if not pending:
        print("bekleyen post yok")
        return 0

    durum = pending.get("durum")
    print(f"\ndurum: {durum}")

    if durum in (None, "onay_bekliyor", "tamam", "iptal_edildi"):
        print("uygulanacak karar yok")
        return 0

    draft = ROOT / pending["draft"]
    cards_dir = ROOT / pending["cards_dir"]

    if durum == "yayinla":
        # Faz 6 (publish.py) yazilana kadar otomatik paylasim yok.
        # Sessizce basarisiz olmaktansa kullaniciya durumu soyle.
        if (SRC / "publish.py").exists():
            if not run("publish.py", str(draft), "--cards", str(cards_dir)):
                tg.send_text("paylaşım başarısız oldu, /bana ile elle atabilirsin.")
                return 1
            kuyrugu_temizle(pending, "tamam")
            tg.send_text("paylaşıldı.")
            return 0
        tg.send_text("otomatik paylaşım henüz bağlı değil (instagram kurulumu "
                     "yapılmadı). kartları almak için /bana yaz.")
        kuyrugu_temizle(pending, "onay_bekliyor")
        return 0

    if durum == "elle":
        # Kartlar telegram.py tarafindan zaten dosya olarak yollandi.
        kuyrugu_temizle(pending, "tamam")
        print("kuyruk temizlendi, yeni uretime hazir")
        return 0

    if durum == "iptal":
        kuyrugu_temizle(pending, "iptal_edildi")
        print("post iptal edildi, kuyruk bos")
        return 0

    if durum == "yeniden_uret":
        spec = json.loads(draft.read_text(encoding="utf-8"))
        index = spec.get("_aday_index")
        if not index:
            tg.send_text("bu postun aday sırası kayıtlı değil, yeniden "
                         "üretemiyorum. /iptal yazıp yeni üretim bekle.")
            return 1
        tg.send_text("metin yeniden yazılıyor...")
        if not run("write.py", "--index", str(index), "--tier", spec["tier"],
                   "--out", str(draft)):
            tg.send_text("yeniden üretim başarısız oldu.")
            return 1
        return yeniden_bas_ve_sor(pending, draft, cards_dir, gorsel_yeniden=True)

    if durum in ("yeniden_bas", "gorsel_degisti"):
        tg.send_text("kartlar yeniden basılıyor...")
        return yeniden_bas_ve_sor(pending, draft, cards_dir,
                                  gorsel_yeniden=(durum == "gorsel_degisti"))

    print(f"bilinmeyen durum: {durum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

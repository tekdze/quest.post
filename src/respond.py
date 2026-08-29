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


def run(script: str, *args: str) -> bool:
    command = [sys.executable, str(SRC / script), *args]
    print(f"\n$ {script} {' '.join(args)}", flush=True)
    return subprocess.run(command, cwd=ROOT).returncode == 0


def durumu_yaz(entry: dict, durum: str) -> None:
    """Girdinin durumunu güncelle ve kuyruğu diske yaz."""
    queue = tg.load_queue()
    for row in queue:
        if row.get("id") == entry.get("id"):
            row["durum"] = durum
            break
    tg.save_queue(queue)
    entry["durum"] = durum


def kuyruktan_cikar(entry: dict) -> None:
    """İşi biten postu kuyruktan düşür.

    Tek slotlu dönemde durum "tamam" yazılıp bırakılıyordu; çok girdili
    kuyrukta bitmiş postu tutmak listeyi şişirir ve /kuyruk çıktısını bozar.
    """
    queue = [row for row in tg.load_queue() if row.get("id") != entry.get("id")]
    tg.save_queue(queue)


def etiketle(entry: dict, mesaj: str) -> str:
    """Birden fazla post kuyruktayken mesajın hangi posta ait olduğu belli olsun.

    Kuyruğun tamamına bakılır, bekleyenlere değil: işlenen postun durumu
    "onay_bekliyor" olmaktan çıktığı için bekleyen sayısı yanıltıcı olurdu.
    """
    if len(tg.load_queue()) > 1:
        return f"[{entry.get('baslik') or entry.get('id')}] {mesaj}"
    return mesaj


def yeniden_bas_ve_sor(entry: dict, draft: Path, cards_dir: Path,
                       gorsel_yeniden: bool = False) -> int:
    """Kartları yeniden bas ve onayı tekrar sor."""
    if gorsel_yeniden and not run("images.py", str(draft)):
        tg.send_text(etiketle(entry, "görselleri yeniden seçerken hata oldu."))
        return 1
    if not run("render.py", str(draft), "--out", str(cards_dir)):
        tg.send_text(etiketle(entry, "kartları basarken hata oldu."))
        return 1
    # Etiket korunmali: acil post yeniden basildiginda normale dusmesin.
    if not run("telegram.py", "send", str(draft), "--cards", str(cards_dir),
               "--etiket", entry.get("etiket", "normal")):
        return 1
    return 0


def girdiyi_isle(entry: dict) -> int:
    """Tek bir postun kararını uygula."""
    durum = entry.get("durum")
    draft = ROOT / entry["draft"]
    cards_dir = ROOT / entry["cards_dir"]
    print(f"\n[{entry.get('id')}] durum: {durum}")

    if durum == "yayinla":
        # Faz 6 (publish.py) yazilana kadar otomatik paylasim yok.
        # Sessizce basarisiz olmaktansa kullaniciya durumu soyle.
        if (SRC / "publish.py").exists():
            if not run("publish.py", str(draft), "--cards", str(cards_dir)):
                tg.send_text(etiketle(entry, "paylaşım başarısız oldu, /bana ile "
                                             "elle atabilirsin."))
                durumu_yaz(entry, "onay_bekliyor")
                return 1
            tg.send_text(etiketle(entry, "paylaşıldı."))
            kuyruktan_cikar(entry)
            return 0
        tg.send_text(etiketle(entry, "otomatik paylaşım henüz bağlı değil "
                                     "(instagram kurulumu yapılmadı). kartları "
                                     "almak için /bana yaz."))
        durumu_yaz(entry, "onay_bekliyor")
        return 0

    if durum == "elle":
        # Kartlar telegram.py tarafindan zaten dosya olarak yollandi.
        kuyruktan_cikar(entry)
        print("kuyruktan cikarildi")
        return 0

    if durum == "iptal":
        kuyruktan_cikar(entry)
        print("post iptal edildi, kuyruktan cikarildi")
        return 0

    if durum == "yeniden_uret":
        spec = json.loads(draft.read_text(encoding="utf-8"))
        index = spec.get("_aday_index")
        if not index:
            tg.send_text(etiketle(entry, "bu postun aday sırası kayıtlı değil, "
                                         "yeniden üretemiyorum. /iptal yazıp yeni "
                                         "üretim bekle."))
            durumu_yaz(entry, "onay_bekliyor")
            return 1
        if not run("write.py", "--index", str(index), "--tier", spec["tier"],
                   "--out", str(draft)):
            tg.send_text(etiketle(entry, "yeniden üretim başarısız oldu."))
            durumu_yaz(entry, "onay_bekliyor")
            return 1
        return yeniden_bas_ve_sor(entry, draft, cards_dir, gorsel_yeniden=True)

    if durum == "havuz":
        # Havuzu göster, kuyruğu bozma: kullanıcı bakıp karar verecek.
        sheet = cards_dir / "havuz.png"
        if not run("render.py", str(draft), "--sheet", str(sheet)):
            tg.send_text(etiketle(entry, "bu postta görsel havuzu yok "
                                         "(tipografik kart)."))
        else:
            tg.send_photo(sheet, "beğendiklerini sayfa sırasına göre yaz: "
                                 "/gorsel 4 7 2")
        durumu_yaz(entry, "onay_bekliyor")
        return 0

    if durum == "gorsel_baska_set":
        if not run("images.py", str(draft), "--rotate", "1"):
            tg.send_text(etiketle(entry, "görselleri değiştirirken hata oldu."))
            durumu_yaz(entry, "onay_bekliyor")
            return 1
        return yeniden_bas_ve_sor(entry, draft, cards_dir)

    if durum in ("yeniden_bas", "gorsel_degisti"):
        return yeniden_bas_ve_sor(entry, draft, cards_dir,
                                  gorsel_yeniden=(durum == "gorsel_degisti"))

    print(f"bilinmeyen durum: {durum}")
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

    queue = tg.load_queue()
    if not queue:
        print("bekleyen post yok")
        return 0

    # Karara baglanmis girdiler. Kuyrukta iki post olabilir ve ikisine de
    # ayri komut verilmis olabilir; her turda hepsi islenir.
    bekleyen_durumlar = {None, "onay_bekliyor"}
    isler = [e for e in queue if e.get("durum") not in bekleyen_durumlar]
    if not isler:
        print(f"uygulanacak karar yok ({len(queue)} post onay bekliyor)")
        return 0

    sonuc = 0
    for entry in isler:
        # girdiyi_isle kuyrugu diske yeniden yaziyor; elimizdeki kopya
        # uzerinden calismak guvenli cunku her girdi kendi id'siyle bulunuyor.
        if girdiyi_isle(entry) != 0:
            sonuc = 1
    return sonuc


if __name__ == "__main__":
    raise SystemExit(main())

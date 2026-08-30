#!/usr/bin/env python3
"""Telegram'dan gelen kararı okur ve UYGULAR. respond.yml'in çağırdığı şey bu.

İş bölümü: `telegram.py` kararı kaydeder (kayıt memuru), `respond.py` kararı
uygular (icra). Bu ayrım olmadan telegram.py hem mesajlaşma hem boru hattı
yönetimi yapardı.

    /ok      -> yayınla (publish.py yoksa kullanıcıya /bana öner)
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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram as tg  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
POSTED_FILE = ROOT / "state" / "posted.json"
MENU_FILE = ROOT / "state" / "menu.json"
CANDIDATES_FILE = ROOT / "state" / "candidates.json"
ISTEK_FILE = ROOT / "state" / "istek.json"


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


def arsivle(entry: dict, sonuc: str) -> None:
    """Karara bağlanan haberi posted.json'a yaz: bir daha aday olmasın.

    Eksikti: posted.json'u hiçbir kod yazmıyordu, sadece fetch.py okuyordu.
    Bu yüzden /iptal denen haber bir sonraki üretimde yine en üstte çıkıyordu.
    İptal de arşive girer - "istemedim" demek "bir daha sorma" demektir.
    """
    draft = ROOT / entry["draft"]
    try:
        spec = json.loads(draft.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("uyari: taslak okunamadi, arsivlenemedi")
        return

    hashes = spec.get("_hashes") or []
    if not hashes:
        # Eski taslaklarda _hashes yok. Sessizce gecmek yerine soyle:
        # bu haber tekrar aday olabilir.
        print(f"uyari: {entry.get('id')} icin hash yok, tekrar filtresine girmedi")
        return

    arsiv = tg.read_json(POSTED_FILE, {"posted": []})
    kayitli = {row.get("hash") for row in arsiv.get("posted", [])}
    eklendi = 0
    for h in hashes:
        if h in kayitli:
            continue
        arsiv["posted"].append({
            "hash": h,
            "id": entry.get("id"),
            "baslik": entry.get("baslik"),
            "sonuc": sonuc,
            "tarih": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        eklendi += 1
    tg.write_json(POSTED_FILE, arsiv)
    print(f"arsivlendi ({sonuc}): {eklendi} kayit -> posted.json")


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


def istekleri_isle() -> int:
    """Posta bağlı olmayan istekleri uygula: /konular, /uret, /apideadline.

    İstek dosyası işlenir işlenmez siliniyor: cron 5 dakikada bir çalıştığı
    için kalan bir istek her turda yeniden üretim tetiklerdi.
    """
    istek = tg.read_json(ISTEK_FILE, None)
    if not istek:
        return 0
    ne = istek.get("istek")
    ISTEK_FILE.unlink(missing_ok=True)
    print(f"\nistek: {ne}")

    if ne == "konular":
        if not run("fetch.py"):
            tg.send_text("kaynakları tararken hata oldu.")
            return 1
        if not run("menu.py"):
            tg.send_text("menüyü hazırlarken hata oldu.")
            return 1
        return 0

    if ne == "api":
        if not run("apicheck.py"):
            tg.send_text("anahtarları yoklarken hata oldu.")
            return 1
        return 0

    if ne == "uret":
        menu = tg.read_json(MENU_FILE, None)
        sira = istek.get("sira")
        aday = next((r for r in (menu or {}).get("adaylar", [])
                     if r.get("sira") == sira), None)
        if not aday:
            tg.send_text("seçtiğin aday listede bulunamadı. /konular ile "
                         "listeyi yenile.")
            return 1

        # produce.py "onay bekleyen normal post varken uretme" diyor ve
        # sessizce cikiyor - kullanici bosuna bekliyordu. Sebebi burada
        # soyleniyor, cunku istegi alan taraf burasi.
        bekleyen = [e for e in tg.bekleyenler(tg.load_queue())
                    if e.get("etiket") != "acil"]
        if bekleyen:
            adlar = ", ".join(e.get("baslik") or e.get("id") for e in bekleyen)
            tg.send_text(f"kuyrukta onay bekleyen post var: {adlar}\n\n"
                         "önce onu karara bağla (/ok · /bana · /iptal), "
                         "sonra tekrar /uret yaz.")
            return 0
        # Adayin tam kaydi menude tasiniyor; candidates.json'u ondan kur.
        # Boylece uretim, menunun gordugu haberin AYNISINI isliyor.
        index = aday.get("aday_index", sira)
        tam = aday.get("aday")
        if tam:
            tg.write_json(CANDIDATES_FILE, {"candidates": [tam]})
            index = 1
        else:
            tg.send_text("bu menü eski biçimde, aday verisi taşınmamış. "
                         "/konular ile listeyi yenile.")
            return 1

        if not run("produce.py", "--skip-fetch", "--index", str(index)):
            tg.send_text("üretim başarısız oldu. actions kaydına bakmak "
                         "gerekebilir.")
            return 1
        return 0

    print(f"bilinmeyen istek: {ne}")
    return 0


def girdiyi_isle(entry: dict) -> int:
    """Tek bir postun kararını uygula."""
    durum = entry.get("durum")
    draft = ROOT / entry["draft"]
    cards_dir = ROOT / entry["cards_dir"]
    print(f"\n[{entry.get('id')}] durum: {durum}")

    if durum == "yayinla":
        # publish.py yoksa otomatik paylasim yapilamaz.
        # Sessizce basarisiz olmaktansa kullaniciya durumu soyle.
        if (SRC / "publish.py").exists():
            if not run("publish.py", str(draft), "--cards", str(cards_dir)):
                tg.send_text(etiketle(entry, "paylaşım başarısız oldu, /bana ile "
                                             "elle atabilirsin."))
                durumu_yaz(entry, "onay_bekliyor")
                return 1
            tg.send_text(etiketle(entry, "paylaşıldı."))
            arsivle(entry, "yayinlandi")
            kuyruktan_cikar(entry)
            return 0
        tg.send_text(etiketle(entry, "otomatik paylaşım henüz bağlı değil "
                                     "(instagram kurulumu yapılmadı). kartları "
                                     "almak için /bana yaz."))
        durumu_yaz(entry, "onay_bekliyor")
        return 0

    if durum == "elle":
        # Kartlar telegram.py tarafindan zaten dosya olarak yollandi.
        arsivle(entry, "elle_alindi")
        kuyruktan_cikar(entry)
        print("kuyruktan cikarildi")
        return 0

    if durum == "iptal":
        arsivle(entry, "iptal")
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
        # write.py taslagi sifirdan yaziyor: kume hash'leri silinirdi ve
        # post karara baglandiginda arsive girmezdi. Geri koyuluyor.
        yeni = json.loads(draft.read_text(encoding="utf-8"))
        yeni["_hashes"] = spec.get("_hashes", [])
        yeni["_kume_key"] = spec.get("_kume_key")
        draft.write_text(json.dumps(yeni, ensure_ascii=False, indent=2),
                         encoding="utf-8")
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

    # Posta bagli olmayan istekler (menu, uretim, anahtar durumu) once:
    # kuyruk bos olsa da calisirlar.
    sonuc_istek = istekleri_isle()

    queue = tg.load_queue()
    if not queue:
        print("bekleyen post yok")
        return sonuc_istek

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

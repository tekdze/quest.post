#!/usr/bin/env python3
"""Tek komutla üretim zinciri. produce.yml'in çağırdığı şey bu.

    fetch -> aday seç -> tier hesapla -> metin yaz -> görsel seç
          -> kart bas -> Telegram'a sor

Her aşama ayrı süreç olarak çalışıyor. Sebep: GitHub Actions kaydında
hangi aşamanın patladığı tek bakışta görünsün, ve bir aşama diğerinin
belleğini kirletmesin.

Kullanım:
    py -3.12 src/produce.py                  # tam zincir
    py -3.12 src/produce.py --skip-fetch     # elde duran candidates.json ile
    py -3.12 src/produce.py --dry-run        # Telegram'a yollamaz
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telegram as tg  # noqa: E402
import tier as tier_module  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
CANDIDATES_FILE = ROOT / "state" / "candidates.json"
DRAFTS_DIR = ROOT / "state" / "drafts"
WEEKLY_FILE = ROOT / "state" / "weekly.json"

# Aday havuzunda bu kadar sirayi gecince aramayi birakiyoruz: daha
# asagisi ya cok eski ya cok zayif.
MAX_TRIES = 8


def run(script: str, *args: str) -> None:
    """Bir aşamayı çalıştır. Patlarsa SEBEBİYLE birlikte zinciri durdur.

    Eskiden sadece "write.py basarisiz oldu (cikis kodu 1)" yazıyordu ve
    gerçek sebep burada kayboluyordu: respond.py bu satırı Telegram'a
    taşıyor, yani kullanıcı "üretim başarısız" görüp Actions kaydını açmak
    zorunda kalıyordu. Alt sürecin son hata satırı artık yukarı çıkıyor.
    """
    command = [sys.executable, str(SRC / script), *args]
    print(f"\n$ {script} {' '.join(args)}", flush=True)
    result = subprocess.run(command, cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if result.returncode != 0:
        sebep = tg.hata_satiri(result.stderr, f"cikis kodu {result.returncode}")
        sys.exit(f"\n{script}: {sebep}")


def run_yumusak(script: str, *args: str) -> bool:
    """Zinciri DURDURMAYAN aşama. İyileştirmeler için.

    `run` patladığında üretim ölüyor; bazı aşamalar ise olmasa da post
    çıkabilir (görsel eşleştirme gibi). Onlar buradan çalışıyor.
    """
    command = [sys.executable, str(SRC / script), *args]
    print(f"\n$ {script} {' '.join(args)}", flush=True)
    if subprocess.run(command, cwd=ROOT).returncode == 0:
        return True
    print(f"{script} basarisiz oldu, zincir devam ediyor", file=sys.stderr)
    return False


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def slugify(text: str) -> str:
    folded = (text or "post").lower()
    for a, b in (("ı", "i"), ("ş", "s"), ("ğ", "g"), ("ü", "u"), ("ö", "o"), ("ç", "c")):
        folded = folded.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:40] or "post"


def already_in_weekly(key: str) -> bool:
    weekly = read_json(WEEKLY_FILE, {"bekleyen": []})
    return any(row.get("key") == key for row in weekly["bekleyen"])


def add_to_weekly(candidate: dict, tier: str) -> None:
    """C kademesi tek başına yayınlanmaz, haftalık derlemeye biriktirilir."""
    weekly = read_json(WEEKLY_FILE, {"bekleyen": []})
    weekly["bekleyen"].append({
        "key": candidate["key"],
        "title": candidate["title"],
        "url": candidate["url"],
        "tier": tier,
        "eklendi": datetime.now(timezone.utc).isoformat(),
    })
    write_json(WEEKLY_FILE, weekly)


def pick_candidate(candidates: list[dict]) -> tuple[dict, str, int] | None:
    """En yüksek sıralı, C olmayan ve derlemede beklemeyen adayı seç.

    C çıkanlar yol boyunca haftalık derlemeye yazılır - eleme değil erteleme.
    """
    for index, candidate in enumerate(candidates[:MAX_TRIES], 1):
        computed, reasons = tier_module.compute(candidate)
        head = f"{index}. [{computed}] {candidate['title'][:60]}"

        if already_in_weekly(candidate["key"]):
            print(f"{head} -> derlemede zaten var, atlaniyor")
            continue
        if computed == "C":
            add_to_weekly(candidate, computed)
            print(f"{head} -> C, haftalik derlemeye eklendi")
            continue

        print(f"{head} -> secildi")
        for reason in reasons:
            print(f"     {reason}")
        return candidate, computed, index
    return None


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post uretim zinciri")
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Telegram'a yollamaz")
    ap.add_argument("--index", type=int, default=None, help="aday secimini elle ez")
    ap.add_argument("--acil", action="store_true",
                    help="son dakika haberi: bekleyen normal post olsa da uret")
    args = ap.parse_args()

    etiket = "acil" if args.acil else "normal"

    # Kuyruk kurali: normal uretim, onay bekleyen normal bir post varken
    # ikincisini uretmez - kullanici karar vermeden yigilmasin. ACIL uretim
    # bu kuraldan muaf: bekleyen post ertelenmez, acil post yanina girer.
    bekleyen = tg.bekleyenler(tg.load_queue())
    if args.acil:
        if len(bekleyen) >= tg.MAX_KUYRUK:
            print(f"kuyruk dolu ({tg.MAX_KUYRUK}), acil post da eklenemiyor.")
            return 0
    else:
        normaller = [e for e in bekleyen if e.get("etiket") != "acil"]
        if normaller:
            print("onay bekleyen normal post var, yeni uretim yapilmadi.")
            for row in normaller:
                print(f"  {row.get('id')}")
            return 0

    if not args.skip_fetch:
        run("fetch.py")

    data = read_json(CANDIDATES_FILE, None)
    if not data or not data.get("candidates"):
        sys.exit("aday bulunamadi (candidates.json bos)")

    # Kaynak sağlığını rapora yaz: ölen besleme sessizce kaybolmasın.
    dead = [h["id"] for h in data.get("feed_health", []) if not h["ok"]]
    if dead:
        print(f"UYARI: cevap vermeyen kaynak(lar): {', '.join(dead)}")

    if args.index:
        candidate = data["candidates"][args.index - 1]
        computed, _ = tier_module.compute(candidate)
        index = args.index
        print(f"elle secildi: [{computed}] {candidate['title'][:60]}")
    else:
        picked = pick_candidate(data["candidates"])
        if not picked:
            print("\nyayina uygun aday yok (hepsi C veya derlemede). "
                  "haftalik derleme buyudu.")
            return 0
        candidate, computed, index = picked

    # Taslak once gecici adla yazilir: dosya adindaki oyun adi ancak write.py
    # calistiktan sonra biliniyor. Her postun kendi taslagi olmali, yoksa
    # kuyrukta iki post varken ikincisi birincisinin metnini ezerdi.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    gecici = DRAFTS_DIR / f"_uretiliyor-{stamp}.json"
    run("write.py", "--index", str(index), "--tier", computed, "--out", str(gecici))

    spec = read_json(gecici, {})
    # Kumedeki her kaydin hash'i taslaga yaziliyor: post karara baglandiginda
    # (yayinlandi ya da iptal edildi) respond.py bunlari posted.json'a
    # gecirecek ve fetch.py ayni haberi bir daha aday yapmayacak.
    spec["_hashes"] = [m["hash"] for m in candidate.get("members", []) if "hash" in m]
    spec["_kume_key"] = candidate.get("key")
    write_json(gecici, spec)

    post_id = f"{stamp}-{slugify(spec.get('game', 'post'))}"
    # Ayni gun ayni oyundan ikinci post: kuyrukta id cakismasin.
    if any(e.get("id") == post_id for e in tg.load_queue()):
        post_id = f"{post_id}-2"
    draft_file = DRAFTS_DIR / f"{post_id}.json"
    gecici.replace(draft_file)

    run("images.py", str(draft_file))

    # Gorsel-sayfa eslestirme. images.py kareleri sayfa TIPINE gore
    # dagitiyor, icerikle bagi tesadufi kaliyordu. qa.py havuzu modele
    # gosterip her sayfaya hangi karenin uydugunu soruyor; secimi kod
    # dogruluyor. Bir IYILESTIRME oldugu icin patlarsa zincir durmuyor,
    # mevcut secimle devam ediliyor.
    if run_yumusak("qa.py", str(draft_file)):
        if read_json(draft_file, {}).get("_gorsel_secimi"):
            # Yeni secim images.py tarafindan uygulaniyor (indirme dahil).
            run("images.py", str(draft_file))

    out_dir = ROOT / "out" / post_id
    run("render.py", str(draft_file), "--out", str(out_dir))

    # KART DENETIMI. Yazilmisti ama zincire hic baglanmamisti - yani
    # canlida bir kez bile calismadi (bulundu 2026-09-01: dawnwalker
    # testinde kapakta "DAWNWALKE" diye kesilmis logo basildi ve hicbir
    # sey yakalamadi). Yukaridaki qa.py cagrisi GORSEL-SAYFA
    # ESLESTIRMESI; bu ayri is ve BASILMIS karta bakiyor, cunku kirpma
    # ancak render'dan sonra gorunur.
    #
    # ⚠️ DERS: "yazildi" ile "calisiyor" ayni sey degil. DEVIR'de bitmis
    # gorunuyordu (bkz. komut listesi dersi: arayuz eklerken once icra
    # tarafi yazilmali - burada tersi oldu, icra vardi cagri yoktu).
    if run_yumusak("qa.py", str(draft_file), "--kartlar", str(out_dir)):
        if read_json(draft_file, {}).get("_gorsel_secimi"):
            run("images.py", str(draft_file))
            run("render.py", str(draft_file), "--out", str(out_dir))

    if args.dry_run:
        print(f"\n--dry-run: Telegram'a yollanmadi. kartlar: {out_dir}")
        return 0

    run("telegram.py", "send", str(draft_file), "--cards", str(out_dir),
        "--etiket", etiket)
    print(f"\nzincir tamamlandi ({etiket}), onay bekleniyor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

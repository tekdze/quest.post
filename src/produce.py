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
import tier as tier_module  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
CANDIDATES_FILE = ROOT / "state" / "candidates.json"
DRAFT_FILE = ROOT / "state" / "draft.json"
WEEKLY_FILE = ROOT / "state" / "weekly.json"
PENDING_FILE = ROOT / "state" / "pending.json"

# Aday havuzunda bu kadar sirayi gecince aramayi birakiyoruz: daha
# asagisi ya cok eski ya cok zayif.
MAX_TRIES = 8


def run(script: str, *args: str) -> None:
    """Bir aşamayı çalıştır. Patlarsa zinciri durdur."""
    command = [sys.executable, str(SRC / script), *args]
    print(f"\n$ {script} {' '.join(args)}", flush=True)
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"\n{script} basarisiz oldu (cikis kodu {result.returncode})")


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
    args = ap.parse_args()

    # Onay bekleyen bir post varken yenisini üretmek kuyruğu karıştırır:
    # pending.json tek slot, ikinci post birincisini ezerdi.
    pending = read_json(PENDING_FILE, None)
    if pending and pending.get("durum") == "onay_bekliyor":
        print("onay bekleyen bir post var, yeni uretim yapilmadi.")
        print(f"  {pending.get('draft')}")
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

    run("write.py", "--index", str(index), "--tier", computed,
        "--out", str(DRAFT_FILE))
    run("images.py", str(DRAFT_FILE))

    spec = read_json(DRAFT_FILE, {})
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    out_dir = ROOT / "out" / f"{stamp}-{slugify(spec.get('game', 'post'))}"
    run("render.py", str(DRAFT_FILE), "--out", str(out_dir))

    if args.dry_run:
        print(f"\n--dry-run: Telegram'a yollanmadi. kartlar: {out_dir}")
        return 0

    run("telegram.py", "send", str(DRAFT_FILE), "--cards", str(out_dir))
    print("\nzincir tamamlandi, onay bekleniyor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

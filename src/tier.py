#!/usr/bin/env python3
"""Tier (nadirlik) hesabı. KOD hesaplar, LLM değil.

Tasarım kararı: LLM'e serbestlik verilirse her haberi S yapar. Bu yüzden
tier'ı model belirlemez; eşikler burada, Python'da sabittir. LLM sadece
veri üretir (metin), sinyalleri fetch.py toplar.

Ana sinyal: kaç kaynak yazmış. Bir haberi dört site yazdıysa o haber
gerçekten büyüktür; tek site yazdıysa gündem değil.

Kullanım:
    py -3.12 src/tier.py                 # candidates.json'daki adaylari tierla
    py -3.12 src/tier.py --index 1       # tek adayin gerekcesini goster
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = ROOT / "state" / "candidates.json"

# Kaç kaynak yazdıysa hangi taban tier. Ölçüm (2026-08-25, 48 saatlik
# pencere, 18 kaynak): 4 kaynaklı küme günde 1 tane, 2 kaynaklı 13 tane,
# tek kaynaklı ~180 tane. Yani S doğal olarak nadir kalıyor.
SOURCE_TIERS = [
    (4, "S"),
    (3, "A"),
    (2, "B"),
    (1, "C"),
]

# Ayrıştırıcı kaynak (itch.io, devlog, indie odaklı site) tek başına yazsa
# bile bir kademe yükseltir: bizim değer önerimiz "herkesin yazdığını değil,
# kimsenin görmediğini bulmak".
DISTINCTIVE_WEIGHT = 1.2

TIER_ORDER = ["C", "B", "A", "S"]
TIER_LABELS = {"C": "sıradan", "B": "büyülü", "A": "sıradışı", "S": "mitik"}


def bump(tier: str, steps: int = 1) -> str:
    index = min(TIER_ORDER.index(tier) + steps, len(TIER_ORDER) - 1)
    return TIER_ORDER[index]


def compute(candidate: dict) -> tuple[str, list[str]]:
    """Adayın tier'ını ve gerekçesini döndür."""
    reasons: list[str] = []
    source_count = candidate.get("source_count", 1)

    tier = "C"
    for threshold, value in SOURCE_TIERS:
        if source_count >= threshold:
            tier = value
            break
    reasons.append(f"{source_count} kaynak yazmış -> taban {tier}")

    members = candidate.get("members", [])
    weights = [m.get("weight", 1.0) for m in members] or [1.0]
    tags = {tag for m in members for tag in m.get("tags", [])}
    kinds = {m.get("kind") for m in members}

    if max(weights) >= DISTINCTIVE_WEIGHT:
        tier = bump(tier)
        reasons.append(f"ayrıştırıcı kaynak (ağırlık {max(weights)}) -> {tier}")

    if "indie" in tags and tier == "C":
        tier = bump(tier)
        reasons.append(f"indie etiketli kaynak -> {tier}")

    # Çıkış ve devlog haberleri bizim hesabın çekirdek içeriği; ana akım
    # sitelerin tekrar ettiği duyurulardan daha değerli.
    if kinds & {"releases", "devlog"} and tier in ("C", "B"):
        tier = bump(tier)
        reasons.append(f"çıkış/devlog haberi -> {tier}")

    # Topluluk kaynağı tek başına doğrulanmamış sayılır, yükseltmez.
    if kinds == {"community"}:
        tier = "C"
        reasons.append("yalnızca topluluk kaynağı, doğrulanmamış -> C")

    return tier, reasons


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post tier hesabi")
    ap.add_argument("--index", type=int, default=None, help="tek adayin gerekcesi")
    ap.add_argument("--limit", type=int, default=15)
    args = ap.parse_args()

    if not CANDIDATES_FILE.exists():
        sys.exit("state/candidates.json yok. Once: py -3.12 src/fetch.py")
    data = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
    candidates = data["candidates"]

    if args.index:
        candidate = candidates[args.index - 1]
        tier, reasons = compute(candidate)
        print(f"{candidate['title'][:78]}\n")
        for reason in reasons:
            print(f"  {reason}")
        print(f"\nsonuç: {tier} ({TIER_LABELS[tier]})")
        if tier == "C":
            print("C kademesi tek başına yayınlanmaz, haftalık derlemeye biriktirilir.")
        return 0

    print(f"{'#':>3} {'tier':>4}  {'kyn':>3}  başlık")
    for index, candidate in enumerate(candidates[: args.limit], 1):
        tier, _ = compute(candidate)
        print(f"{index:>3} {tier:>4}  {candidate['source_count']:>3}  "
              f"{candidate['title'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

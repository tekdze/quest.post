#!/usr/bin/env python3
"""Post tarifini (JSON) alip 1080x1350 PNG kartlara cevirir.

Faz 3 - API anahtari gerekmez, sadece Playwright + fontlar.

Tasarim templates/card.html + card.css icinde SABIT durur. Bu dosya sadece
tarayiciyi surer: veriyi basar, gradyani olcturur, ekran goruntusu alir.

Kullanim:
    py -3.12 src/render.py examples/sample_post.json
    py -3.12 src/render.py examples/sample_post.json --out out/deneme
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("playwright kurulu degil. Once: py -3.12 -m pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "card.html"

WIDTH, HEIGHT = 1080, 1350

# Tier: renk + Turkce ad. Tier'i KOD hesaplar (tier.py), LLM degil.
# tier.py yazildiginda esikleri o dosyada tutacak, renk/ad burada kalacak.
TIERS = {
    "C": {"color": "#4A4A4A", "label": "sıradan"},
    "B": {"color": "#2A6398", "label": "büyülü"},
    "A": {"color": "#6A4CA6", "label": "sıradışı"},
    "S": {"color": "#D9741F", "label": "mitik"},
}

DEFAULT_HANDLE = "@quest.post"
DEFAULT_TAGLINE = "haftada üç indie hikayesi"


def resolve_image(value: str | None) -> str | None:
    """Yerel dosya yolunu tarayicinin okuyabilecegi file:// adresine cevir."""
    if not value:
        return None
    if value.startswith(("http://", "https://", "data:", "file://")):
        return value
    path = (ROOT / value).resolve() if not Path(value).is_absolute() else Path(value)
    if not path.exists():
        raise FileNotFoundError(f"gorsel bulunamadi: {path}")
    return path.as_uri()


def build_page_payload(spec: dict, page: dict, index: int, total: int) -> dict:
    tier = spec.get("tier", "C").upper()
    if tier not in TIERS:
        raise ValueError(f"bilinmeyen tier: {tier} (C/B/A/S olmali)")

    page = dict(page)
    page["image"] = resolve_image(page.get("image"))
    if page["type"] == "cover" and not page.get("page_count"):
        page["page_count"] = "tek kare" if total == 1 else f"{total} sayfa"

    return {
        "tier_color": TIERS[tier]["color"],
        "tier_label": TIERS[tier]["label"],
        "category": spec.get("category", ""),
        "game": spec.get("game", ""),
        # Sizinti/datamine haberinde gorsel kullanilmaz, kredi de gerekmez.
        "credit": spec.get("credit") if page["image"] else None,
        "handle": spec.get("handle", DEFAULT_HANDLE),
        "tagline": spec.get("tagline", DEFAULT_TAGLINE),
        "page": page,
        "index": index,
    }


def render(spec: dict, out_dir: Path) -> list[dict]:
    pages = spec["pages"]
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=1,
        )
        page.goto(TEMPLATE.as_uri())
        page.wait_for_function("() => typeof window.renderCard === 'function'")

        for index, spec_page in enumerate(pages, 1):
            payload = build_page_payload(spec, spec_page, index, len(pages))
            metrics = page.evaluate("data => window.renderCard(data)", payload)

            # Fontlar yuklenmeden fotograf cekilirse yedek font goruntuye kacar.
            page.evaluate("() => document.fonts.ready")
            if payload["page"]["image"]:
                page.wait_for_function(
                    "() => { const i = document.querySelector('.card__image');"
                    " return i && i.complete && i.naturalWidth > 0; }"
                )
            # Font yuklenmesi metin blogunun yuksekligini degistirir, gradyani
            # son haliyle yeniden olc.
            metrics = page.evaluate("() => window.fitScrim()") or metrics

            target = out_dir / f"{index:02d}.png"
            page.screenshot(path=str(target))
            written.append({
                "file": str(target.relative_to(ROOT)),
                "type": spec_page["type"],
                "scrim_start_pct": (metrics or {}).get("scrim_start_pct"),
                "scrim_solid_pct": (metrics or {}).get("scrim_solid_pct"),
                "content_height": (metrics or {}).get("content_height"),
            })

        browser.close()
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="quest.post kart uretici (Faz 3)")
    ap.add_argument("spec", help="post tarifi (JSON)")
    ap.add_argument("--out", default=None, help="cikis klasoru (varsayilan: out/<dosya adi>)")
    args = ap.parse_args()

    spec_path = Path(args.spec)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    out_dir = Path(args.out) if args.out else ROOT / "out" / spec_path.stem

    written = render(spec, out_dir)

    print(f"{len(written)} kart uretildi -> {out_dir}")
    for row in written:
        scrim = row["scrim_start_pct"]
        if scrim:
            # Krem alanin altta kapladigi oran: tasarim notundaki referans deger.
            cream = round(100 - row["scrim_solid_pct"], 1)
            note = (f"metin {row['content_height']}px -> gecis %{scrim}, "
                    f"krem alan %{cream}")
        else:
            note = "tipografik (gorsel yok)"
        print(f"  {row['file']:34} {row['type']:8} {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

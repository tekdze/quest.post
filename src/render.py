#!/usr/bin/env python3
"""Post tarifini (JSON) alip 1080x1350 PNG kartlara cevirir.

API anahtari gerekmez, sadece Playwright + fontlar.

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

# Tasarim 1080x1350 CSS pikseli uzerine kurulu, ama PNG bundan daha yogun
# basiliyor: 1080*4/3 = 1440, Instagram'in kabul ettigi en buyuk genislik.
# CSS'e hic dokunulmuyor, sadece piksel yogunlugu artiyor - yazi ve gorsel
# ikisi de keskinlesiyor. Instagram zaten kendi sikistirmasini uyguluyor,
# ona daha fazla piksel vermek her zaman daha iyi sonuc veriyor.
SCALE = 4 / 3

# Tier: renk + Turkce ad. Tier'i KOD hesaplar (tier.py), LLM degil.
# tier.py yazildiginda esikleri o dosyada tutacak, renk/ad burada kalacak.
# Tier: renk + Turkce ad. Tier'i KOD hesaplar (tier.py), LLM degil.
# Tier renginin uzerine her zaman KREM yazi gelir. Olculen kontrast:
# C 7.58 · B 5.38 · A 5.62 · S 2.78. S sinirin altinda kaliyor ama
# kavram butunlugu icin bilerek boyle birakildi - tek kademenin farkli
# davranmasi sistemi bozuyordu (bkz. DEVIR, tasarim kararlari).
TIERS = {
    "C": {"color": "#4A4A4A", "label": "sıradan"},
    "B": {"color": "#2A6398", "label": "büyülü"},
    "A": {"color": "#6A4CA6", "label": "sıradışı"},
    "S": {"color": "#D9741F", "label": "mitik"},
}

DEFAULT_HANDLE = "@quest.post"
DEFAULT_TAGLINE = "oyun dünyasından her gün 3 yeni haber"
DEFAULT_FOLLOW = "yenilerini kaçırmamak için takipte kal"


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

    # Sayfa gostergesi: ilk sayfada kaydirma daveti, sonrakilerde sadece sira.
    # Tek sayfalik postta "1/1" - kaydirma daveti anlamsiz olurdu.
    if total <= 1:
        marker = "1/1"
    elif index == 1:
        marker = f"1/{total} · kaydır"
    else:
        marker = f"{index}/{total}"

    return {
        "tier_color": TIERS[tier]["color"],
        "tier_label": TIERS[tier]["label"],
        "category": spec.get("category", ""),
        "game": spec.get("game", ""),
        # Sizinti/datamine haberinde gorsel kullanilmaz, kredi de gerekmez.
        # Kredi once sayfanin kendisinden: seri yedeginden gelen gorselin
        # studyosu ana oyununkinden farkli olabiliyor (images.py yaziyor).
        "credit": (page.get("credit") or spec.get("credit")) if page["image"] else None,
        "handle": spec.get("handle", DEFAULT_HANDLE),
        "tagline": spec.get("tagline", DEFAULT_TAGLINE),
        "page": page,
        "index": index,
        "page_marker": marker,
        "follow": spec.get("follow", DEFAULT_FOLLOW),
    }


def render(spec: dict, out_dir: Path) -> list[dict]:
    pages = spec["pages"]
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=SCALE,
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
            # --out proje disinda bir yol olabilir, relative_to patlamasin.
            try:
                label = str(target.resolve().relative_to(ROOT))
            except ValueError:
                label = str(target)
            written.append({
                "file": label,
                "type": spec_page["type"],
                "scrim_start_pct": (metrics or {}).get("scrim_start_pct"),
                "scrim_solid_pct": (metrics or {}).get("scrim_solid_pct"),
                "content_height": (metrics or {}).get("content_height"),
            })

        browser.close()
    return written


SHEET_THUMB = "https://images.igdb.com/igdb/image/upload/t_screenshot_med/{id}.jpg"


def render_sheet(spec: dict, out_path: Path) -> int:
    """Havuzdaki tum gorselleri numaralandirilmis tek bir izgarada bas.

    Kullanicinin "/gorsel 4 7 2" diyebilmesi icin havuzu gormesi lazim.
    Kucuk onizlemeler dogrudan IGDB'den cekiliyor, indirilmiyor.
    """
    pool = spec.get("_image_pool") or []
    if not pool:
        print("havuz bos: bu postta gorsel yok (tipografik kart)")
        return 1

    tiles = []
    for number, entry in enumerate(pool, 1):
        tiles.append(f"""
        <div class="tile">
          <img src="{entry.get('thumb') or SHEET_THUMB.format(id=entry['id'])}">
          <div class="num">{number}</div>
          <div class="meta">{entry.get('kind', '')} · {entry.get('w', 0)}x{entry.get('h', 0)}</div>
        </div>""")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <link rel="stylesheet" href="{(ROOT / 'templates' / 'card.css').as_uri()}">
    <style>
      body {{ width: 1080px; background: #F1EDE3; padding: 40px; }}
      .head {{ font-family: "Bricolage Grotesque", sans-serif; font-weight: 800;
               font-size: 42px; color: #17151A; margin-bottom: 8px; }}
      .sub {{ font-family: "Outfit", sans-serif; font-size: 24px; color: #8A8378;
              margin-bottom: 28px; }}
      .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }}
      .tile {{ position: relative; }}
      .tile img {{ width: 100%; aspect-ratio: 16/9; object-fit: cover;
                   background: #CFC8B8; display: block; }}
      .num {{ position: absolute; top: 0; left: 0; background: #17151A; color: #F1EDE3;
              font-family: "Bricolage Grotesque", sans-serif; font-weight: 800;
              font-size: 30px; padding: 4px 16px; }}
      .meta {{ font-family: "Outfit", sans-serif; font-size: 19px; color: #8A8378;
               margin-top: 6px; }}
    </style></head><body>
      <div class="head">görsel havuzu</div>
      <div class="sub">{spec.get('game', '')} · {len(pool)} görsel ·
        beğendiklerini sayfa sırasına göre yaz: /gorsel 4 7 2</div>
      <div class="grid">{''.join(tiles)}</div>
    </body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": 800})
        page.set_content(html)
        page.evaluate("() => document.fonts.ready")
        # Onizlemeler agdan geliyor, hepsi inmeden fotograf cekilmemeli.
        try:
            page.wait_for_function(
                "() => Array.from(document.images).every(i => i.complete)", timeout=30000)
        except Exception:
            print("uyari: bazi onizlemeler yuklenemedi", file=sys.stderr)
        page.screenshot(path=str(out_path), full_page=True)
        browser.close()

    print(f"havuz sayfasi: {out_path} ({len(pool)} gorsel)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="quest.post kart uretici")
    ap.add_argument("spec", help="post tarifi (JSON)")
    ap.add_argument("--out", default=None, help="cikis klasoru (varsayilan: out/<dosya adi>)")
    ap.add_argument("--sheet", default=None,
                    help="kart yerine numarali gorsel havuzu bas, verilen yola yaz")
    args = ap.parse_args()

    if args.sheet:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        return render_sheet(spec, Path(args.sheet))

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

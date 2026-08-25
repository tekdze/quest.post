#!/usr/bin/env python3
"""IGDB'den oyun görselleri seçer ve post tarifine işler.

Faz 4 - IGDB_CLIENT_ID ve IGDB_CLIENT_SECRET gerekir.

Görsel seçimini KOD yapar, LLM değil. Sayfa tipine göre hangi görsel tipinin
kullanılacağı tasarım kararı, modele bırakılmaz.

Telif: görsel kredisi (`görsel: <stüdyo>`) LLM'in tahmininden değil IGDB'nin
şirket verisinden geliyor. Görselin sahibini görselle gelen veri bilir.

Kullanım:
    py -3.12 src/images.py state/draft.json
    py -3.12 src/images.py state/draft.json --dry-run   # indirmez, sadece secer
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "state" / "img"

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_URL = "https://api.igdb.com/v4"
IMAGE_URL = "https://images.igdb.com/igdb/image/upload/t_{size}/{image_id}.jpg"

# Sayfa tipi -> tercih sirasi. Tasarim karari, DEVIR bolum 3'ten geliyor.
PREFERENCE = {
    "cover": ("artwork", "cover", "screenshot"),
    "text": ("screenshot", "artwork", "cover"),
    "numbers": ("screenshot", "artwork", "cover"),
    "outro": ("artwork", "screenshot", "cover"),
}

# Isim benzerligi bu esigin altindaysa "bulamadim" denir. Yanlis oyunun
# gorselini basmak, gorselsiz basmaktan cok daha kotu.
NAME_MATCH_MIN = 0.55
# Arama sonucunda bu kadar gorseli olmayan kaydi ciddiye almiyoruz.
MIN_IMAGES = 2


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def credentials() -> tuple[str, str]:
    load_env()
    cid = os.environ.get("IGDB_CLIENT_ID", "").strip()
    secret = os.environ.get("IGDB_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        sys.exit(".env icinde IGDB_CLIENT_ID ve IGDB_CLIENT_SECRET dolu olmali")
    return cid, secret


def get_token(cid: str, secret: str) -> str:
    """Twitch uygulama jetonu. Her calismada yeniden alinir - tek istek,
    onbellek tutmaya deger degil, ve suresi dolmus jeton derdi kalmiyor."""
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": secret, "grant_type": "client_credentials",
    }).encode()
    request = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())["access_token"]
    except urllib.error.HTTPError as exc:
        sys.exit(f"Twitch jeton hatasi {exc.code}: {exc.read().decode('utf-8','replace')[:200]}")


def igdb_query(cid: str, token: str, endpoint: str, query: str) -> list[dict]:
    request = urllib.request.Request(
        f"{IGDB_URL}/{endpoint}", data=query.encode("utf-8"), method="POST",
        headers={"Client-ID": cid, "Authorization": f"Bearer {token}",
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"IGDB hatasi {exc.code}: {exc.read().decode('utf-8','replace')[:300]}")


# ------------------------------------------------------------------ secim

def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", name.lower()).strip()


def name_score(wanted: str, found: str) -> float:
    return difflib.SequenceMatcher(None, normalize(wanted), normalize(found)).ratio()


# Roma rakamlari da surum numarasi sayilir: "witcher iv" ile "witcher 3"
# birbirine karismasin.
ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7"}


def version_tokens(name: str) -> set[str]:
    """Isimdeki surum isaretleri: sayilar ve roma rakamlari."""
    words = normalize(name).split()
    found = {w for w in words if w.isdigit()}
    found |= {ROMAN[w] for w in words if w in ROMAN}
    return found


def version_conflict(wanted: str, found: str) -> bool:
    """Aranan surum numarasi belirtmisse, eslesme baska bir surum olamaz.

    Bu kural olmadan "the witcher 3" aramasi 2007'nin "The Witcher"ina
    veya "The Witcher IV"e dusuyordu - yanlis oyunun gorselleri basiliyordu.
    """
    a, b = version_tokens(wanted), version_tokens(found)
    if not a:
        return False
    return not (a & b)


def image_pool(game: dict) -> dict[str, list[str]]:
    """IGDB kaydindan gorselleri tipe gore ayir."""
    pool = {
        "artwork": [a["image_id"] for a in game.get("artworks", []) if a.get("image_id")],
        "screenshot": [s["image_id"] for s in game.get("screenshots", []) if s.get("image_id")],
        "cover": [game["cover"]["image_id"]] if game.get("cover", {}).get("image_id") else [],
    }
    return pool


def developer_of(game: dict) -> str | None:
    """Gorsel kredisi icin studyo. Once gelistirici, yoksa yayinci."""
    involved = game.get("involved_companies") or []
    for want_developer in (True, False):
        for entry in involved:
            company = (entry.get("company") or {}).get("name")
            if company and bool(entry.get("developer")) == want_developer:
                return company.lower()
    return None


def find_game(cid: str, token: str, name: str) -> tuple[dict | None, float, list[tuple[str, float, int]]]:
    """Oyunu ara, en iyi eslesmeyi dondur. Aday listesini de dondurur (rapor icin)."""
    safe = name.replace('"', " ").strip()
    if not safe:
        return None, 0.0, []
    results = igdb_query(cid, token, "games",
                         f'search "{safe}"; '
                         'fields name,cover.image_id,artworks.image_id,screenshots.image_id,'
                         'involved_companies.developer,involved_companies.company.name; '
                         'limit 8;')

    scored = []
    for game in results:
        pool = image_pool(game)
        total = sum(len(v) for v in pool.values())
        found_name = game.get("name", "")
        score = name_score(name, found_name)
        if version_conflict(name, found_name):
            score -= 0.5  # ayni seri, yanlis oyun
        scored.append((game, score, total))

    # Isim benzerligi once, esitlikte gorsel sayisi. "Elvies" gibi bos
    # kayitlar boylece elenir.
    scored.sort(key=lambda row: (-row[1], -row[2]))
    report = [(g.get("name", "?"), round(s, 2), n) for g, s, n in scored]

    for game, score, total in scored:
        if score >= NAME_MATCH_MIN and total >= MIN_IMAGES:
            return game, score, report
    return None, scored[0][1] if scored else 0.0, report


def assign_images(pages: list[dict], pool: dict[str, list[str]]) -> list[str | None]:
    """Her sayfaya farkli bir gorsel ata. Hepsi ayni oyundan, tekrar en son."""
    used: set[str] = set()
    chosen: list[str | None] = []

    for page in pages:
        pick = None
        for kind in PREFERENCE.get(page["type"], ("screenshot", "artwork", "cover")):
            available = [i for i in pool.get(kind, []) if i not in used]
            if available:
                pick = available[0]
                break
        if pick is None:
            # Gorsel tukendi: bastan dolas, tekrar kullanmak gorselsiz
            # kalmaktan iyidir.
            everything = [i for kind in PREFERENCE[page["type"]] for i in pool.get(kind, [])]
            pick = everything[len(chosen) % len(everything)] if everything else None
        if pick:
            used.add(pick)
        chosen.append(pick)
    return chosen


# ---------------------------------------------------------------- indirme

def download(image_id: str, target: Path, size: str = "1080p") -> bool:
    url = IMAGE_URL.format(size=size, image_id=image_id)
    request = urllib.request.Request(url, headers={"User-Agent": "questpost/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        print(f"  gorsel indirilemedi ({exc.code}): {image_id}", file=sys.stderr)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return True


# ------------------------------------------------------------------- akis

def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post gorsel secici (Faz 4)")
    ap.add_argument("draft", help="write.py'nin urettigi tarif (JSON)")
    ap.add_argument("--dry-run", action="store_true", help="indirme yapma, sadece sec")
    ap.add_argument("--game", default=None, help="arama adini elle ez")
    args = ap.parse_args()

    draft_path = Path(args.draft)
    spec = json.loads(draft_path.read_text(encoding="utf-8"))

    # Sizinti haberinde gorsel KULLANILMAZ. Telif kurali, tartisilmaz.
    if spec.get("_is_leak"):
        for page in spec["pages"]:
            page["image"] = None
        spec["credit"] = None
        draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print("sizinti haberi: gorsel kullanilmadi, kartlar tipografik olacak")
        return 0

    cid, secret = credentials()
    token = get_token(cid, secret)
    # Arama icin search_name kullaniliyor: "game" alani karta basilan
    # Turkce/kucuk harf gorunum adi, IGDB'de aranamaz.
    wanted = args.game or spec.get("search_name") or spec.get("game", "")
    if not wanted or str(wanted).lower() == "none":
        for page in spec["pages"]:
            page["image"] = None
        spec["credit"] = None
        draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print("search_name bos: haber bir oyun hakkinda degil, kartlar tipografik olacak")
        return 0

    game, score, report = find_game(cid, token, wanted)

    print(f'arama: "{wanted}"')
    for name, s, n in report[:5]:
        print(f"  {s:.2f} benzerlik | {n:2} gorsel | {name}")

    if game is None:
        # Eslesme yok: haber bir oyun hakkinda olmayabilir (etkinlik, sirket,
        # sektor haberi). Yanlis gorsel basmaktan iyisi gorselsiz basmak.
        for page in spec["pages"]:
            page["image"] = None
        spec["credit"] = None
        draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\neslesme yok (en iyi benzerlik {score:.2f} < {NAME_MATCH_MIN}). "
              "kartlar tipografik olacak.")
        return 0

    pool = image_pool(game)
    print(f'\nsecilen: {game["name"]} (benzerlik {score:.2f})')
    print(f'  artwork {len(pool["artwork"])} | screenshot {len(pool["screenshot"])} '
          f'| cover {len(pool["cover"])}')

    studio = developer_of(game)
    spec["credit"] = studio
    print(f"  kredi: {studio or 'bilinmiyor'}")

    picks = assign_images(spec["pages"], pool)
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(game["name"])).strip("-") or "post"

    print()
    for index, (page, image_id) in enumerate(zip(spec["pages"], picks), 1):
        if not image_id:
            page["image"] = None
            print(f"  {index}. {page['type']:8} gorsel yok")
            continue
        rel = f"state/img/{slug}-{image_id}.jpg"
        if args.dry_run:
            page["image"] = rel
            print(f"  {index}. {page['type']:8} {image_id} (indirilmedi)")
            continue
        target = ROOT / rel
        if target.exists() or download(image_id, target):
            page["image"] = rel
            print(f"  {index}. {page['type']:8} {image_id}")
        else:
            page["image"] = None
            print(f"  {index}. {page['type']:8} indirilemedi, gorselsiz")

    draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ntarif guncellendi -> {draft_path}")
    print(f"kartlari basmak icin:\n  py -3.12 src/render.py {draft_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

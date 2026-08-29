#!/usr/bin/env python3
"""IGDB'den oyun görselleri seçer ve post tarifine işler.

Faz 4 - IGDB_CLIENT_ID ve IGDB_CLIENT_SECRET gerekir.

Görsel seçimini KOD yapar, LLM değil. Sayfa tipine göre hangi görsel tipinin
kullanılacağı tasarım kararı, modele bırakılmaz.

Telif: görsel kredisi (kartta `@<stüdyo>`) LLM'in tahmininden değil IGDB'nin
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

# Kart 1080x1350 (yogunlukla 1440x1800) basiliyor ve gorsel "cover" ile
# kirpiliyor: 16:9 bir kaynagin 1350 yuksekligi doldurmasi icin ~2400px
# genislik gerekiyor. Bu esigin altindaki gorsel buyutulur ve bulanik cikar.
# Olcum (2026-08-27, Witcher 3): ayni oyunun gorselleri 600x338 ile
# 10681x7874 arasinda degisiyor - filtre olmadan sans isi.
MIN_IMAGE_WIDTH = 1280
MIN_IMAGE_HEIGHT = 720


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


def usable(entry: dict) -> bool:
    """Karta basilacak kadar buyuk mu?

    Boyut bilgisi gelmeyen kayitlari eliyoruz: bilinmeyen boyut riskli,
    bulanik kart basmaktansa o gorseli hic kullanmamak iyi.
    """
    width, height = entry.get("width") or 0, entry.get("height") or 0
    return width >= MIN_IMAGE_WIDTH and height >= MIN_IMAGE_HEIGHT


def image_pool(game: dict, filtered: bool = True) -> dict[str, list[dict]]:
    """IGDB kaydindan gorselleri tipe gore ayir, kucukleri ele, buyugu one al.

    Kapak gorseli boyut filtresinden muaf: IGDB kapaklari zaten kucuk
    (dikey poster) ve sadece son care olarak kullaniliyor.
    """
    def topla(entries, kind: str, boyut_filtresi: bool) -> list[dict]:
        rows = [
            {"id": e["image_id"], "kind": kind,
             "w": e.get("width") or 0, "h": e.get("height") or 0}
            for e in entries or [] if e.get("image_id")
        ]
        if boyut_filtresi and filtered:
            rows = [r for r in rows if usable({"width": r["w"], "height": r["h"]})]
        # Buyukten kucuge: en keskin gorsel kapaga gitsin.
        rows.sort(key=lambda r: -(r["w"] * r["h"]))
        return rows

    cover = game.get("cover") or {}
    return {
        "artwork": topla(game.get("artworks"), "artwork", True),
        "screenshot": topla(game.get("screenshots"), "screenshot", True),
        "cover": topla([cover] if cover.get("image_id") else [], "cover", False),
    }


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
                         'fields name,'
                         'cover.image_id,cover.width,cover.height,'
                         'artworks.image_id,artworks.width,artworks.height,'
                         'screenshots.image_id,screenshots.width,screenshots.height,'
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


def assign_images(pages: list[dict], pool: dict[str, list[dict]],
                  rotate: int = 0) -> list[str | None]:
    """Her sayfaya farkli bir gorsel ata. Hepsi ayni oyundan, tekrar en son.

    `rotate` her tipin listesini kaydiriyor: kullanici "/gorsel" yazip
    "bunlari begenmedim" dediginde ayni havuzdan baska bir set cikiyor.
    """
    used: set[str] = set()
    chosen: list[str | None] = []
    donmus = {kind: rows[rotate % len(rows):] + rows[:rotate % len(rows)] if rows else []
              for kind, rows in pool.items()}

    for page in pages:
        pick = None
        for kind in PREFERENCE.get(page["type"], ("screenshot", "artwork", "cover")):
            available = [r["id"] for r in donmus.get(kind, []) if r["id"] not in used]
            if available:
                pick = available[0]
                break
        if pick is None:
            # Gorsel tukendi: bastan dolas, tekrar kullanmak gorselsiz
            # kalmaktan iyidir.
            everything = [r["id"] for kind in PREFERENCE[page["type"]]
                          for r in pool.get(kind, [])]
            pick = everything[len(chosen) % len(everything)] if everything else None
        if pick:
            used.add(pick)
        chosen.append(pick)
    return chosen


# ---------------------------------------------------------------- indirme

def download(image_id: str, target: Path) -> bool:
    """Gorseli indir. Once t_original: IGDB'de 4K bir artwork varken
    t_1080p istemek onu 1920x1080'e dusuruyordu, sonra biz 1350 yukseklige
    buyutunce bulanik cikiyordu. Original yoksa 1080p'ye duser."""
    for size in ("original", "1080p"):
        url = IMAGE_URL.format(size=size, image_id=image_id)
        request = urllib.request.Request(url, headers={"User-Agent": "questpost/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            if size == "original":
                continue
            print(f"  gorsel indirilemedi ({exc.code}): {image_id}", file=sys.stderr)
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return True
    return False


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
    ap.add_argument("--pick", nargs="*", default=None,
                    help="sayfa sayfa havuz sirasi, ornek: --pick 1 3 5")
    ap.add_argument("--rotate", type=int, default=0,
                    help="havuzu kaydir: ayni oyundan baska bir set")
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
    ham = image_pool(game, filtered=False)
    elenen = (len(ham["artwork"]) + len(ham["screenshot"])
              - len(pool["artwork"]) - len(pool["screenshot"]))
    print(f'  artwork {len(pool["artwork"])} | screenshot {len(pool["screenshot"])} '
          f'| cover {len(pool["cover"])}')
    if elenen:
        print(f"  {elenen} gorsel cozunurluk yetersizliginden elendi "
              f"(<{MIN_IMAGE_WIDTH}x{MIN_IMAGE_HEIGHT})")
    en_iyi = (pool["artwork"] + pool["screenshot"])[:1]
    if en_iyi:
        print(f'  en buyuk: {en_iyi[0]["w"]}x{en_iyi[0]["h"]}')

    studio = developer_of(game)
    spec["credit"] = studio
    print(f"  kredi: {studio or 'bilinmiyor'}")

    # Havuzu tarife yaz: /gorsel komutu alternatifleri buradan secer.
    # Sira sabit tutulur ki kullanicinin gordugu "3. gorsel" hep ayni olsun.
    duz_havuz = pool["artwork"] + pool["screenshot"] + pool["cover"]
    spec["_image_pool"] = duz_havuz
    spec["_slug"] = re.sub(r"[^a-z0-9]+", "-", normalize(game["name"])).strip("-") or "post"

    # "/gorsel" argumansiz gelince tur sayaci artiyor ve ayni havuzdan
    # baska bir set cikiyor. Kullanici numara ezberlemek zorunda kalmasin.
    rotate = int(spec.get("_gorsel_turu", 0) or 0) + (args.rotate or 0)
    spec["_gorsel_turu"] = rotate

    elle = spec.pop("_gorsel_secimi", None) or args.pick
    if elle:
        # Kullanici sayfa sayfa havuz sirasi verdi: "1 3 5" -> 1. sayfaya
        # havuzun 1., 2. sayfaya 3., 3. sayfaya 5. gorseli.
        picks = []
        for sira, page in enumerate(spec["pages"]):
            if sira < len(elle):
                try:
                    picks.append(duz_havuz[int(elle[sira]) - 1]["id"])
                    continue
                except (ValueError, IndexError):
                    print(f"  uyari: gecersiz gorsel numarasi {elle[sira]!r}, "
                          f"otomatik secim kullanilacak")
            picks.append(None)
        otomatik = assign_images(spec["pages"], pool, rotate)
        picks = [p or otomatik[i] for i, p in enumerate(picks)]
        print(f"  elle secim uygulandi: {' '.join(str(x) for x in elle)}")
    else:
        picks = assign_images(spec["pages"], pool, rotate)

    slug = spec["_slug"]

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

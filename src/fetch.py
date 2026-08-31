#!/usr/bin/env python3
"""RSS kaynaklarini tara, tekrarlari at, aday haber kumeleri uret.

Hicbir API anahtari gerekmez.

Botun asil isi yazmak degil filtrelemek: 40 haberden 2'sini secmek.
Bu dosya o 40 haberi toplayip ayni haberi yazan kaynaklari tek kumede
birlestirir. "Kac kaynak yazmis" sinyali tier.py'in girdisi olacak.

Kullanim:
    py -3.12 src/fetch.py --print
    py -3.12 src/fetch.py --max-age-hours 24 --limit 15
"""

from __future__ import annotations

import argparse
import calendar
import collections
import concurrent.futures as cf
import hashlib
import html
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import feedparser
except ImportError:
    sys.exit("feedparser kurulu degil. Once: py -3.12 -m pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "src" / "feeds.json"
POSTED_FILE = ROOT / "state" / "posted.json"
OUT_FILE = ROOT / "state" / "candidates.json"

# Baslik benzerligi bu esigin uzerindeyse ayni haber sayilir.
# Benzerlik IDF agirlikli: "games", "new", "release" gibi her baslikta gecen
# kelimeler az, "terranigma" veya "w4" gibi nadir kelimeler cok deger tasir.
CLUSTER_THRESHOLD = 0.30
MIN_SHARED_TOKENS = 2
# Paylasilan kelimelerin toplam IDF agirligi. Oran tek basina yeterli degil:
# iki kelimelik iki baslik da %100 benzer cikar. Kutle "yeterince kanit var mi"
# sorusunu sorar.
MIN_SHARED_IDF = 3.0
# Ozel isim koprusu: iki baslik nadir bir kelimeyi paylasiyorsa (ayni oyun,
# ayni studyo) ayni haber olma sansi yuksektir, oran esigi dusurulur.
# Not: df havuzun kendisinden hesaplanir, yani cok kaynagin yazdigi buyuk
# haberin anahtar kelimesi "nadir" olmaktan cikar - o yuzden bu bir kopru,
# zorunluluk degil.
BRIDGE_DF = 2
BRIDGE_THRESHOLD = 0.15

# Kume siralamasinda kullanilan agirliklar. Bunlar tier DEGILDIR -
# tier'i tier.py hesaplar. Burasi sadece "hangisine once bakilsin".
SOURCE_COUNT_WEIGHT = 3.0
KIND_BONUS = {"releases": 0.6, "devlog": 0.6, "news": 0.0, "community": -0.2}

STOPWORDS = {
    # tr
    "ve", "ile", "icin", "bir", "bu", "da", "de", "mi", "ne", "cok", "gibi",
    "olarak", "sonra", "once", "kadar", "ama", "veya", "her", "tum", "yeni",
    "oldu", "oluyor", "olacak", "var", "yok", "geldi", "geliyor", "gelecek",
    "aciklandi", "duyuruldu", "iste", "peki", "sey", "kez", "yil", "gun",
    # en
    "the", "and", "for", "are", "was", "were", "been", "with", "its",
    "this", "that", "has", "have", "had", "will", "now", "new", "out",
    "you", "your", "all", "but", "not", "can", "get", "gets", "got", "into",
    "more", "about", "after", "before", "than", "then", "just",
}

TR_FOLD = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s",
    "ğ": "g", "Ğ": "g", "ü": "u", "Ü": "u",
    "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    "â": "a", "î": "i",
})

TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src")


# ---------------------------------------------------------------- yardimcilar

def fold(text: str) -> str:
    """Turkce karakterleri sadelestir, kucult."""
    return text.translate(TR_FOLD).lower()


def strip_html(raw: str) -> str:
    raw = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw or "", flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def canonical_url(url: str) -> str:
    """Takip parametrelerini at, ayni haberin iki farkli linki tek olsun."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = [
        (k, v) for k, v in urllib.parse.parse_qsl(parts.query)
        if not any(k.lower().startswith(p) for p in TRACKING_PARAMS)
    ]
    path = parts.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((
        parts.scheme.lower(), parts.netloc.lower(), path,
        urllib.parse.urlencode(query), "",
    ))


def url_hash(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


def clean_title(title: str, feed_name: str) -> str:
    """Baslik sonundaki site adi kuyrugunu atar (ornek: ... - Webtekno)."""
    title = strip_html(title)
    feed_tokens = {fold(t) for t in re.findall(r"\w+", feed_name) if len(t) > 2}
    for sep in (" | ", " - ", " — ", " – ", " :: "):
        head, found, tail = title.rpartition(sep)
        if found and head and len(tail.split()) <= 4:
            tail_tokens = {fold(t) for t in re.findall(r"\w+", tail)}
            if tail_tokens & feed_tokens:
                title = head.strip()
    return title


def tokens_of(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", fold(title))
    return {w for w in words if len(w) >= 3 and w not in STOPWORDS}


def build_idf(items: list[dict]) -> tuple[dict[str, float], collections.Counter]:
    """Kelime nadirlik tablosu. Havuzun kendisinden ogrenilir, sabit liste yok."""
    df: collections.Counter = collections.Counter()
    for item in items:
        df.update(item["_tokens"])
    total = max(len(items), 1)
    idf = {token: math.log(total / count) + 1.0 for token, count in df.items()}
    return idf, df


def similarity(a: set[str], b: set[str], idf: dict[str, float]) -> tuple[float, int, float]:
    """IDF agirlikli Jaccard. Nadir kelime paylasmak cok, sik kelime az deger.

    Doner: (oran, paylasilan kelime sayisi, paylasilan IDF kutlesi)
    """
    if not a or not b:
        return 0.0, 0, 0.0
    shared = a & b
    if not shared:
        return 0.0, 0, 0.0
    mass = sum(idf.get(t, 1.0) for t in shared)
    denominator = sum(idf.get(t, 1.0) for t in a | b)
    return mass / denominator, len(shared), mass


def same_story(a: set[str], b: set[str], idf: dict[str, float],
               df: collections.Counter) -> tuple[bool, float]:
    """Iki baslik ayni haberi mi anlatiyor?"""
    ratio, shared_count, mass = similarity(a, b, idf)
    if shared_count < MIN_SHARED_TOKENS or mass < MIN_SHARED_IDF:
        return False, ratio
    has_bridge = any(df[t] <= BRIDGE_DF for t in a & b)
    threshold = BRIDGE_THRESHOLD if has_bridge else CLUSTER_THRESHOLD
    return ratio >= threshold, ratio


def parse_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    return None


# --------------------------------------------------------------------- cekme

def fetch_feed(feed: dict, defaults: dict) -> dict:
    """Tek bir beslemeyi cek. Hata firlatmaz, durumu sozlukte dondurur."""
    request = urllib.request.Request(feed["url"], headers={
        "User-Agent": defaults["user_agent"],
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "tr,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(request, timeout=defaults["timeout_seconds"]) as response:
            raw = response.read()
    except Exception as exc:  # aglayan besleme tum calismayi dusurmemeli
        return {"feed": feed, "entries": [], "error": f"{type(exc).__name__}: {exc}"}

    parsed = feedparser.parse(raw)
    if not parsed.entries:
        note = getattr(parsed, "bozo_exception", None)
        return {"feed": feed, "entries": [], "error": f"icerik yok ({note})" if note else "icerik yok"}
    return {"feed": feed, "entries": parsed.entries, "error": None}


def passes_topic_filter(feed: dict, title: str, keywords: list[str]) -> bool:
    """Genel besleme icin konu filtresi. Sadece BASLIGA bakar.

    Ozet metnine bakmak filtreyi ise yaramaz hale getiriyor: neredeyse her
    ozette bir yerde "game" kelimesi geciyor.
    """
    if feed.get("topic_filter") != "gaming":
        return True
    words = set(re.findall(r"[a-z0-9]+", fold(title)))
    return any(
        (k in words) if " " not in k else (fold(k) in fold(title))
        for k in (fold(x) for x in keywords)
    )


def entry_image(entry) -> str | None:
    """Haberin kendi görseli. Kartta kullanılacak en ilgili kare.

    Bir editör o kareyi O HABER için seçmiş: konuyla ilgisi garanti,
    oysa mağaza karesi pazarlama fotoğrafı ve olayla bağı tesadüf.
    Ölçüm (2026-08-31): İngilizce haber kaynaklarının 10/10'u RSS'te
    görsel veriyor, 4'ü karta basılacak çözünürlükte (boyut denetimi
    images.py tarafında).
    """
    for alan in ("media_content", "media_thumbnail"):
        for row in entry.get(alan) or []:
            url = row.get("url")
            if url:
                return url
    for link in entry.get("links") or []:
        if "image" in (link.get("type") or "") and link.get("href"):
            return link["href"]
    return None


def normalize(entry, feed: dict, keywords: list[str], now: datetime, max_age: timedelta):
    link = entry.get("link") or ""
    title = clean_title(entry.get("title") or "", feed["name"])
    if not link or not title:
        return None

    summary = strip_html(entry.get("summary") or entry.get("description") or "")[:600]
    if not passes_topic_filter(feed, title, keywords):
        return None

    published = parse_date(entry)
    # Tarihsiz kayit varsayilan olarak simdi kabul edilir; bazi akislarda
    # tarih bos gelir, haberi tamamen kaybetmemek icin pencerede tutulur.
    age_hours = (now - published).total_seconds() / 3600 if published else 0.0
    if published and (now - published) > max_age:
        return None
    if age_hours < -6:  # gelecek tarihli kayit = kaynagin saati bozuk, guvenme
        return None

    return {
        "hash": url_hash(link),
        "url": canonical_url(link),
        "title": title,
        "summary": summary,
        "published": published.isoformat() if published else None,
        "age_hours": round(max(age_hours, 0.0), 1),
        "image": entry_image(entry),
        "source_id": feed["id"],
        "source_name": feed["name"],
        "lang": feed["lang"],
        "kind": feed["kind"],
        "bucket": feed.get("bucket", "news"),
        "weight": feed["weight"],
        "tags": feed.get("tags", []),
        "_tokens": tokens_of(title),
    }


# ------------------------------------------------------------------ kumeleme

def cluster_items(items: list[dict]) -> list[dict]:
    """Ayni haberi yazan kaynaklari tek kumede birlestir.

    Basit ama isini yapan yontem: baslik kelime kumeleri arasi Jaccard.
    Bilinen sinir: TR ve EN basliklar birbiriyle eslesmez, yani ayni haberi
    hem TR hem EN kaynak yazdiysa iki ayri kume cikar. tier.py bunu bilerek
    okumali.
    """
    idf, df = build_idf(items)
    clusters: list[dict] = []
    # Once en yenisi: kumenin temsilcisi en guncel haber olsun.
    for item in sorted(items, key=lambda i: i["age_hours"]):
        best, best_score = None, 0.0
        for cluster in clusters:
            merge, score = same_story(item["_tokens"], cluster["_tokens"], idf, df)
            if merge and score > best_score:
                best, best_score = cluster, score
        if best is None:
            clusters.append({"_tokens": set(item["_tokens"]), "members": [item]})
        else:
            best["members"].append(item)
            best["_tokens"] |= item["_tokens"]
    return clusters


def summarize_cluster(cluster: dict, max_age_hours: int) -> dict:
    members = sorted(cluster["members"], key=lambda m: (m["age_hours"], -m["weight"]))
    # Kumenin temsilcisi haber kaynagi olsun; kesif kaynagi ancak baska yoksa.
    lead = next((m for m in members if m["bucket"] == "news"), members[0])
    bucket = "news" if any(m["bucket"] == "news" for m in members) else "discovery"
    sources = sorted({m["source_id"] for m in members})
    max_weight = max(m["weight"] for m in members)
    kind_bonus = max(KIND_BONUS.get(m["kind"], 0.0) for m in members)
    recency = max(0.0, 1.0 - lead["age_hours"] / max(max_age_hours, 1))
    indie_bonus = 0.4 if any("indie" in m["tags"] for m in members) else 0.0

    score = (
        SOURCE_COUNT_WEIGHT * (len(sources) - 1)
        + max_weight + kind_bonus + indie_bonus + recency
    )
    return {
        "key": lead["hash"],
        "title": lead["title"],
        "url": lead["url"],
        "summary": lead["summary"],
        "published": lead["published"],
        "age_hours": lead["age_hours"],
        "lang": lead["lang"],
        "kind": lead["kind"],
        "bucket": bucket,
        "tags": lead["tags"],
        "source_count": len(sources),
        "sources": sources,
        "rank_score": round(score, 2),
        "members": [
            {k: v for k, v in m.items() if not k.startswith("_")} for m in members
        ],
    }


# ---------------------------------------------------------------------- akis

def load_posted() -> set[str]:
    if not POSTED_FILE.exists():
        return set()
    try:
        data = json.loads(POSTED_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("uyari: state/posted.json okunamadi, tekrar filtresi bu turda pasif", file=sys.stderr)
        return set()
    return {row["hash"] for row in data.get("posted", []) if "hash" in row}


def main() -> int:
    # Windows konsolu cp1254 ile aciliyor, Turkce baslik basarken patliyor.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post haber toplayici")
    ap.add_argument("--max-age-hours", type=int, default=None)
    ap.add_argument("--limit", type=int, default=40, help="kaydedilecek aday kumesi sayisi")
    ap.add_argument("--print", action="store_true", dest="do_print", help="ozeti ekrana bas")
    ap.add_argument("--out", default=str(OUT_FILE))
    args = ap.parse_args()

    config = json.loads(FEEDS_FILE.read_text(encoding="utf-8"))
    defaults = config["defaults"]
    keywords = config["gaming_keywords"]
    feeds = [f for f in config["feeds"] if f.get("enabled", True)]
    max_age_hours = args.max_age_hours or defaults["max_age_hours"]
    max_age = timedelta(hours=max_age_hours)
    now = datetime.now(timezone.utc)

    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda f: fetch_feed(f, defaults), feeds))

    health, items, raw_count = [], [], 0
    skipped_posted = 0
    posted = load_posted()

    for result in results:
        feed = result["feed"]
        kept = []
        for entry in result["entries"]:
            raw_count += 1
            normalized = normalize(entry, feed, keywords, now, max_age)
            if normalized:
                kept.append(normalized)
        # Kaynak basina tavan: itch.io gibi akislar gunde yuzlerce kayit
        # dokuyor, tavan olmazsa tek kaynak butun listeyi yutar.
        kept.sort(key=lambda k: k["age_hours"])
        kept = kept[: feed.get("max_items", 40)]
        items.extend(kept)
        health.append({
            "id": feed["id"],
            "ok": result["error"] is None,
            "entries": len(result["entries"]),
            "kept": len(kept),
            "error": result["error"],
            "newest_age_hours": min((k["age_hours"] for k in kept), default=None),
        })

    # Ayni linki iki kaynak verdiyse tek tut, yayinlanmislari tamamen cikar.
    by_hash: dict[str, dict] = {}
    for item in items:
        if item["hash"] in posted:
            skipped_posted += 1
            continue
        current = by_hash.get(item["hash"])
        if current is None or item["weight"] > current["weight"]:
            by_hash[item["hash"]] = item
    unique = list(by_hash.values())

    clusters = cluster_items(unique)
    summaries = sorted(
        (summarize_cluster(c, max_age_hours) for c in clusters),
        key=lambda c: -c["rank_score"],
    )
    candidates = [c for c in summaries if c["bucket"] == "news"][: args.limit]

    # REDDIT ILGI SINYALI. Kaynak sayisi yaygınlığı olcuyor, ilgincligi
    # degil; reddit oyu o eksigi kapatan tek olcu (bkz. reddit.py).
    # Anahtar yoksa ya da reddit erisilemezse SESSIZCE atlaniyor: sinyal
    # bir iyilestirme, bagimlilik degil - fetch hicbir kosulda bunun
    # yuzunden dusmemeli, yoksa gunun butun postu gider.
    try:
        import reddit as reddit_mod
        if reddit_mod.kimlik() is not None:
            gonderiler = reddit_mod.sicak_gonderiler()
            reddit_mod.isi_ekle(candidates, gonderiler)
            eslesen = sum(1 for c in candidates if c.get("reddit_oy"))
            print(f"reddit: {len(gonderiler)} gonderi tarandi, "
                  f"{eslesen} aday eslesti")
    except Exception as exc:                       # noqa: BLE001
        print(f"reddit sinyali atlandi: {exc}", file=sys.stderr)
    discovery = [c for c in summaries if c["bucket"] == "discovery"][: args.limit]

    payload = {
        "generated_at": now.isoformat(),
        "window_hours": max_age_hours,
        "stats": {
            "feeds": len(feeds),
            "feeds_ok": sum(1 for h in health if h["ok"]),
            "entries_seen": raw_count,
            "in_window": len(items),
            "already_posted_skipped": skipped_posted,
            "unique": len(unique),
            "clusters": len(clusters),
            "multi_source_clusters": sum(1 for c in summaries if c["source_count"] > 1),
        },
        "feed_health": health,
        "candidates": candidates,
        "discovery": discovery,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.do_print:
        print_report(payload)
    else:
        s = payload["stats"]
        print(f"{s['entries_seen']} kayit -> {s['in_window']} pencerede -> "
              f"{s['clusters']} kume. yazildi: {out_path}")
    return 0


def print_report(payload: dict) -> None:
    s = payload["stats"]
    print(f"\n=== kaynak durumu ({s['feeds_ok']}/{s['feeds']} calisiyor) ===")
    for h in sorted(payload["feed_health"], key=lambda h: (h["ok"], -h["kept"])):
        mark = "ok " if h["ok"] else "OLU"
        age = f"{h['newest_age_hours']:.0f}sa" if h["newest_age_hours"] is not None else "-"
        note = f"  {h['error']}" if h["error"] else ""
        print(f"  {mark} {h['id']:20} kayit={h['entries']:3} pencerede={h['kept']:3} en_yeni={age:>5}{note}")

    print(f"\n=== {s['entries_seen']} kayit -> {s['in_window']} pencerede "
          f"-> {s['unique']} tekil -> {s['clusters']} kume "
          f"({s['multi_source_clusters']} tanesi cok kaynakli) ===")

    for baslik, anahtar, adet in (("HABER ADAYLARI", "candidates", 25),
                                  ("KESIF HAVUZU", "discovery", 8)):
        rows = payload.get(anahtar, [])[:adet]
        print(f"\n--- {baslik} ({len(payload.get(anahtar, []))} kume) ---")
        print(f"{'#':>3} {'skor':>5} {'kyn':>3} {'yas':>5}  baslik")
        for i, c in enumerate(rows, 1):
            flag = "*" if c["source_count"] > 1 else " "
            print(f"{i:>3} {c['rank_score']:>5} {c['source_count']:>3}{flag}{c['age_hours']:>5.0f}  "
                  f"{c['title'][:80]}")
            if c["source_count"] > 1:
                print(f"{'':>19} yazanlar: {', '.join(c['sources'])}")


if __name__ == "__main__":
    raise SystemExit(main())

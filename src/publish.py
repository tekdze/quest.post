#!/usr/bin/env python3
"""Kartları Instagram'a carousel gönderi olarak yayınlar. Faz 6.

IG_ACCESS_TOKEN ve IG_USER_ID gerekir.

Instagram dosya YÜKLETMİYOR: her görsel için herkese açık bir URL istiyor.
Bu yüzden kartlar repoya commit ediliyor ve raw.githubusercontent.com
adresi veriliyor. Üretim ve yayınlama ayrı Actions çalışmaları olduğu için
kartlar `/ok` denildiğinde çoktan push edilmiş oluyor.

Yayınlama üç adım (Meta'nın dayattığı sıra):
  1. Her kart için "container" oluştur (is_carousel_item)
  2. Container'ların FINISHED olmasını bekle - Instagram görseli kendi
     indiriyor, hemen publish edilirse hata veriyor
  3. Carousel container oluştur, sonra publish et

Kullanım:
    py -3.12 src/publish.py state/drafts/x.json --cards out/x
    py -3.12 src/publish.py state/drafts/x.json --cards out/x --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Surum SABIT: Meta eski surumleri kapatinca bot sessizce degil, acik bir
# hatayla dursun. "en son surum" gibi takma ad kullanilmiyor.
API_BASE = "https://graph.instagram.com/v23.0"

# Instagram carousel siniri: 2-10 gorsel. Tek kartlik post carousel olamaz,
# tek gorsel olarak gonderiliyor.
CAROUSEL_MIN = 2
CAROUSEL_MAX = 10

# Container hazir olma beklemesi. Instagram gorseli kendisi indiriyor;
# buyuk PNG'lerde birkac saniye suruyor.
STATUS_TRIES = 20
STATUS_WAIT = 3


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
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    user_id = os.environ.get("IG_USER_ID", "").strip()
    if not token or not user_id:
        sys.exit("IG_ACCESS_TOKEN ve IG_USER_ID gerekli (Secrets veya .env)")
    return token, user_id


def call(path: str, params: dict, method: str = "POST") -> dict:
    token, _ = credentials()
    params = {**params, "access_token": token}
    if method == "GET":
        url = f"{API_BASE}/{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, method="GET")
    else:
        url = f"{API_BASE}/{path}"
        request = urllib.request.Request(
            url, data=urllib.parse.urlencode(params).encode(), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        # Token suresi dolmussa bunu ACIKCA soyle: 60 gunde bir yenileniyor
        # ve dolduğu gun bot sessizce susarsa sebebi aranir.
        if "190" in body or "OAuthException" in body:
            sys.exit(f"Instagram jetonu gecersiz veya suresi dolmus.\n{body[:400]}")
        sys.exit(f"Instagram API hatasi {exc.code}:\n{body[:400]}")


def repo_slug() -> str:
    """owner/repo. Actions'ta ortamdan, yerelde git remote'tan."""
    env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if env:
        return env
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit("repo adresi bulunamadi (GITHUB_REPOSITORY yok, git remote yok)")
    return url.removesuffix(".git").split("github.com")[-1].lstrip(":/")


def card_urls(cards_dir: Path, branch: str = "main") -> list[str]:
    """Kartların herkese açık raw adresleri, sayfa sırasına göre."""
    cards = sorted(p for p in cards_dir.glob("*.png") if p.name != "havuz.png")
    if not cards:
        sys.exit(f"kart bulunamadi: {cards_dir}")
    slug = repo_slug()
    urls = []
    for card in cards:
        rel = card.relative_to(ROOT).as_posix()
        urls.append(f"https://raw.githubusercontent.com/{slug}/{branch}/{rel}")
    return urls


def reachable(url: str) -> bool:
    """Instagram bu adresi indirebilecek mi? Once biz deneyelim.

    Kartlar commit edilmeden yayinlanmaya calisilirsa Instagram'in verdigi
    hata anlasilmaz oluyor; burada erken ve net soyluyoruz.
    """
    try:
        request = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "questpost/0.1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def wait_finished(container_id: str, etiket: str) -> None:
    """Container hazir olana kadar bekle. Instagram gorseli kendi indiriyor."""
    for deneme in range(1, STATUS_TRIES + 1):
        data = call(container_id, {"fields": "status_code,status"}, method="GET")
        durum = data.get("status_code")
        if durum == "FINISHED":
            return
        if durum == "ERROR":
            sys.exit(f"{etiket}: Instagram gorseli isleyemedi\n{data.get('status')}")
        time.sleep(STATUS_WAIT)
    sys.exit(f"{etiket}: container {STATUS_TRIES * STATUS_WAIT} sn icinde hazir olmadi")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post Instagram paylasimi")
    ap.add_argument("draft", help="post tarifi (JSON)")
    ap.add_argument("--cards", required=True, help="kart klasoru")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--dry-run", action="store_true",
                    help="Instagram'a gondermez, adresleri ve metni gosterir")
    args = ap.parse_args()

    draft_path = Path(args.draft).resolve()
    spec = json.loads(draft_path.read_text(encoding="utf-8"))
    caption = (spec.get("caption") or "").strip()

    urls = card_urls(Path(args.cards).resolve(), args.branch)
    print(f"{len(urls)} kart, gonderi metni {len(caption)} karakter\n")
    for index, url in enumerate(urls, 1):
        print(f"  {index}. {url}")

    if args.dry_run:
        print(f"\n--dry-run: gonderilmedi\n\ncaption:\n{caption}")
        return 0

    if len(urls) > CAROUSEL_MAX:
        sys.exit(f"instagram en fazla {CAROUSEL_MAX} gorsel aliyor, {len(urls)} kart var")

    # Kartlar commit edilmemisse Instagram'in hatasi anlasilmaz olur.
    print()
    erisilemeyen = [u for u in urls if not reachable(u)]
    if erisilemeyen:
        sys.exit("kartlar github'da bulunamadi (henuz commit edilmemis olabilir):\n  "
                 + "\n  ".join(erisilemeyen[:3]))
    print("kartlarin adresleri erisilebilir")

    _, user_id = credentials()

    if len(urls) < CAROUSEL_MIN:
        # Tek kart: carousel olamaz, dogrudan tek gorsel.
        print("\ntek kart: carousel yerine tek gorsel gonderiliyor")
        container = call(f"{user_id}/media",
                         {"image_url": urls[0], "caption": caption})
        wait_finished(container["id"], "tek gorsel")
        parent_id = container["id"]
    else:
        print(f"\n{len(urls)} container olusturuluyor...")
        children = []
        for index, url in enumerate(urls, 1):
            item = call(f"{user_id}/media",
                        {"image_url": url, "is_carousel_item": "true"})
            children.append(item["id"])
            print(f"  {index}. container {item['id']}")

        print("\ncontainerlar hazirlaniyor...")
        for index, child in enumerate(children, 1):
            wait_finished(child, f"kart {index}")
        print("  hepsi hazir")

        parent = call(f"{user_id}/media", {
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": caption,
        })
        parent_id = parent["id"]
        wait_finished(parent_id, "carousel")

    print("\nyayinlaniyor...")
    sonuc = call(f"{user_id}/media_publish", {"creation_id": parent_id})
    post_id = sonuc.get("id", "?")
    print(f"paylasildi. gonderi id: {post_id}")

    # Gonderi id'si tarife yaziliyor: sonradan "bu post nereye gitti"
    # sorusu sorulabilsin.
    spec["_ig_post_id"] = post_id
    draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

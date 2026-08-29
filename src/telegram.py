#!/usr/bin/env python3
"""Telegram onay kanalı: hazır postu sorar, cevabı okur.

Faz 5 - TG_BOT_TOKEN ve TG_CHAT_ID gerekir.

Telegram bir program değil, posta kutusu. Betik uyandığında `getUpdates` ile
"cevap geldi mi" diye sorar, işini yapar, uyur. Sürekli çalışan bir süreç yok.

Kullanım:
    py -3.12 src/telegram.py send state/draft.json    # kartlari yolla, sor
    py -3.12 src/telegram.py poll                     # cevabi oku, karari uygula
    py -3.12 src/telegram.py say "metin"              # duz mesaj (hata bildirimi)

Komutlar (kullanicinin Telegram'a yazacaklari):
    /ok         onayla, otomatik paylasima gonder
    /bana       kartlari bana yolla, elimle paylasacagim
    /iptal      bu postu at
    /yeniden    metni yeniden uret
    /c /b /a /s tier'i ez
    /gorsel 1 3 5   sayfalara sirasiyla havuzdaki N. gorseli ata
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PENDING_FILE = ROOT / "state" / "pending.json"
OFFSET_FILE = ROOT / "state" / "tg_offset.json"

API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024

TIER_LABELS = {"C": "sıradan", "B": "büyülü", "A": "sıradışı", "S": "mitik"}

# Telegram'in kendi komutlari. "bilinmeyen komut" diye cevaplanmamali.
KOMUT_YARDIM = ("/ok onayla · /bana kartları bana yolla · /yeniden metni yeniden yaz\n"
                "/gorsel başka görsel dene · /havuz tüm görselleri numaralı gör\n"
                "/gorsel 4 7 2 sayfa sayfa seç · /iptal at · /c /b /a /s tier")


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def config() -> tuple[str, str]:
    load_env()
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat:
        sys.exit(".env icinde TG_BOT_TOKEN ve TG_CHAT_ID dolu olmali")
    return token, chat


# ------------------------------------------------------------------- istek

def call(method: str, params: dict | None = None,
         files: dict[str, Path] | None = None) -> dict:
    token, _ = config()
    url = API.format(token=token, method=method)

    if files:
        body, content_type = build_multipart(params or {}, files)
        request = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": content_type})
    else:
        data = urllib.parse.urlencode(params or {}).encode()
        request = urllib.request.Request(url, data=data, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"Telegram hatasi {exc.code}: {exc.read().decode('utf-8','replace')[:300]}")

    if not payload.get("ok"):
        sys.exit(f"Telegram reddetti: {payload}")
    return payload["result"]


def build_multipart(fields: dict, files: dict[str, Path]) -> tuple[bytes, str]:
    """Dosya yuklemek icin multipart govde. Stdlib'de hazir bir sey yok."""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(f"{value}\r\n".encode())

    for name, path in files.items():
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n".encode())
        parts.append(path.read_bytes())
        parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# -------------------------------------------------------------------- ozet

def summarize(spec: dict, cards: list[Path]) -> str:
    """Onay mesajinin metni. Kullanici karara bakarak karar verecek."""
    tier = spec.get("tier", "?")
    lines = [
        f"{spec.get('game', '?')}",
        f"{tier} · {TIER_LABELS.get(tier, '?')} · {spec.get('category', '?')}",
        f"{len(cards)} kart · {spec.get('_kaynak_sayisi', '?')} kaynak yazmış",
    ]
    if spec.get("credit"):
        lines.append(f"görsel: {spec['credit']}")
    else:
        lines.append("görsel yok (tipografik kart)")
    if spec.get("_kaynak"):
        lines.append(spec["_kaynak"])

    lines.append("")
    for index, page in enumerate(spec["pages"], 1):
        baslik = page.get("title") or page.get("question") or page["type"]
        lines.append(f"{index}. {baslik}")

    lines += ["", "/ok onayla · /bana bana yolla · /yeniden yeniden yaz",
              "/gorsel başka görsel · /havuz görselleri gör · /iptal at",
              "/c /b /a /s tier değiştir"]

    text = "\n".join(lines)
    return text[:CAPTION_LIMIT - 3] + "..." if len(text) > CAPTION_LIMIT else text


def send_cards(spec: dict, cards: list[Path]) -> list[int]:
    """Kartlari albüm olarak yolla. Caption ilk karta bindirilir."""
    _, chat = config()
    caption = summarize(spec, cards)

    media, files = [], {}
    for index, card in enumerate(cards):
        name = f"card{index}"
        item = {"type": "photo", "media": f"attach://{name}"}
        if index == 0:
            item["caption"] = caption
        media.append(item)
        files[name] = card

    result = call("sendMediaGroup",
                  {"chat_id": chat, "media": json.dumps(media, ensure_ascii=False)},
                  files)
    return [m["message_id"] for m in result]


def send_text(text: str) -> int:
    _, chat = config()
    return call("sendMessage", {"chat_id": chat, "text": text})["message_id"]


def send_photo(path: Path, caption: str = "") -> int:
    _, chat = config()
    params = {"chat_id": chat}
    if caption:
        params["caption"] = caption
    return call("sendPhoto", params, {"photo": path})["message_id"]


def send_documents(cards: list[Path]) -> None:
    """/bana: kartlari sikistirilmamis dosya olarak yolla.

    Fotograf olarak yollanan gorsel Telegram tarafindan yeniden sikistiriliyor;
    kullanici onu indirip Instagram'a atacaksa kalite kaybi olmamali.
    """
    _, chat = config()
    for index, card in enumerate(cards, 1):
        call("sendDocument", {"chat_id": chat, "caption": f"{index:02d}.png"},
             {"document": card})


# ------------------------------------------------------------------ durum

def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Gecici dosya sonra tasi: yarim yazilmis state dosyasi botu kilitler.
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


# ---------------------------------------------------------------- komutlar

def parse_command(text: str) -> tuple[str, list[str]] | None:
    text = (text or "").strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    if not parts:
        return None
    return parts[0].lower(), parts[1:]


def fetch_commands() -> tuple[list[tuple[str, list[str]]], int | None]:
    """Yeni komutlari oku. Offset dosyasi ayni komutu iki kez islemeyi onler."""
    _, chat = config()
    offset = read_json(OFFSET_FILE, {}).get("offset", 0)
    updates = call("getUpdates", {"offset": offset, "timeout": 0})

    commands, last = [], None
    for update in updates:
        last = update["update_id"]
        message = update.get("message") or update.get("edited_message") or {}
        if str((message.get("chat") or {}).get("id")) != str(chat):
            continue  # baska sohbetten gelen mesaj yok sayilir
        parsed = parse_command(message.get("text", ""))
        if parsed:
            commands.append(parsed)
    return commands, last


def commit_offset(last: int | None) -> None:
    if last is not None:
        write_json(OFFSET_FILE, {"offset": last + 1})


# ------------------------------------------------------------------- akis

def do_send(draft_path: Path, cards_dir: Path) -> int:
    spec = json.loads(draft_path.read_text(encoding="utf-8"))
    cards = sorted(cards_dir.glob("*.png"))
    if not cards:
        sys.exit(f"kart bulunamadi: {cards_dir} (once render.py)")

    message_ids = send_cards(spec, cards)
    # Yollar POSIX bicimde yazilir: bot GitHub Actions'ta Linux'ta calisiyor,
    # Windows'ta uretilen "state\draft.json" orada cozulmuyor.
    write_json(PENDING_FILE, {
        "durum": "onay_bekliyor",
        "draft": draft_path.relative_to(ROOT).as_posix(),
        "cards_dir": cards_dir.relative_to(ROOT).as_posix(),
        "message_ids": message_ids,
        "tier": spec.get("tier"),
    })
    print(f"{len(cards)} kart yollandi, onay bekleniyor. pending.json yazildi.")
    return 0


def do_poll() -> int:
    pending = read_json(PENDING_FILE, None)
    commands, last = fetch_commands()

    if not commands:
        print("yeni komut yok")
        commit_offset(last)
        return 0

    if not pending or pending.get("durum") != "onay_bekliyor":
        for name, _ in commands:
            print(f"komut geldi ama bekleyen post yok: /{name}")
        if any(name in ("start", "help", "yardim") for name, _ in commands):
            send_text("hazır postları buraya yollayacağım.\n\n" + KOMUT_YARDIM)
        else:
            send_text("şu an onay bekleyen bir post yok.")
        commit_offset(last)
        return 0

    draft_path = ROOT / pending["draft"]
    spec = json.loads(draft_path.read_text(encoding="utf-8"))
    karar = None
    bilinmeyen: list[str] = []

    for name, args in commands:
        if name in ("start", "help", "yardim"):
            send_text("hazır postları buraya yollayacağım.\n\n" + KOMUT_YARDIM)
        elif name in ("ok", "otomatik"):
            karar = "yayinla"
        elif name == "bana":
            karar = "elle"
        elif name == "iptal":
            karar = "iptal"
        elif name == "yeniden":
            karar = "yeniden_uret"
        elif name.upper() in TIER_LABELS:
            spec["tier"] = name.upper()
            pending["tier"] = name.upper()
            draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            send_text(f"tier {name.upper()} ({TIER_LABELS[name.upper()]}) olarak "
                      f"ayarlandı. kartları yeniden basmam gerekiyor.")
            karar = "yeniden_bas"
        elif name in ("gorsel", "görsel"):
            if args:
                spec["_gorsel_secimi"] = args
                draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
                send_text(f"görsel seçimi kaydedildi: {' '.join(args)}")
                karar = "gorsel_degisti"
            else:
                # Argumansiz: "bunlari begenmedim, baska bir set dene".
                # Kullanici havuzdaki numaralari ezberlemek zorunda kalmasin.
                karar = "gorsel_baska_set"
        elif name == "havuz":
            karar = "havuz"
        else:
            bilinmeyen.append(f"/{name}")

    # Tek mesajda topla: her bilinmeyen komuta ayri cevap yazmak sohbeti
    # bogmakti (uc /start ucu ayri hata mesaji uretti).
    if bilinmeyen:
        send_text("anlamadığım komut: " + ", ".join(bilinmeyen) + "\n\n" + KOMUT_YARDIM)

    if karar:
        pending["durum"] = karar
        write_json(PENDING_FILE, pending)
        print(f"karar: {karar}")
        if karar == "elle":
            send_documents(sorted((ROOT / pending["cards_dir"]).glob("*.png")))
            send_text("kartlar dosya olarak yollandı. instagram'ın kendi müziğiyle "
                      "paylaşabilirsin.")
        elif karar == "yayinla":
            send_text("onaylandı, paylaşıma alınıyor.")
        elif karar == "iptal":
            send_text("post atıldı.")

    commit_offset(last)
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post Telegram onay kanali (Faz 5)")
    sub = ap.add_subparsers(dest="komut", required=True)

    p_send = sub.add_parser("send", help="kartlari yolla ve onay sor")
    p_send.add_argument("draft")
    p_send.add_argument("--cards", default=None, help="kart klasoru (varsayilan: out/<draft adi>)")

    sub.add_parser("poll", help="cevabi oku")

    p_say = sub.add_parser("say", help="duz mesaj yolla")
    p_say.add_argument("text")

    args = ap.parse_args()

    if args.komut == "send":
        draft_path = Path(args.draft).resolve()
        cards_dir = Path(args.cards).resolve() if args.cards else ROOT / "out" / draft_path.stem
        return do_send(draft_path, cards_dir)
    if args.komut == "poll":
        return do_poll()
    if args.komut == "say":
        send_text(args.text)
        print("gonderildi")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

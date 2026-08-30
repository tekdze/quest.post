#!/usr/bin/env python3
"""Telegram onay kanalı: hazır postu sorar, cevabı okur.

TG_BOT_TOKEN ve TG_CHAT_ID gerekir.

Telegram bir program değil, posta kutusu. Betik uyandığında `getUpdates` ile
"cevap geldi mi" diye sorar, işini yapar, uyur. Sürekli çalışan bir süreç yok.

Kuyruk çok girdili: normal post onay beklerken acil bir haber girebilsin diye.
İki post aynı anda beklerken komutun hangisine ait olduğu şöyle çözülür:
kullanıcı o postun mesajını YANITLARSA komut ona gider; yanıtlamazsa ve
bekleyen tek post varsa ona gider; birden fazlaysa bot hangisi diye sorar.
Yanlış posta /iptal uygulanmasındansa bir kez fazla sorulsun.

Kullanım:
    py -3.12 src/telegram.py send state/drafts/<id>.json  # kartlari yolla, sor
    py -3.12 src/telegram.py poll                     # cevabi oku, karari uygula
    py -3.12 src/telegram.py say "metin"              # duz mesaj (hata bildirimi)

Komutlar (kullanicinin Telegram'a yazacaklari):
    /ok         onayla, otomatik paylasima gonder
    /bana       kartlari bana yolla, elimle paylasacagim
    /iptal      bu postu at
    /yeniden    metni yeniden uret
    /c /b /a /s tier'i ez
    /gorsel 1 3 5   sayfalara sirasiyla havuzdaki N. gorseli ata
    /kuyruk     bekleyen postlari listele
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PENDING_FILE = ROOT / "state" / "pending.json"
OFFSET_FILE = ROOT / "state" / "tg_offset.json"
MENU_FILE = ROOT / "state" / "menu.json"
# Posta bagli olmayan istekler burada bekler: telegram.py kaydeder,
# respond.py icra eder. Kuyruk post bazli oldugu icin bunlar oraya sigmiyor.
ISTEK_FILE = ROOT / "state" / "istek.json"
# Tekrarlayan hata uyarilarinin kaydi (bkz. hata_bildir).
UYARI_FILE = ROOT / "state" / "uyari.json"

API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024

TIER_LABELS = {"C": "sıradan", "B": "büyülü", "A": "sıradışı", "S": "mitik"}

# Kuyrukta en fazla bu kadar post bekleyebilir. Sinirsiz birakilirsa unutulan
# postlar birikir ve hangi komutun nereye gittigi takip edilemez hale gelir.
MAX_KUYRUK = 3

# Komut alindi bildirimi. Bot cron ile uyandigi icin kullanici komutu yazip
# bir sure bekliyor; uyandiginda once "gordum, calisiyorum" demeli, yoksa
# sistemin calisip calismadigi belirsiz kaliyor. Sureler olculen degerler.
ACK = {
    "havuz": "havuz işleme alındı. görselleri numaralı ızgarada yollayacağım, ~1 dk.",
    "gorsel_baska_set": "başka bir görsel seti deneniyor. kartlar yeniden basılıp "
                        "yollanacak, ~1-2 dk.",
    "gorsel_degisti": "görsel seçimin alındı. kartlar yeniden basılıyor, ~1-2 dk.",
    "yeniden_bas": "tier değişikliği alındı. kartlar yeniden basılıyor, ~1 dk.",
    "yeniden_uret": "yeniden yazım işleme alındı. önce metin, sonra kartlar, ~2-3 dk.",
    "elle": "kartlar sıkıştırılmamış dosya olarak yollanıyor...",
    "yayinla": "onay alındı, paylaşıma bakılıyor.",
    "iptal": "post atılıyor.",
}

# Posta bagli olmayan istekler ve bildirimleri.
ISTEK_ACK = {
    "uret": "seçimin alındı. metin yazılıp kartlar basılacak, ~2-3 dk.",
    "konular": "adaylar taranıyor, menü hazırlanıyor, ~1-2 dk.",
    "api": "anahtarlar yoklanıyor, ~1 dk.",
}

# TEK KAYNAK: hem /komutlar rehberi hem kisa yardim buradan uretiliyor.
# Yeni komut eklerken SADECE buraya yazilir; iki yeri guncelleme derdi
# olmasin diye. Kisa yardim ilk sutundan, rehber tamamindan.
KOMUT_REHBERI = [
    ("günlük akış", [
        ("/konular", "günün aday haberlerini listeler. her aday için ne haberi "
                     "olduğu, kaç kaynağın yazdığı ve görsel durumu yazılı. "
                     "⭐ işareti botun önerisi"),
        ("/uret 2", "listeden seçtiğin numarayı üretir. metin yazılır, görseller "
                    "seçilir, kartlar basılır ve onayına sunulur"),
    ]),
    ("kartlar geldiğinde", [
        ("/ok", "onayla ve instagram'a paylaş"),
        ("/bana", "kartları sıkıştırılmamış dosya olarak yolla, elle paylaşacaksan. "
                  "gönderi açıklaması da ayrı mesaj olarak gelir"),
        ("/yeniden", "metni baştan yazdır, görselleri ve kartları yenile"),
        ("/iptal", "postu at. atılan haber bir daha aday olarak gelmez"),
    ]),
    ("görsel değiştirme", [
        ("/havuz", "o oyunun tüm görsellerini numaralı ızgarada gösterir"),
        ("/gorsel", "aynı oyundan başka bir set dener"),
        ("/gorsel 4 7 2", "havuzdaki numaraları sayfa sırasına göre atar"),
    ]),
    ("kademe", [
        ("/c /b /a /s", "kademeyi elle değiştir (sıradan · büyülü · sıradışı · "
                        "mitik). kartlar yeni renkle yeniden basılır"),
    ]),
    ("durum", [
        ("/kuyruk", "onay bekleyen postları listeler"),
        ("/apideadline", "anahtarların durumu: çalışıyor mu, kotası doldu mu, "
                         "süresi bitiyor mu"),
    ]),
    ("yardım", [
        ("/komutlar", "bu liste"),
    ]),
]

# Bir POSTA uygulanan komutlar. Bunun disindakiler ya global (yukarida
# islenir) ya da yazim hatasi.
POST_KOMUTLARI = {"ok", "otomatik", "bana", "iptal", "yeniden", "havuz",
                  "gorsel", "görsel", "c", "b", "a", "s"}

# Birden fazla post beklerken komutun adresi.
REPLY_NOTU = ("birden fazla post beklerken: komutu o postun mesajına YANIT "
              "olarak yaz. yanıtlamazsan ve tek post bekliyorsa ona uygulanır; "
              "birden fazlaysa bot hangisi diye sorar.")


def komut_rehberi() -> str:
    """`/komutlar` çıktısı: gruplu, açıklamalı tam liste."""
    satirlar = ["quest.post komutları", ""]
    for baslik, komutlar in KOMUT_REHBERI:
        satirlar.append(f"— {baslik} —")
        for komut, aciklama in komutlar:
            satirlar.append(f"{komut}")
            satirlar.append(f"   {aciklama}")
        satirlar.append("")
    satirlar.append(REPLY_NOTU)
    return "\n".join(satirlar)


# Kisa yardim: bilinmeyen komut ve /start icin. Rehberin tamami uzun,
# her hatada yollamak sohbeti boguyor.
KOMUT_YARDIM = (" · ".join(k for _, komutlar in KOMUT_REHBERI for k, _ in komutlar)
                + "\n\ntam açıklama için /komutlar")


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

def summarize(spec: dict, cards: list[Path], etiket: str = "normal",
              baska_bekleyen: int = 0) -> str:
    """Onay mesajinin metni. Kullanici karara bakarak karar verecek."""
    tier = spec.get("tier", "?")
    lines = []
    if etiket == "acil":
        lines.append("ACİL")
    lines += [
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
    # Yedek modelle yazildiysa soyle: uslup farki fark edilirse sebebi belli
    # olsun, kullanici isterse /yeniden ile tekrar denesin.
    if spec.get("_model") and spec["_model"] != "gemini-3.6-flash":
        lines.append(f"NOT: yedek modelle yazıldı ({spec['_model']})")

    lines.append("")
    for index, page in enumerate(spec["pages"], 1):
        baslik = page.get("title") or page.get("question") or page["type"]
        lines.append(f"{index}. {baslik}")

    # Kart mesajinda kisa liste: caption siniri 1024, tam rehber sigmaz.
    lines += ["", "/ok onayla · /bana bana yolla · /yeniden yeniden yaz",
              "/gorsel başka görsel · /havuz görselleri gör · /iptal at",
              "/c /b /a /s tier · /komutlar tüm komutlar"]

    # Baska post da beklerken komutun adresi belirsiz kalmasin.
    if baska_bekleyen:
        lines.append("")
        lines.append("başka post da bekliyor: komutu bu mesaja yanıt olarak yaz.")

    text = "\n".join(lines)
    return text[:CAPTION_LIMIT - 3] + "..." if len(text) > CAPTION_LIMIT else text


def send_cards(spec: dict, cards: list[Path], etiket: str = "normal",
               baska_bekleyen: int = 0) -> list[int]:
    """Kartlari albüm olarak yolla. Caption ilk karta bindirilir."""
    _, chat = config()
    caption = summarize(spec, cards, etiket, baska_bekleyen)

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


# Ayni uyariyi bu sure boyunca bir kez yolla. Bot 5 dakikada bir uyandigi
# icin takilan tek bir is gunde 288 mesaj uretebiliyor (2026-08-30'da
# uretti). Asil cozum hatanin kendisini duzeltmek ama her hatayi onceden
# bilemeyiz: bu, hangi yoldan gelirse gelsin tekrari kesen son emniyet.
UYARI_SUSTURMA_DK = 60
# Kayit bu kadar sonra unutulur: dosya sonsuza kadar sismesin.
UYARI_OMRU_SAAT = 24


def hata_bildir(text: str, anahtar: str | None = None) -> bool:
    """Hata uyarısı yolla, ama aynısını tekrarlama. True = yollandı.

    `anahtar`: metin her seferinde değişiyorsa (workflow mesajlarında
    Actions run numarası var) aynı iş olarak sayılması için sabit bir
    kimlik. Verilmezse metnin kendisi kimlik olur.

    Susturulan tekrar sayılıyor ve uyarı yeniden yollandığında yazılıyor:
    "(bu uyarı 47 kez daha tekrarlandı)". Böylece sorun sessizce kaybolmuyor,
    sadece sohbeti boğmuyor.
    """
    simdi = datetime.now(timezone.utc)
    kimlik = anahtar or text
    kayit = read_json(UYARI_FILE, {})
    satir = kayit.get(kimlik)

    if satir:
        try:
            son = datetime.fromisoformat(satir["son"])
        except (ValueError, KeyError):
            son = None
        if son and (simdi - son) < timedelta(minutes=UYARI_SUSTURMA_DK):
            satir["bastirilan"] = satir.get("bastirilan", 0) + 1
            satir["son"] = simdi.isoformat(timespec="seconds")
            kayit[kimlik] = satir
            write_json(UYARI_FILE, kayit)
            print(f"uyari bastirildi ({satir['bastirilan']}. tekrar): {text[:60]}")
            return False

    bastirilan = (satir or {}).get("bastirilan", 0)
    govde = text
    if bastirilan:
        govde += f"\n\n(bu uyarı {bastirilan} kez daha tekrarlandı)"
    send_text(govde)

    # Eskimis kayitlari at, yenisini yaz.
    sinir = simdi - timedelta(hours=UYARI_OMRU_SAAT)
    temiz = {}
    for anahtar, deger in kayit.items():
        try:
            if datetime.fromisoformat(deger["son"]) >= sinir:
                temiz[anahtar] = deger
        except (ValueError, KeyError, TypeError):
            continue
    temiz[kimlik] = {"son": simdi.isoformat(timespec="seconds"), "bastirilan": 0}
    write_json(UYARI_FILE, temiz)
    return True


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


# ------------------------------------------------------------------ kuyruk

def load_queue() -> list[dict]:
    """pending.json'daki kuyruğu oku.

    Eski tek slotlu biçim de okunur: {"durum": ..., "draft": ...} bir girdilik
    kuyruğa çevrilir. Böylece elde duran bir post sürüm geçişinde kaybolmaz.
    """
    data = read_json(PENDING_FILE, None)
    if not data:
        return []
    if isinstance(data, dict) and "kuyruk" in data:
        return data["kuyruk"]
    if isinstance(data, dict) and data.get("draft"):
        entry = dict(data)
        entry.setdefault("id", Path(data["draft"]).stem)
        entry.setdefault("etiket", "normal")
        return [entry]
    return []


def save_queue(queue: list[dict]) -> None:
    write_json(PENDING_FILE, {"kuyruk": queue})


def bekleyenler(queue: list[dict]) -> list[dict]:
    return [e for e in queue if e.get("durum") == "onay_bekliyor"]


def hedef_bul(queue: list[dict], reply_to: int | None) -> dict | None:
    """Komutun hangi posta ait olduğunu bul.

    Yanıtlanan mesajın id'si o postun kart mesajlarından biriyse hedef odur.
    Kartlar albüm olarak gidiyor, yani bir postun birden çok message_id'si var;
    kullanıcı hangisini yanıtlarsa yanıtlasın aynı posta düşer.
    """
    if reply_to is None:
        return None
    for entry in queue:
        if reply_to in (entry.get("message_ids") or []):
            return entry
    return None


def istek_yaz(ne: str, ek: dict | None = None) -> None:
    """Posta bağlı olmayan bir işi respond.py'ye bırak."""
    kayit = {"istek": ne}
    kayit.update(ek or {})
    write_json(ISTEK_FILE, kayit)


def uret_hedefi(args: list[str]) -> int | None:
    """/uret <numara> doğrulaması. Menü yoksa veya numara geçersizse uyarır."""
    menu = read_json(MENU_FILE, None)
    if not menu or not menu.get("adaylar"):
        send_text("elimde güncel bir aday listesi yok. önce /konular yaz.")
        return None
    if not args:
        send_text("hangi adayı üreteyim? örnek: /uret 2\n\n"
                  "listeyi yeniden görmek için /konular")
        return None
    try:
        sira = int(args[0])
    except ValueError:
        send_text(f"'{args[0]}' bir numara değil. örnek: /uret 2")
        return None
    if not any(row.get("sira") == sira for row in menu["adaylar"]):
        send_text(f"listede {sira} numaralı aday yok "
                  f"(1-{len(menu['adaylar'])} arası bir numara yaz).")
        return None
    return sira


def kuyruk_ozeti(queue: list[dict]) -> str:
    satirlar = []
    for index, entry in enumerate(bekleyenler(queue), 1):
        etiket = "ACİL · " if entry.get("etiket") == "acil" else ""
        satirlar.append(f"{index}. {etiket}{entry.get('baslik') or entry.get('id')} "
                        f"({entry.get('tier', '?')})")
    return "\n".join(satirlar) if satirlar else "kuyruk boş."


# ---------------------------------------------------------------- komutlar

def parse_command(text: str) -> tuple[str, list[str]] | None:
    text = (text or "").strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    if not parts:
        return None
    return parts[0].lower(), parts[1:]


def fetch_commands() -> tuple[list[tuple[str, list[str], int | None]], int | None]:
    """Yeni komutlari oku. Offset dosyasi ayni komutu iki kez islemeyi onler.

    Ucuncu alan: komut bir mesaji yanitliyorsa o mesajin id'si. Kuyrukta
    birden fazla post varken komutun adresi bundan cozuluyor.
    """
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
            reply_to = (message.get("reply_to_message") or {}).get("message_id")
            commands.append((parsed[0], parsed[1], reply_to))
    return commands, last


def commit_offset(last: int | None) -> None:
    if last is not None:
        write_json(OFFSET_FILE, {"offset": last + 1})


# ------------------------------------------------------------------- akis

def do_send(draft_path: Path, cards_dir: Path, etiket: str = "normal") -> int:
    spec = json.loads(draft_path.read_text(encoding="utf-8"))
    cards = sorted(cards_dir.glob("*.png"))
    if not cards:
        sys.exit(f"kart bulunamadi: {cards_dir} (once render.py)")

    queue = load_queue()
    post_id = draft_path.stem

    # Ayni post yeniden basildiginda (tier degisti, gorsel degisti) kuyruga
    # ikinci girdi eklenmemeli: var olan guncellenir, eski message_id'ler
    # yerine yenileri yazilir.
    onceki = next((e for e in queue if e.get("id") == post_id), None)
    if onceki is None and len(bekleyenler(queue)) >= MAX_KUYRUK:
        sys.exit(f"kuyruk dolu ({MAX_KUYRUK}). once bekleyen postlari karara bagla.")

    message_ids = send_cards(spec, cards, etiket, len(bekleyenler(queue)))
    # Yollar POSIX bicimde yazilir: bot GitHub Actions'ta Linux'ta calisiyor,
    # Windows'ta uretilen "state\draft.json" orada cozulmuyor.
    entry = {
        "id": post_id,
        "etiket": onceki.get("etiket", etiket) if onceki else etiket,
        "durum": "onay_bekliyor",
        "baslik": spec.get("game", post_id),
        "draft": draft_path.relative_to(ROOT).as_posix(),
        "cards_dir": cards_dir.relative_to(ROOT).as_posix(),
        "message_ids": message_ids,
        "tier": spec.get("tier"),
    }
    if onceki:
        queue[queue.index(onceki)] = entry
    else:
        queue.append(entry)
    save_queue(queue)

    print(f"{len(cards)} kart yollandi ({entry['etiket']}), onay bekleniyor. "
          f"kuyruk: {len(bekleyenler(queue))}")
    return 0


def komutu_uygula(entry: dict, name: str, args: list[str]) -> str | None:
    """Tek bir komutu tek bir posta uygula, kararı döndür.

    Karar sadece kaydedilir; icrayı respond.py yapar. Bu ayrım korunuyor.
    """
    draft_path = ROOT / entry["draft"]

    if name in ("ok", "otomatik"):
        return "yayinla"
    if name == "bana":
        return "elle"
    if name == "iptal":
        return "iptal"
    if name == "yeniden":
        return "yeniden_uret"
    if name == "havuz":
        return "havuz"

    if name.upper() in TIER_LABELS:
        spec = json.loads(draft_path.read_text(encoding="utf-8"))
        spec["tier"] = name.upper()
        draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        entry["tier"] = name.upper()
        return "yeniden_bas"

    if name in ("gorsel", "görsel"):
        if args:
            spec = json.loads(draft_path.read_text(encoding="utf-8"))
            spec["_gorsel_secimi"] = args
            draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            return "gorsel_degisti"
        # Argumansiz: "bunlari begenmedim, baska bir set dene".
        # Kullanici havuzdaki numaralari ezberlemek zorunda kalmasin.
        return "gorsel_baska_set"

    return None


def do_poll() -> int:
    queue = load_queue()
    commands, last = fetch_commands()

    if not commands:
        print("yeni komut yok")
        commit_offset(last)
        return 0

    bilinmeyen: list[str] = []

    for name, args, reply_to in commands:
        # Posta bagli olmayan komutlar once: bunlar kuyruk bos olsa da calisir.
        if name in ("start", "help", "yardim"):
            send_text("hazır postları buraya yollayacağım.\n\n" + KOMUT_YARDIM)
            continue
        if name in ("komutlar", "yardim2"):
            send_text(komut_rehberi())
            continue
        if name == "kuyruk":
            send_text(kuyruk_ozeti(queue))
            continue
        if name in ("konular", "menu", "menü"):
            istek_yaz("konular")
            send_text(ISTEK_ACK["konular"])
            continue
        if name in ("apideadline", "api"):
            istek_yaz("api")
            send_text(ISTEK_ACK["api"])
            continue
        if name in ("uret", "üret"):
            hedef_sira = uret_hedefi(args)
            if hedef_sira is None:
                continue
            istek_yaz("uret", {"sira": hedef_sira})
            send_text(ISTEK_ACK["uret"])
            continue

        # Bilinmeyen komut kontrolu ADRES aramadan once: kuyruk bosken
        # "/zart" yazilinca "onay bekleyen post yok" deniyordu ve kullanici
        # yazim hatasi yaptigini anlamiyordu.
        if name not in POST_KOMUTLARI:
            bilinmeyen.append(f"/{name}")
            continue

        # Komutun adresi: once yanit, sonra "tek bekleyen varsa o".
        hedef = hedef_bul(queue, reply_to)
        if hedef is None:
            aktif = bekleyenler(queue)
            if not aktif:
                print(f"komut geldi ama bekleyen post yok: /{name}")
                send_text("şu an onay bekleyen bir post yok.")
                continue
            if len(aktif) > 1:
                # Yanlis posta /iptal uygulamaktansa sormak iyidir.
                send_text(f"/{name} hangi posta? komutu o postun mesajına yanıt "
                          f"olarak yaz.\n\n" + kuyruk_ozeti(queue))
                continue
            hedef = aktif[0]

        if hedef.get("durum") != "onay_bekliyor":
            send_text(f"o post zaten karara bağlanmış ({hedef.get('durum')}).")
            continue

        karar = komutu_uygula(hedef, name, args)
        if karar is None:
            bilinmeyen.append(f"/{name}")
            continue

        hedef["durum"] = karar
        save_queue(queue)
        print(f"karar: {karar} -> {hedef.get('id')}")

        # Komut alindi bildirimi. Bot cron ile uyandigi icin kullanici bu
        # mesaji gorene kadar sistemin calisip calismadigini bilmiyor.
        # Etiket kuyrugun TAMAMINA bakar, bekleyenlere degil: karar yazilinca
        # bu post "bekleyen" olmaktan cikiyor ve etiket dusuyordu.
        mesaj = ACK.get(karar)
        if mesaj:
            if len(queue) > 1:
                mesaj = f"[{hedef.get('baslik') or hedef.get('id')}] {mesaj}"
            send_text(mesaj)

        if karar == "elle":
            # Kisa is, beklemeye deger degil: hemen burada yapilir.
            send_documents(sorted((ROOT / hedef["cards_dir"]).glob("*.png")))
            send_text("kartlar dosya olarak yollandı. instagram'ın kendi müziğiyle "
                      "paylaşabilirsin.")
            # Caption AYRI mesajda: Telegram'da tek dokunusla kopyalanabilsin,
            # aciklama metniyle karismasin.
            caption = (json.loads((ROOT / hedef["draft"]).read_text(encoding="utf-8"))
                       .get("caption") or "").strip()
            if caption:
                send_text(caption)

    # Tek mesajda topla: her bilinmeyen komuta ayri cevap yazmak sohbeti
    # bogmakti (uc /start ucu ayri hata mesaji uretti).
    if bilinmeyen:
        send_text("anlamadığım komut: " + ", ".join(bilinmeyen) + "\n\n" + KOMUT_YARDIM)

    commit_offset(last)
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post Telegram onay kanali")
    sub = ap.add_subparsers(dest="komut", required=True)

    p_send = sub.add_parser("send", help="kartlari yolla ve onay sor")
    p_send.add_argument("draft")
    p_send.add_argument("--cards", default=None, help="kart klasoru (varsayilan: out/<draft adi>)")
    p_send.add_argument("--etiket", default="normal", choices=["normal", "acil"],
                        help="acil: kuyrukta bekleyen post olsa da yollanir")

    sub.add_parser("poll", help="cevabi oku")

    p_say = sub.add_parser("say", help="duz mesaj yolla")
    p_say.add_argument("text")
    p_say.add_argument("--tekrarsiz", default=None, metavar="ANAHTAR",
                       help="ayni anahtarli uyari saatte bir kez yollanir")

    args = ap.parse_args()

    if args.komut == "send":
        draft_path = Path(args.draft).resolve()
        cards_dir = Path(args.cards).resolve() if args.cards else ROOT / "out" / draft_path.stem
        return do_send(draft_path, cards_dir, args.etiket)
    if args.komut == "poll":
        return do_poll()
    if args.komut == "say":
        if args.tekrarsiz:
            yollandi = hata_bildir(args.text, args.tekrarsiz)
            print("gonderildi" if yollandi else "bastirildi (tekrar)")
            return 0
        send_text(args.text)
        print("gonderildi")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

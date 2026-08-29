#!/usr/bin/env python3
"""Günün adaylarını Telegram'a menü olarak sunar, seçimi kullanıcı yapar.

Neden var: bot kendi seçtiği haberi doğrudan üretiyordu ve kullanıcı ancak
kartlar basıldıktan sonra "bunu istemiyorum" diyebiliyordu. Görselsiz bir
haber için LLM ve render bedeli boşa gidiyordu. Menü bu kararı öne alıyor:
metin üretimi ancak kullanıcı seçtikten sonra başlar.

Üç bilgi bir arada geliyor:
  - tier (KOD hesaplar, LLM değil - renk sistemi buna bağlı)
  - görsel durumu (IGDB'de gerçekten kaç kullanılabilir görsel var)
  - öneri (LLM, sadece "görünürlük açısından ilginç mi" sorusu)

LLM'e verilen bütçe SINIRLI: tam olarak bir aday seçmek zorunda. Serbest
bırakılırsa hepsini işaretler ve öneri değersizleşir - tier.py'nin
"LLM'e serbestlik verilirse her haberi S yapar" dersi burada da geçerli.
LLM tier'a DOKUNMAZ; öneri ayrı bir sinyaldir.

Kullanım:
    py -3.12 src/menu.py                 # menu uret ve Telegram'a yolla
    py -3.12 src/menu.py --dry-run       # yollamaz, ekrana basar
    py -3.12 src/menu.py --limit 6
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import images as img  # noqa: E402
import telegram as tg  # noqa: E402
import tier as tier_module  # noqa: E402
import write as writer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_FILE = ROOT / "state" / "candidates.json"
MENU_FILE = ROOT / "state" / "menu.json"

# Menude kac aday gosterilecek. Daha fazlasi Telegram mesajini okunmaz
# yapiyor ve LLM'in secim isini zorlastiriyor.
DEFAULT_LIMIT = 6

ONERI_SCHEMA = """{
  "adaylar": [
    {"sira": 1, "oyun": "haberde gecen oyunun TAM INGILIZCE adi, yoksa null"}
  ],
  "oneri": 3,
  "gerekce": "tek cumle, en fazla 12 kelime, kucuk harf"
}"""


def build_prompt(rows: list[dict]) -> str:
    satirlar = []
    for row in rows:
        satirlar.append(f"{row['sira']}. {row['title']}")
        ozet = (row.get("summary") or "").strip().replace("\n", " ")
        if ozet:
            satirlar.append(f"   {ozet[:240]}")

    return "\n".join([
        "Bir Türkçe oyun haberi hesabı için günün aday haberleri aşağıda.",
        "İki iş yapacaksın.",
        "",
        "BİRİNCİ İŞ: her aday için haberde adı geçen oyunun tam İngilizce",
        "adını çıkar (sürüm numarası dahil). Haberde bir oyun adı geçmiyorsa",
        "null yaz. Bu ad IGDB'de aranacak, o yüzden çevirme ve kısaltma.",
        "",
        "İKİNCİ İŞ: TAM OLARAK BİR aday öner. Ölçüt tek: bu haber bir",
        "Instagram gönderisi olarak GÖRÜNÜRLÜK açısından ilginç mi -",
        "insanlar durup okur mu, paylaşır mı, yorum yazar mı.",
        "",
        "Öneri ölçütü DEĞİLDİR: haberin büyüklüğü, kaç kaynağın yazdığı,",
        "ne kadar önemli olduğu. Bunlar zaten ayrıca hesaplanıyor.",
        "Sıradan görünen ama merak uyandıran bir haber, büyük ama kuru bir",
        "duyurudan daha iyi bir öneridir.",
        "",
        "Birden fazla öneremezsin. Hiçbirini öneremem diyemezsin. En iyisini",
        "seçmek zorundasın - kıyaslama yapman için böyle.",
        "",
        "ADAYLAR:",
        *satirlar,
        "",
        "SADECE şu şemada JSON döndür, başka hiçbir şey yazma:",
        ONERI_SCHEMA,
    ])


def gorsel_durumu(cid: str, token: str, oyun: str | None,
                  sayfa_tahmini: int = 4) -> dict:
    """Adayın IGDB'de kullanılabilir görseli var mı, kaç tane.

    Menüde "görsel VAR/YOK" yazabilmek için. Metin üretilmeden önce
    bakılıyor: kullanıcı görselsiz bir haberi hiç seçmek zorunda kalmasın.
    """
    if not oyun:
        return {"durum": "yok", "sayi": 0, "oyun": None}
    game, score, _ = img.find_game(cid, token, oyun)
    if game is None:
        return {"durum": "yok", "sayi": 0, "oyun": None}
    pool = img.image_pool(game)
    sayi = len(pool["artwork"]) + len(pool["screenshot"]) + len(pool["cover"])
    return {
        "durum": "var" if sayi >= sayfa_tahmini else "az",
        "sayi": sayi,
        "oyun": game["name"],
    }


def menu_metni(rows: list[dict], oneri: int | None, gerekce: str) -> str:
    satirlar = ["bugünün adayları:", ""]
    for row in rows:
        isaret = "  ⭐" if row["sira"] == oneri else ""
        satirlar.append(f"{row['sira']}. [{row['tier']}] {row['baslik']}{isaret}")

        gorsel = row["gorsel"]
        if gorsel["durum"] == "var":
            g = f"görsel VAR ({gorsel['sayi']})"
        elif gorsel["durum"] == "az":
            g = f"görsel AZ ({gorsel['sayi']}, sayfalarda tekrar eder)"
        else:
            g = "görsel YOK (tipografik olur)"
        satirlar.append(f"   {row['kaynak_sayisi']} kaynak · {g}")

        if gorsel.get("oyun") and gorsel["durum"] != "yok":
            satirlar.append(f"   görsel kaynağı: {gorsel['oyun']}")
        if row["sira"] == oneri and gerekce:
            satirlar.append(f"   \"{gerekce}\"")
        satirlar.append("")

    satirlar.append("üretmek için: /uret <numara>")
    return "\n".join(satirlar)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post aday menusu")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ap.add_argument("--dry-run", action="store_true", help="Telegram'a yollamaz")
    ap.add_argument("--model", default=writer.DEFAULT_MODEL)
    args = ap.parse_args()

    data = tg.read_json(CANDIDATES_FILE, None)
    if not data or not data.get("candidates"):
        sys.exit("aday bulunamadi (candidates.json bos). once: py -3.12 src/fetch.py")

    ham = data["candidates"][: args.limit]
    rows = []
    for sira, cand in enumerate(ham, 1):
        computed, _ = tier_module.compute(cand)
        rows.append({
            "sira": sira,
            "aday_index": sira,          # candidates.json'daki sira ile ayni
            "tier": computed,
            "title": cand["title"],
            "summary": (cand.get("members") or [{}])[0].get("summary", ""),
            "kaynak_sayisi": cand.get("source_count", 1),
            "url": cand.get("url"),
        })

    # Tek LLM cagrisi: hem oyun adlarini cikariyor hem oneriyi seciyor.
    # Ayri cagrilar bolmek gereksiz - ikisi de ayni metni okuyor.
    print(f"{len(rows)} aday LLM'e soruluyor...")
    cevap = writer.generate(build_prompt(rows), args.model, temperature=0.4)

    oyunlar = {}
    for row in cevap.get("adaylar", []):
        try:
            oyunlar[int(row.get("sira"))] = row.get("oyun")
        except (TypeError, ValueError):
            continue

    oneri = cevap.get("oneri")
    try:
        oneri = int(oneri)
    except (TypeError, ValueError):
        oneri = None
    if oneri is not None and not any(r["sira"] == oneri for r in rows):
        print(f"uyari: LLM listede olmayan {oneri} numarasini onerdi, yok sayildi")
        oneri = None
    gerekce = (cevap.get("gerekce") or "").strip()

    # Gorsel kontrolu: LLM'in verdigi oyun adlari IGDB'de aranir.
    # Metin uretilmeden once bakiliyor, bedeli sadece birkac arama.
    cid, secret = img.credentials()
    token = img.get_token(cid, secret)
    for row in rows:
        oyun = oyunlar.get(row["sira"])
        row["oyun_adi"] = oyun
        row["gorsel"] = gorsel_durumu(cid, token, oyun)
        row["baslik"] = oyun or (row["title"][:52].rstrip() + "..."
                                 if len(row["title"]) > 52 else row["title"])
        isaret = " <- ONERI" if row["sira"] == oneri else ""
        print(f"  {row['sira']}. [{row['tier']}] {row['baslik']} "
              f"| gorsel {row['gorsel']['durum']} ({row['gorsel']['sayi']}){isaret}")

    metin = menu_metni(rows, oneri, gerekce)

    # Secimin hangi adaya denk geldigi burada saklaniyor: kullanici
    # "/uret 2" yazdiginda respond.py bu dosyadan aday sirasini okuyacak.
    tg.write_json(MENU_FILE, {
        "olusturuldu": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "oneri": oneri,
        "gerekce": gerekce,
        "adaylar": [{k: v for k, v in row.items() if k != "summary"} for row in rows],
    })

    if args.dry_run:
        print("\n--- menu (yollanmadi) ---")
        print(metin)
        return 0

    tg.send_text(metin)
    print("\nmenu Telegram'a yollandi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

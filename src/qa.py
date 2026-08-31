#!/usr/bin/env python3
"""Görsel-sayfa eşleştirmesi: hangi kareyi hangi sayfaya koyalım.

Neden var: `images.py` görseli sayfa TİPİNE göre dağıtıyor (kapağa artwork,
metne screenshot). İçerikle bağı tesadüf. Ölçülen sonuç (20260830-gta-6):
metin köpek gezdirmekten bahsederken kartta arabada oturan bir adam, sonraki
sayfada arkasında yarım kalmış bir gece kulübü tabelası vardı. Kartlar tek
tek düzgün ama post amatör duruyordu.

İş bölümü DEĞİŞMİYOR: LLM veri verir, kod uygular.
- LLM'e sorulan tek şey: "bu sayfanın metnine havuzdaki hangi numara uyar"
- Sınırlı karar kümesi: yalnızca havuzdaki numaralar
- Kod doğrular: numara aralıkta mı, tekrar var mı, KAPAK ana oyundan mı
- LLM tasarıma, tier'a, metne dokunmuyor

Model havuzu tek bir numaralandırılmış ızgara olarak görüyor (`render.py
--sheet`, kullanıcının `/havuz` ile gördüğü sayfanın aynısı). Yani bir post
için tek görsel çağrısı yapılıyor, kart başına değil.

Kullanım:
    py -3.12 src/qa.py state/drafts/<id>.json            # esles, taslaga yaz
    py -3.12 src/qa.py state/drafts/<id>.json --dry-run  # sadece raporla
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render  # noqa: E402
import write as writer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Havuz bu sayidan buyukse ilk N'i gosteriliyor: izgara buyudukce hem
# istek sisiyor hem onizlemeler kucultulup okunmaz hale geliyor.
MAX_HAVUZ = 30

SEMA = """{
  "sayfalar": [
    {"sayfa": 1, "havuz": 12, "gerekce": "tek cumle, en fazla 10 kelime, kucuk harf"}
  ]
}"""


def sayfa_metni(page: dict) -> str:
    """Sayfanın modele gösterilecek metni. Kartta ne yazıyorsa o."""
    parcalar = [page.get("title") or page.get("question") or ""]
    if page.get("paragraph"):
        parcalar.append(page["paragraph"])
    for madde in page.get("bullets") or []:
        parcalar.append(f"- {madde}")
    for metrik in page.get("metrics") or []:
        parcalar.append(f"{metrik.get('value','')} {metrik.get('label','')}")
    return " ".join(p for p in parcalar if p).strip()


def build_prompt(spec: dict, pool: list[dict], ana_oyun: str | None) -> str:
    satirlar = []
    for sira, page in enumerate(spec["pages"], 1):
        etiket = {"cover": "KAPAK", "outro": "SON SAYFA"}.get(page["type"], "METİN")
        satirlar.append(f"Sayfa {sira} ({etiket}): {sayfa_metni(page)[:280]}")

    return "\n".join([
        "Görselde bir oyun görsel havuzu var: her kare sol üstte numaralı.",
        "Aşağıda bir Instagram gönderisinin sayfa metinleri yazılı.",
        "",
        "GÖREV: her sayfa için o metne EN UYGUN havuz numarasını seç.",
        "",
        "ÖLÇÜT, önem sırasıyla:",
        "1. Görselde görünen şey metinde anlatılanla ilgili olsun. Metin bir",
        "   mekanikten bahsediyorsa o mekaniği gösteren kare, bir karakterden",
        "   bahsediyorsa o karakter, şehirden bahsediyorsa şehir manzarası.",
        "2. Aynı derecede ilgili iki kare varsa ÇARPICI olanı seç: hareket,",
        "   güçlü ışık, karakterin yüzü, net bir olay. Boş koridor ya da",
        "   uzaktan çekilmiş sıkıcı manzara son tercih.",
        "   Bu bir KIYASLAMA - tek başına \"güzel mi\" diye sorulmuyor, iki",
        "   kare arasında hangisi durdurur diye soruluyor.",
        "3. Kare içindeki büyük yazı veya logo YARIM görünmesin. Kart 4:5",
        "   dikey kırpılıyor, yani geniş karelerin sol ve sağ kenarı kesiliyor.",
        "   Ortada duran yazı güvenli, kenarda duran kesilir.",
        "4. Alt yarısı sakin kareler daha iyi: kartın alt kısmına metin",
        "   basılıyor, kalabalık zemin okumayı zorlaştırıyor.",
        "5. Üzerinde haber sitesi logosu, filigran ya da kolaj düzeni",
        "   olan kareyi mümkünse seçme: kart kendi tasarımına benzemeli.",
        "6. Aynı numarayı iki sayfaya verme.",
        "",
        "Hiçbir kare gerçekten uymuyorsa en az kötü olanı seç, ama gerekçende",
        "bunu söyle. Uydurma bağ kurma - okur göremediği bağı fark eder.",
        "",
        "SAYFALAR:",
        *satirlar,
        "",
        f"Havuzda {len(pool)} kare var, numaralar 1-{len(pool)}.",
        "",
        "SADECE şu şemada JSON döndür, başka hiçbir şey yazma:",
        SEMA,
    ])


def dogrula(cevap: dict, spec: dict, pool: list[dict],
            ana_oyun: str | None) -> tuple[list[int | None], list[str]]:
    """Modelin seçimini denetle. Dönen liste sayfa sırasına göre havuz sırası.

    Kod burada karar veriyor: model yalnızca öneri getiriyor. Aralık dışı,
    tekrar eden veya kapak kuralını çiğneyen öneri sessizce düşürülüyor ve
    o sayfa eski seçiminde kalıyor.
    """
    secimler: list[int | None] = [None] * len(spec["pages"])
    notlar: list[str] = []
    kullanilan: set[int] = set()

    for row in writer.liste_al(cevap, "sayfalar"):
        try:
            sayfa = int(row.get("sayfa"))
            havuz = int(row.get("havuz"))
        except (TypeError, ValueError):
            continue
        if not 1 <= sayfa <= len(spec["pages"]):
            notlar.append(f"sayfa {sayfa} yok, yok sayildi")
            continue
        if not 1 <= havuz <= len(pool):
            notlar.append(f"sayfa {sayfa}: havuz {havuz} araliktan disari")
            continue
        if havuz in kullanilan:
            notlar.append(f"sayfa {sayfa}: {havuz} zaten kullanildi, yok sayildi")
            continue

        # KAPAK ASLA yedekten/temsiliden secilmez - vitrin kurali (DEVIR 4).
        # Model bunu bilmiyor, kod uyguluyor.
        if spec["pages"][sayfa - 1]["type"] == "cover" and ana_oyun:
            if (pool[havuz - 1].get("oyun") or "") != ana_oyun:
                notlar.append(f"kapak icin {havuz} onerildi ama o kare "
                              f"{pool[havuz-1].get('oyun')} oyunundan, reddedildi")
                continue

        kullanilan.add(havuz)
        secimler[sayfa - 1] = havuz
        gerekce = (row.get("gerekce") or "").strip()
        if gerekce:
            notlar.append(f"sayfa {sayfa} -> {havuz}: {gerekce[:60]}")

    return secimler, notlar


def mevcut_secim(spec: dict, pool: list[dict]) -> list[int | None]:
    """Sayfaların şu anki görselleri havuzun kaçıncı sırası.

    ⚠️ Eskiden kimlik dosya adinin SON TIRESINDEN sonrasi aliniyordu
    (`stem.rsplit("-", 1)[-1]`) ve bu yalnizca IGDB kimliklerinde
    dogruydu. Havuzdaki diger kimlikler tire ICERIYOR:
    "haber-2a8597eae20faf7c" ve "steam3751260-1". Onlarda ayirma
    yanlis parcayi veriyordu ("2a8597eae20faf7c", "1"), havuzda
    bulunamiyordu ve sayfa None donuyordu.

    Sonucu SESSIZ ve agirdi: `str(y or s or 1)` None'i 1'e ceviriyor,
    yani havuzun BIRINCI karesine. Haber gorseli kullanan bir postta
    qa.py her calistiginda o sayfalar birinci kareye zorlaniyordu -
    ustelik cogu zaman ayni kare birkac sayfaya birden.

    Olculdu (20260831-onimusha-way-of-the-sword): kart denetimi kapaktaki
    kirpik logoyu degistirdi, ama ayni turda 2. ve 3. kartlar (ikisi de
    haber gorseli) kirpik kapak karesine dondu - yani duzeltme kusuru
    yaymis oldu. Kart denetimi zincire baglanana kadar gorunmuyordu.

    Dogru yol tersten kurmak: her havuz karesi icin images.py'in
    yazacagi dosya adini uretip onunla eslestiriyoruz. Kimligin bicimi
    ne olursa olsun calisir.
    """
    slug = spec.get("_slug") or ""
    stem_of = {f"{slug}-{row['id']}": n for n, row in enumerate(pool, 1)}
    simdiki = []
    for page in spec["pages"]:
        yol = page.get("image") or ""
        stem = Path(yol).stem if yol else ""
        sira = stem_of.get(stem)
        if sira is None and stem:
            # Slug degismis olabilir (eski taslak): kimligi sondan ara.
            sira = next((n for n, row in enumerate(pool, 1)
                         if stem.endswith(f"-{row['id']}")), None)
        simdiki.append(sira)
    return simdiki


# Kart denetiminin karar kumesi. SINIRLI ve SOMUT tutuluyor: "bu kart guzel
# mi" gibi mutlak estetik sorusu bu sistemde calismiyor - model bozuk karta
# da "tamam" diyor, serbest birakilinca her kartta kusur buluyor (DEVIR'de
# iki ayri yerde kayitli). Buradakilerin hepsi GOZLE GORULUR kusur.
KART_KARARLARI = {
    "kirpik": "görselin içindeki bir yazı, tabela, logo ya da karakterin "
              "yüzü kartın kenarında YARIM kalmış (kesik_yazi doluysa "
              "durum buysa)",
    "okunmuyor": "kartın kendi metni zemin yüzünden zor okunuyor",
    "uygunsuz": "görselde hesaba yakışmayan bir öge var (müstehcen tabela, "
                "kan, başka markanın reklamı)",
}

KART_SEMA = """{
  "kartlar": [
    {"kart": 1,
     "gozlem": "ustteki gorselde ne var, birkac kelime",
     "kesik_yazi": "kartin herhangi bir kenarinda yarim kalan yazi varsa onu yaz, yoksa null",
     "logo_metni": "gorselin icinde oyun logosu/basligi varsa GORDUGUN HARFLERI yaz, yoksa null",
     "durum": "temiz | kirpik | okunmuyor | uygunsuz",
     "aciklama": "sorun varsa tek cumle, en fazla 12 kelime, kucuk harf"}
  ]
}"""


def kart_prompt(spec: dict, kart_sayisi: int) -> str:
    satirlar = []
    for sira, page in enumerate(spec["pages"][:kart_sayisi], 1):
        satirlar.append(f"Kart {sira} ({page['type']}): {sayfa_metni(page)[:160]}")

    return "\n".join([
        "Görselde bir Instagram gönderisinin kartları var, sol üstte numaralı.",
        "Her kartın üst kısmı oyun görseli, alt kısmı krem zeminde metin.",
        "",
        "ÖNCE BAK, SONRA KARAR VER. Her kart için önce 'gozlem' alanına",
        "üstteki görselde NE GÖRDÜĞÜNÜ yaz (birkaç kelime) - bu, karta",
        "gerçekten baktığından emin olmak için. Boş bırakma.",
        "",
        "Sonra 'kesik_yazi' alanına şunu yaz: kartın HERHANGİ BİR kenarında",
        "(üst, sol ya da sağ) yarısı kesilmiş bir yazı, tabela ya da logo",
        "var mı? VARSA okuyabildiğin kadarını yaz (\"...auto\", \"jack of he...\"",
        "gibi), yoksa null. Görselin içindeki büyük yazılara özellikle bak:",
        "oyun logosu, tabela, afiş, dükkan adı.",
        "",
        "Ayrıca 'logo_metni' alanına, görselin içinde bir oyun logosu ya da",
        "başlığı varsa GÖRDÜĞÜN HARFLERİ yaz - tahmin etme, ekranda ne",
        "yazıyorsa onu. Eksik görünüyorsa eksik haliyle yaz. Bu alanı kod",
        "oyunun gerçek adıyla karşılaştırıyor, yani doğru okuman yeterli;",
        "kesik olup olmadığına karar vermek senin işin değil.",
        "",
        "Sonra karar ver. SADECE şu üç kusurdan birini bildir:",
        "",
        *[f"  {ad} - {aciklama}" for ad, aciklama in KART_KARARLARI.items()],
        "",
        "BİLDİRME: renk tercihi, kompozisyon yorumu, \"daha iyi olabilirdi\",",
        "yazı tipi, boşluk miktarı, görselin konuyla ilgisi. Bunlar senin",
        "işin değil. Kart kusursuz olmasa bile bu üç kategoriye girmiyorsa",
        "\"temiz\" de.",
        "",
        "\"kirpik\" için ölçüt NET: kartın üst kenarında yarısı kesilmiş bir",
        "yazı ya da logo görünüyor mu. Görselin doğal olarak çerçeve dışında",
        "kalan kısmı kırpık DEĞİLDİR - sadece okunmaya çalışılan bir şeyin",
        "yarım kalması kırpıktır.",
        "",
        "KARTLAR:",
        *satirlar,
        "",
        "SADECE şu şemada JSON döndür:",
        KART_SEMA,
    ])


# Kesik logo tespitinde en az bu kadar harf okunmus olmali. Daha kisa
# parcalar tesadufen baska bir kelimenin eki olabiliyor.
LOGO_MIN_HARF = 4


def kesik_logo(okunan: str, tam_ad: str | None) -> str | None:
    """Okunan logo metni oyunun adinin YARISI mi? Deterministik.

    ⚠️ NEDEN KOD YAPIYOR: model logonun tam halini BILMIYOR. Olcum
    (20260831-onimusha-way-of-the-sword): kapakta logo sol kenardan
    kesilmis, ekranda "MUSHA / THE SWORD" yaziyordu. Model bunu dogru
    okudu - gozlem alanina "musa logosu" yazdi - ama "temiz" dedi,
    cunku "MUSHA" ona eksiksiz bir kelime gibi gorundu.

    Yani sorun modelin dikkatsizligi degil BILGI EKSIKLIGI: kesik olup
    olmadigini anlamak icin tam adi bilmek gerekiyor ve o bilgi bizde
    (`search_name`). Model OKUR, kod KARSILASTIRIR - "kirpik mi?" diye
    sormak yerine kesik yaziyi okutma dersinin tamamlanmis hali.

    Iki kenar da yakalaniyor: "musha" <- "onimusha" (bas kesik),
    "dawnwalke" <- "dawnwalker" (son kesik).
    """
    if not okunan or not tam_ad:
        return None
    tam_kelimeler = re.findall(r"[a-z0-9]+", tam_ad.lower())
    for parca in re.findall(r"[a-z0-9]+", okunan.lower()):
        if len(parca) < LOGO_MIN_HARF:
            continue
        for kelime in tam_kelimeler:
            if kelime == parca or len(kelime) <= len(parca):
                continue
            if kelime.endswith(parca) or kelime.startswith(parca):
                return f"{parca} <- {kelime}"
    return None


def kart_denetimi(spec: dict, cards: list[Path], model: str) -> list[dict]:
    """Basılmış kartları modele göster, kusurlu olanları döndür.

    Yardımcı modelde çalışıyor (günde 500 istek), yani tur sayısı kota
    yüzünden kısıtlı değil. Karar kod tarafında: model yalnızca kusuru
    bildiriyor, hangi görselin geleceğine kod karar veriyor.
    """
    sheet = ROOT / "state" / "img" / "_qa-kartlar.jpg"
    if render.render_kart_sheet(cards, sheet) != 0:
        return []
    try:
        cevap = writer.generate_gorsel(kart_prompt(spec, len(cards)), sheet, model)
    except (writer.GecersizCevap, SystemExit) as exc:
        print(f"kart denetimi yapilamadi: {exc}")
        return []
    finally:
        sheet.unlink(missing_ok=True)

    kusurlu = []
    for row in writer.liste_al(cevap, "kartlar"):
        if isinstance(row, dict) and row.get("gozlem"):
            kesik = (row.get("kesik_yazi") or "").strip()
            print(f"  kart {row.get('kart')}: {str(row['gozlem'])[:52]}"
                  + (f" | kesik: {kesik[:24]}" if kesik and kesik != "null" else ""))
        try:
            kart = int(row.get("kart"))
        except (TypeError, ValueError):
            continue
        if not 1 <= kart <= len(cards):
            continue

        # Modelin karari ONCE koda dogrulatiliyor: "temiz" dese bile
        # okudugu logo metni oyunun adinin yarisiysa kart kirpiktir.
        eksik = kesik_logo(row.get("logo_metni") or "", spec.get("search_name"))
        if eksik:
            print(f"  kart {kart}: logo kesik ({eksik})")
            kusurlu.append({"kart": kart, "durum": "kirpik",
                            "aciklama": f"logo yarim: {eksik}",
                            "kesik": row.get("logo_metni") or ""})
            continue

        durum = (row.get("durum") or "").strip()
        if durum not in KART_KARARLARI:
            continue  # "temiz" ve karar kumesi disi cevaplar dusuyor
        kusurlu.append({"kart": kart, "durum": durum,
                        "aciklama": (row.get("aciklama") or "").strip(),
                        "kesik": (row.get("kesik_yazi") or "")})
    return kusurlu


def kart_modu(spec: dict, draft_path: Path, kart_dizini: Path, args) -> int:
    """Kartlari denetle, kusurlu sayfalara havuzdan BASKA gorsel ata.

    Karar kod tarafinda: model "3. kart kirpik" diyor, hangi karenin
    gelecegine kod bakiyor - o sayfanin havuzdaki mevcut karesinden
    sonraki, henuz kullanilmamis kare.
    """
    # Yalnizca numarali kartlar: havuz.png gibi yardimci dosyalar
    # kart sanilip denetime giriyordu.
    cards = sorted(k for k in kart_dizini.glob("*.png")
                   if k.stem.isdigit())
    if not cards:
        print(f"kart bulunamadi: {kart_dizini}")
        return 1

    kusurlu = kart_denetimi(spec, cards, args.model)
    if not kusurlu:
        print("kart denetimi: temiz")
        return 0

    for row in kusurlu:
        print(f"  kart {row['kart']}: {row['durum']} - {row['aciklama']}")

    pool = spec.get("_image_pool") or []
    if not pool:
        print("havuz yok, gorsel degistirilemiyor")
        return 0

    simdiki = mevcut_secim(spec, pool)
    kullanilan = {s for s in simdiki if s}
    yeni_secim = list(simdiki)
    degisen = 0
    for row in kusurlu:
        i = row["kart"] - 1
        if i >= len(yeni_secim):
            continue
        # O sayfanin mevcut karesinden sonraki, kullanilmamis kare.
        bas = (simdiki[i] or 0)
        aday = next((n for n in range(bas + 1, len(pool) + 1) if n not in kullanilan),
                    None)
        if aday is None:
            aday = next((n for n in range(1, len(pool) + 1) if n not in kullanilan), None)
        if aday is None:
            print(f"  kart {row['kart']}: havuzda kullanilabilir baska kare yok")
            continue
        yeni_secim[i] = aday
        kullanilan.add(aday)
        degisen += 1
        print(f"  kart {row['kart']}: {simdiki[i]} -> {aday}")

    if not degisen:
        return 0
    if args.dry_run:
        print("--dry-run: taslak degistirilmedi")
        return 0

    spec["_gorsel_secimi"] = [str(y or s or 1) for y, s in zip(yeni_secim, simdiki)]
    draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"\n{degisen} sayfanin gorseli degistirildi -> {draft_path}")
    print("kartlari yenilemek icin: images.py + render.py")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="quest.post gorsel-sayfa eslestirme")
    ap.add_argument("draft")
    ap.add_argument("--dry-run", action="store_true", help="taslagi degistirme")
    ap.add_argument("--model", default=writer.HELPER_MODEL)
    ap.add_argument("--kartlar", default=None, metavar="KLASOR",
                    help="basilmis kartlari denetle (kirpma, okunurluk)")
    args = ap.parse_args()

    draft_path = Path(args.draft)
    spec = json.loads(draft_path.read_text(encoding="utf-8"))

    if args.kartlar:
        return kart_modu(spec, draft_path, Path(args.kartlar), args)

    pool = (spec.get("_image_pool") or [])[:MAX_HAVUZ]
    if len(pool) < 2:
        print("havuz yok veya tek kare: eslestirilecek bir sey yok")
        return 0

    # Kapak kurali icin ana oyun: havuzun ilk karesi her zaman konu oyunundan
    # geliyor (images.py once onu yaziyor, seri yedegi sonra ekleniyor).
    ana_oyun = pool[0].get("oyun")

    # Model havuzu kullanicinin /havuz ile gordugu izgarada goruyor.
    # JPEG: PNG hali 4 MB, base64 ile 5 MB'i asiyor.
    sheet = ROOT / "state" / "img" / f"_qa-{draft_path.stem}.jpg"
    kucuk = dict(spec, _image_pool=pool)
    if render.render_sheet(kucuk, sheet) != 0:
        print("havuz izgarasi basilamadi")
        return 1

    print(f"{len(spec['pages'])} sayfa, {len(pool)} kare modele soruluyor...")
    try:
        cevap = writer.generate_gorsel(build_prompt(spec, pool, ana_oyun),
                                       sheet, args.model)
    except (writer.GecersizCevap, SystemExit) as exc:
        # Eslestirme bir IYILESTIRME: patlarsa uretim durmamali, mevcut
        # (tip bazli) secim gecerli kalir.
        print(f"eslestirme yapilamadi, mevcut secim korunuyor: {exc}")
        return 0
    finally:
        sheet.unlink(missing_ok=True)

    secimler, notlar = dogrula(cevap, spec, pool, ana_oyun)
    for not_ in notlar:
        print(f"  {not_}")

    simdiki = mevcut_secim(spec, pool)
    degisen = [(i + 1, simdiki[i], s) for i, s in enumerate(secimler)
               if s is not None and s != simdiki[i]]

    print()
    for sira, eski, yeni in degisen:
        print(f"  sayfa {sira}: {eski} -> {yeni}")
    if not degisen:
        print("degisiklik yok: mevcut secim zaten uygun")
        return 0

    if args.dry_run:
        print("\n--dry-run: taslak degistirilmedi")
        return 0

    # Secim images.py'nin anladigi bicimde yaziliyor: sayfa sirasina gore
    # havuz numaralari. Bos kalan sayfa (model onermedi) mevcut karesini
    # korusun diye simdiki degeri yaziliyor.
    spec["_gorsel_secimi"] = [str(yeni or simdi or 1)
                              for yeni, simdi in zip(secimler, simdiki)]
    draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"\n{len(degisen)} sayfa degisti -> {draft_path}")
    print("kartlari yenilemek icin: images.py + render.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

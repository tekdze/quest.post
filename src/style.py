#!/usr/bin/env python3
"""Uslup filtresi. LLM ciktisini KOD denetler.

Iki isi var:
1. Yasak kalip avi (em-dash, "iste", emoji, buyuk harf, uc'lu liste kalibi...)
2. Rakam dogrulamasi - kaynak metninde gecmeyen sayi karta giremez

Ihlal bulursa write.py yeniden uretim ister. Bu dosya LLM cagirmaz,
tamamen deterministik: ayni girdi her zaman ayni sonucu verir.
"""

from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- yasaklar

BANNED_PHRASES = [
    "işte", "peki", "devrim niteliğinde", "oyunun kurallarını değiştiriyor",
    "ai destekli", "yapay zeka destekli", "çığır açan", "adeta", "tam anlamıyla",
    "kesinlikle bir", "bir başka deyişle", "sonuç olarak",
]

# Em-dash ve akrabalari. Turkce metinde kisa cizgi kullanilir.
BANNED_CHARS = {
    "—": "em-dash",
    "–": "en-dash",
    "…": "uc nokta karakteri (uc ayri nokta yazilmali)",
    "“": "egik tirnak", "”": "egik tirnak", "‘": "egik tirnak", "’": "egik tirnak",
}

# Yabanci ozel isimlere Turkce ek: okunusa gore secilir, LLM duzenli yaniliyor.
# Sol taraf yanlis, sag taraf dogru. Kucuk harf karsilastirmasi yapilir.
SUFFIX_FIXES = {
    "godot'yu": "godot'u",
    "godot'ya": "godot'a",
    "godot'nun": "godot'un",
    "godot'da": "godot'ta",
    "steam'da": "steam'de",
    "steam'dan": "steam'den",
    "valve'nin": "valve'ın",
    "valve'de": "valve'da",
    "unity'i": "unity'yi",
    "xbox'da": "xbox'ta",
    "xbox'dan": "xbox'tan",
    "ubisoft'da": "ubisoft'ta",
    "microsoft'da": "microsoft'ta",
    "epic'de": "epic'te",
    "epic'den": "epic'ten",
    "kickstarter'de": "kickstarter'da",
    "kickstarter'den": "kickstarter'dan",
}


# Duz metin olmayan alanlar: denetime girmez. "tier" bir kod (C/B/A/S),
# buyuk harf kurali ona uygulanamaz.
# Bu alanlar karta BASILMAZ, dolayisiyla uslup denetimine girmezler.
# search_name / image_candidates / series_fallback IGDB'de aranan tam
# Ingilizce oyun adlari; buyuk harf iceriyorlar ve icermek ZORUNDALAR.
# Denetime girdiklerinde "buyuk harf var" hatasi veriyor, write.py uc kez
# yeniden uretiyor ve LLM sonunda alani bos birakmayi ogreniyordu - yani
# filtre, gorsel bulma ozelligini sessizce sabote ediyordu.
# studio da ayni sebeple disarida: krediyi zaten images.py IGDB'nin sirket
# verisinden yaziyor, to_render_spec kucuk harfe ceviriyor.
# cikarim ayni sebeple disarida ve sebebi daha guclu: icindeki `alinti`
# alani KAYNAKTAN BIREBIR kopyalanmis Ingilizce metin. Denetime girseydi
# buyuk harf, isaretsiz Turkce ve yasak kalip kurallarinin ucune birden
# takilirdi - yani dogrulama mekanizmasinin kendisi filtreye yem olurdu.
NON_PROSE_KEYS = {"type", "image", "tier", "search_name", "image_candidates",
                  "series_fallback", "representative_games", "studio",
                  "cikarim", "dayanak", "bullet_dayanak"}

# 2) Yasak kalip avinda Turkce isaretler yok sayilir: LLM "iste" yazip
# noktalari eksik biraktiginda filtre onu da yakalamali.
TR_FOLD = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    "â": "a", "î": "i",
})


# Turkceye ozgu harfler. Uzun bir metinde bunlardan hic yoksa metin
# isaretsiz yazilmis demektir.
TR_CHARS = set("ışğüöçİIŞĞÜÖÇ") - set("I")


def fold(text: str) -> str:
    return text.translate(TR_FOLD).lower()


def has_emoji(text: str) -> bool:
    for ch in text:
        if unicodedata.category(ch) == "So":
            return True
        if 0x1F000 <= ord(ch) <= 0x1FAFF:
            return True
    return False


def strings_of(spec: dict) -> list[tuple[str, str]]:
    """Post tarifindeki tum metin alanlarini (yol, metin) olarak dolas."""
    found: list[tuple[str, str]] = []

    def walk(node, path: str) -> None:
        if isinstance(node, str):
            found.append((path, node))
        elif isinstance(node, dict):
            for key, value in node.items():
                if key.startswith("_") or key in NON_PROSE_KEYS:
                    continue
                walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(spec, "")
    return found


# ------------------------------------------------------------ kalip avi

def check_patterns(spec: dict) -> list[str]:
    problems: list[str] = []

    for path, text in strings_of(spec):
        for char, name in BANNED_CHARS.items():
            if char in text:
                problems.append(f"{path}: yasak karakter {name} ({char!r})")

        folded = fold(text)
        for phrase in BANNED_PHRASES:
            if re.search(rf"(^|\W){re.escape(fold(phrase))}(\W|$)", folded):
                problems.append(f"{path}: yasak kalip \"{phrase}\"")

        if has_emoji(text):
            problems.append(f"{path}: emoji var")

        # Hesabin uslubu tamamen kucuk harf.
        uppers = [c for c in text if c.isalpha() and c.upper() == c and c.lower() != c]
        if uppers:
            problems.append(f"{path}: buyuk harf var ({''.join(uppers[:6])})")

        if text.count("#") > 2:
            problems.append(f"{path}: 2'den fazla hashtag")

        # Isaretsiz Turkce: LLM "ayni", "hazirlaniyor", "buyuk" yaziyor.
        # Eskiden kural "HIC isaret yok" idi ve fazla gevsekti: tek bir
        # "minyatür" kelimesi, gerisi tamamen isaretsiz olan 185 karakterlik
        # bir paragrafi gecirebiliyordu (olcum 2026-08-31). Artik YOGUNLUK
        # olculuyor - duzgun Turkce metinde isaretli harf seyrek degildir.
        if len(text) > 60:
            gereken = max(1, len(text) // 45)
            varolan = sum(1 for ch in text if ch in TR_CHARS)
            if varolan < gereken:
                problems.append(f"{path}: Turkce isaretler eksik "
                                f"({varolan}/{gereken}), isaretsiz yazilmis")

        # Ucluk kalibi: "a, b ve c" - metnin her yerinde tekrarlayan bir tik.
        if re.search(r"\w+, [^,.]{3,40}, [^,.]{3,40} ve ", folded):
            problems.append(f"{path}: uc'lu liste kalibi (\"a, b ve c\")")

    # Soru cumlesiyle baslamak yasak. Son sayfanin sorusu tasarimin parcasi,
    # o haric tutulur.
    for page in spec.get("pages", []):
        if page.get("type") == "outro":
            continue
        for field in ("title", "paragraph"):
            value = page.get(field)
            if not value:
                continue
            first = re.split(r"(?<=[.!?])\s", value.strip(), maxsplit=1)[0]
            if first.endswith("?"):
                problems.append(f"{page['type']}.{field}: soru cumlesiyle basliyor")

    return problems


# Evet/hayir sorusu kalibi: soru ekine KISI eki eklenmis haller.
# "ister miydiniz", "dener misin", "merak ediyor musun" - cevabi "evet"
# olan sorular, okurun soyleyecek bir seyi kalmiyor.
# Cipilak "mi/mi" YASAK DEGIL: "kotu olmak mi, sevimli olmak mi" iyi bir
# tercih sorusu ve ayni eki tasiyor.
EVET_HAYIR = re.compile(
    r"\b(mı|mi|mu|mü)(sın|sin|sun|sün|sınız|siniz|sunuz|sünüz|ydı|ydi|ydu|ydü)\w*",
    re.IGNORECASE)

# Okura resmi cogul hitap. Kartlar kucuk harfli ve samimi; "siz" dili
# tasarimla celisiyor ve metni bulten gibi gosteriyor.
SIZ_DILI = re.compile(r"\w{3,}(nız|niz|nuz|nüz|sınız|siniz|sunuz|sünüz)\b",
                      re.IGNORECASE)
# "deniz" gibi kelimeler yanlislikla yakalanmasin.
SIZ_ISTISNA = {"deniz", "peniz", "beniz"}

# Gazeteci doldurmalari. Kok halinde araniyor: "yapım", "yapımın",
# "yapımı" hepsi yakalanir ama "yapımcı" (gercek bir meslek) muaf.
GAZETECI_KALIPLARI = [
    (re.compile(r"(^|\W)yapim(?!ci)\w*", re.IGNORECASE), "yapım (oyuna oyun de)"),
    (re.compile(r"(^|\W)soz konusu", re.IGNORECASE), "söz konusu"),
    (re.compile(r"(^|\W)dikkat cek\w*", re.IGNORECASE), "dikkat çekiyor"),
    (re.compile(r"(^|\W)imza at\w*", re.IGNORECASE), "imza attı"),
    (re.compile(r"(^|\W)hayata gecir\w*", re.IGNORECASE), "hayata geçiriyor"),
]

# Maddede fiil var mi? Turkce fiiller bu eklerden birini tasiyor.
# Kisa gecmis zaman ekleri ("dı", "di") LISTEDE YOK: "kaydıyla" gibi
# isimlerde de geciyor ve yanlis onay veriyorlardi.
FIIL_ISARETLERI = ("yor", "acak", "ecek", "abilir", "ebilir",
                   "malı", "meli", "mış", "miş", "muş", "müş")


def check_ses(spec: dict) -> list[str]:
    """Ses ve hitap denetimi: son sayfa sorusu, çağrı, maddeler.

    Dar tutuluyor - yalnızca okura seslenilen ve kalıplaşan yerler.
    Gövde metnine uygulansa filtre çok sıkı olur ve üç deneme de yanar
    (2026-08-31'de büyük harf kuralı yüzünden bir üretim böyle düştü).
    """
    problems: list[str] = []

    for page in spec.get("pages", []):
        if not isinstance(page, dict):
            continue

        if page.get("type") == "outro":
            soru = (page.get("question") or "").strip()
            if soru and EVET_HAYIR.search(soru):
                problems.append(
                    "outro.question: cevabı \"evet\" olan soru "
                    "(\"... misin / miydiniz\"). Düşünmeyi gerektiren soru yaz")
            cagrilar = page.get("ctas") or []
            for sira, cagri in enumerate(cagrilar):
                if not isinstance(cagri, str):
                    continue
                if fold(cagri) in fold(soru) or fold(soru) in fold(cagri):
                    problems.append(f"outro.ctas[{sira}]: soruyu tekrarlıyor")
                # Her posta uyan cagri = her postta ayni cumle. Hesabi
                # otomatik gosteren sey buydu.
                if "yorumlarda paylas" in fold(cagri) or "yorum yaz" in fold(cagri):
                    problems.append(
                        f"outro.ctas[{sira}]: kalıp çağrı (\"yorumlarda "
                        f"paylaş\"). Bu posta özel bir şey söyle")

        # Maddeler etiket degil cumle olmali.
        for sira, madde in enumerate(page.get("bullets") or []):
            if not isinstance(madde, str) or not madde.strip():
                continue
            if not any(isaret in fold(madde) for isaret in
                       (fold(x) for x in FIIL_ISARETLERI)):
                problems.append(
                    f"{page.get('type')}.bullets[{sira}]: fiil yok, etiket gibi "
                    f"(\"{madde[:34]}\")")

    # "siz" dili: yalnizca okura seslenen alanlarda.
    for page in spec.get("pages", []):
        if not isinstance(page, dict) or page.get("type") != "outro":
            continue
        for alan, metin in (("question", page.get("question")),
                            *((f"ctas[{i}]", c) for i, c in
                              enumerate(page.get("ctas") or []))):
            if not isinstance(metin, str):
                continue
            for kelime in re.findall(r"\w+", metin):
                if kelime.lower() in SIZ_ISTISNA:
                    continue
                if SIZ_DILI.fullmatch(kelime):
                    problems.append(f"outro.{alan}: \"siz\" dili (\"{kelime}\"), "
                                    f"okura \"sen\" diye hitap et")
                    break

    return problems


def check_gazeteci(spec: dict) -> list[str]:
    """Haber bülteni doldurmaları. Hesabın sesi değil."""
    problems: list[str] = []
    for path, text in strings_of(spec):
        folded = fold(text)
        for desen, ad in GAZETECI_KALIPLARI:
            if desen.search(folded):
                problems.append(f"{path}: gazeteci kalıbı \"{ad}\"")
    return problems


def check_suffixes(spec: dict) -> list[str]:
    problems: list[str] = []
    for path, text in strings_of(spec):
        low = text.lower()
        for wrong, right in SUFFIX_FIXES.items():
            if wrong == right:
                continue
            if wrong in low:
                problems.append(f"{path}: \"{wrong}\" yerine \"{right}\" yazilmali")
    return problems


# --------------------------------------------------------- rakam denetimi

def digit_runs(text: str) -> list[str]:
    """Metindeki rakam dizilerini cikar. '18 milyon' -> ['18']"""
    return re.findall(r"\d+", text.replace(".", "").replace(",", ""))


# Kaynak Ingilizce, cikti Turkce: kaynakta "two hours" yazarken cikti
# "2 saat" oluyor. Rakam denetimi bunu uydurma sanmasin diye sayi
# kelimeleri de rakama cevrilip izinli kumeye ekleniyor.
NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20",
    "thirty": "30", "forty": "40", "fifty": "50", "sixty": "60",
    "hundred": "100", "thousand": "1000", "million": "1000000",
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "half": "30",  # "half an hour" -> 30 dk
}


def check_numbers(spec: dict, source_text: str) -> list[str]:
    """Kaynak metninde gecmeyen sayi karta giremez.

    LLM sayi uydurur; bu en tehlikeli hata tipi cunku inandirici gorunuyor.
    """
    allowed = set(digit_runs(source_text))
    words = set(re.findall(r"[a-z]+", source_text.lower()))
    allowed |= {NUMBER_WORDS[w] for w in words & NUMBER_WORDS.keys()}
    problems: list[str] = []

    for path, text in strings_of(spec):
        for number in digit_runs(text):
            if number in allowed:
                continue
            # Kaynakta "18m" varsa "18" gecerli sayilir: yukaridaki cikarim
            # zaten rakam dizisi bazli, yani bu kontrol sadece tam yeni
            # sayilari yakalar.
            problems.append(f"{path}: \"{number}\" kaynak metinde yok")
    return problems


def review(spec: dict, source_text: str) -> list[str]:
    """Tum denetimler. Bos liste = temiz."""
    return (check_patterns(spec) + check_suffixes(spec)
            + check_ses(spec) + check_gazeteci(spec)
            + check_numbers(spec, source_text) + check_tekrar(spec))


def replace_strings(spec: dict, yeni: list[str]) -> dict:
    """`strings_of` ile AYNI sırada dolaşıp metinleri değiştir.

    Sıra bazlı, yol bazlı değil: "pages[1].bullets[0]" gibi yolları
    ayrıştırmak gereksiz kırılganlık olurdu. İki fonksiyon aynı gezinme
    kuralını paylaşıyor - biri değişirse diğeri de değişmeli.
    """
    kalan = iter(yeni)

    def walk(node):
        if isinstance(node, str):
            return next(kalan, node)
        if isinstance(node, dict):
            return {k: (v if k.startswith("_") or k in NON_PROSE_KEYS else walk(v))
                    for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(spec)


def isaretsiz(text: str) -> bool:
    """Türkçe işaretleri düşmüş uzun metin mi?

    Ölçü YOĞUNLUK: tek bir "minyatür" kelimesi, gerisi tamamen işaretsiz
    olan bir paragrafı geçiremesin (ölçüm 2026-08-31). `check_patterns`
    ile aynı eşik.
    """
    if len(text) <= 40:
        return False
    return sum(1 for ch in text if ch in TR_CHARS) < max(1, len(text) // 45)


def tr_lower(text: str) -> str:
    """Küçük harfe çevir. "İ" özel: düz `.lower()` onu bozuk üretiyor.

    "I" bilerek "i"ye düşüyor, "ı"ya değil: karta basılan büyük harfli
    kelimelerin neredeyse tamamı İngilizce oyun/şirket adı ("Iron Man",
    "GTA"). Türkçe kuralı uygulasak "ıron man" çıkardı.
    """
    return text.replace("İ", "i").lower()


def autofix_lowercase(spec: dict) -> dict:
    """Büyük harfleri düzelt. Yeniden üretim istemeye değmez.

    Ölçüldü (2026-08-31): bir üretimde üç denemenin ikisi "game: buyuk
    harf var" yüzünden yandı, model her seferinde "Total War: Warhammer
    40,000" yazdı. Kural mutlak ("tamamen küçük harf, tek istisna yok"),
    yani düzeltmesi mekanik - ek hatalarında olduğu gibi.

    NON_PROSE_KEYS'e DOKUNMAZ: `search_name` ve arkadaşları karta
    basılmıyor, İngilizce oyun adları ve büyük harf içermek zorundalar.
    """
    def walk(node, key: str = ""):
        if isinstance(node, str):
            return tr_lower(node)
        if isinstance(node, dict):
            return {k: (v if k in NON_PROSE_KEYS or k.startswith("_") else walk(v, k))
                    for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        return node

    return walk(spec)


def autofix_suffixes(spec: dict) -> dict:
    """Ek hatalarini yeniden uretim istemeden duzelt.

    Yeniden uretim pahali ve sonucu belirsiz; ek hatasi ise mekanik bir
    duzeltme. Sadece sozlukte olan kaliplar degistirilir.
    """
    def fix(text: str) -> str:
        for wrong, right in SUFFIX_FIXES.items():
            if wrong != right:
                text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
        return text

    def walk(node):
        if isinstance(node, str):
            return fix(node)
        if isinstance(node, dict):
            return {k: (v if k in ("type", "image") else walk(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(spec)


# ----------------------------------------------------------- tekrar avi

# Ayni fikrin farkli kelimelerle tekrar edilmesi filtreye takilmiyordu.
# Olcum (20260831-the-blood-of-dawnwalker): "karanlik" dort, "fikir" uc
# ayri alanda gecti; post ilerledikce yeni bir sey soylemiyordu ama hicbir
# kural ihlal edilmemisti. Kural yoklugu degil, kural TURU eksikti:
# mevcut denetimlerin hepsi TEK metne bakiyor, hicbiri metinler ARASINA
# bakmiyordu.
TEKRAR_ESIK = 3          # ayni kok bu kadar AYRI alanda gecerse tekrar
KOK_UZUNLUK = 5          # Turkce eklemeli: ilk 5 harf govdeyi yakaliyor
                         # ("karanlik/karanliga" -> "karan", "fikirlerini" -> "fikir")
                         # 4 harf cok kaba: "karanlik" ile "karakter" cakisiyordu

# Tekrari dogal olan kelimeler. Bunlari saymak gurultu uretir: bir oyun
# haberinde "oyun" ve "oyuncu" her sayfada gecebilir.
TEKRAR_MUAF = {
    "oyunu", "oyunc", "oyunl", "oyuna", "oyund", "stüdy", "sürüm", "şirke",
    "kayna", "yapım", "ekibi", "ekipl", "insan", "kulla", "yenid", "zaman",
    "birli", "kadar", "sonra", "önced", "bunun", "böyle", "başka", "kendi",
    "diğer", "olara", "olduğ", "olaca", "değil", "ayrıc", "hepsi", "aynıs",
}


def _koklar(text: str) -> set[str]:
    """Metindeki icerik kelimelerinin kaba koklerini cikar.

    Turkce eklemeli oldugu icin tam eslesme ise yaramaz: "karanlik",
    "karanliga", "karanligin" ayni kelimedir ama uc farkli dizedir.
    Govde olarak ilk KOK_UZUNLUK harf aliniyor - basit ama olculdugu
    kadariyla yeterli, ve deterministik.
    """
    kokler = set()
    for word in re.findall(r"[a-zçğıöşü]+", fold(text).replace("i̇", "i")):
        if len(word) < KOK_UZUNLUK:
            continue          # kisa kelimeler zaten edat/baglac
        kokler.add(word[:KOK_UZUNLUK])
    return kokler


def check_tekrar(spec: dict) -> list[str]:
    """Kartlar arasi fikir tekrari. LLM cagirmaz.

    Yalnizca `pages` altina bakar: caption ayri bir yuzey, orada haberin
    baglamini vermek icin kart kelimelerinin gecmesi normal.

    Oyunun kendi adi muaf: ondan bahsetmek kacinilmaz.
    """
    muaf = set(TEKRAR_MUAF)
    for alan in ("game", "search_name"):
        muaf |= _koklar(str(spec.get(alan) or ""))

    sayac: dict[str, list[str]] = {}
    for path, text in strings_of(spec):
        # YALNIZCA GOVDE. Baslik ve son sayfa sorusu haric: haberin konu
        # kelimesinin kapakta, bir paragrafta ve soruda gecmesi tekrar
        # degil, tutarlilik ("sizinti" haberinde "sizinti" gecer).
        # Olculdu: bu ayrim yapilmadan dokuz taslagin dokuzu da isaretlendi,
        # yani filtre hicbir sey ayirt etmiyordu. credit de disarida -
        # sayfa basina yazilan ayni studyo adi tekrar degil.
        if ".paragraph" not in path and ".bullets[" not in path:
            continue
        for kok in _koklar(text):
            if kok in muaf:
                continue
            sayac.setdefault(kok, []).append(path)

    problems = []
    for kok, yerler in sorted(sayac.items()):
        if len(yerler) >= TEKRAR_ESIK:
            problems.append(
                f"tekrar: \"{kok}...\" koku {len(yerler)} ayri alanda geciyor "
                f"({', '.join(y.split('.', 1)[-1] for y in yerler[:4])}). "
                f"her kart yeni bir sey soylemeli")
    return problems

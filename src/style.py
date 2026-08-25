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
NON_PROSE_KEYS = {"type", "image", "tier"}

# 2) Yasak kalip avinda Turkce isaretler yok sayilir: LLM "iste" yazip
# noktalari eksik biraktiginda filtre onu da yakalamali.
TR_FOLD = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
    "â": "a", "î": "i",
})


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
        low = text.lower()

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


def check_numbers(spec: dict, source_text: str) -> list[str]:
    """Kaynak metninde gecmeyen sayi karta giremez.

    LLM sayi uydurur; bu en tehlikeli hata tipi cunku inandirici gorunuyor.
    """
    allowed = set(digit_runs(source_text))
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
    return check_patterns(spec) + check_suffixes(spec) + check_numbers(spec, source_text)


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

"""Arabic feminine ordinal words (1-99) <-> integer, for parsing article/chapter headers in the
real KSA VAT Implementing Regulations, which numbers articles by spelled-out ordinal ("المادة
التاسعة" — "Article Nine") rather than digits. "المادة" (article) and "الفصل" then a form
of "الجزء"/chapter-word are grammatically feminine/masculine in different ways in Saudi legal
drafting, but articles consistently use the feminine ordinal form seen in the real corpus
("التاسعة" not "التاسع"), so only the feminine set is built.

This is a closed, finite vocabulary (not open-ended NLP) — every legal document in this corpus
tops out under 100 articles — so a generated lookup table, verified against known values read
directly from the real PDF's table of contents, is lower-risk than a general Arabic numeral
parser.
"""
from __future__ import annotations

import re

_ONES = {
    1: "الأولى", 2: "الثانية", 3: "الثالثة", 4: "الرابعة", 5: "الخامسة",
    6: "السادسة", 7: "السابعة", 8: "الثامنة", 9: "التاسعة",
}
# In a compound ("twenty-one" etc.) "one" takes a different form: الحادية, not الأولى.
_ONES_COMPOUND = {**_ONES, 1: "الحادية"}
_TENS = {
    10: "العاشرة", 20: "العشرون", 30: "الثلاثون", 40: "الأربعون", 50: "الخمسون",
    60: "الستون", 70: "السبعون", 80: "الثمانون", 90: "التسعون",
}

_TASHKEEL_RE = re.compile(r"[ؐ-ًؚ-ٟۖ-ۜ۟-۪ۨ-ۭ]")
_ALEF_RE = re.compile(r"[إأآٱ]")


def _normalize(s: str) -> str:
    """Strip diacritics and normalize alef/hamza variants — PDF extraction and hand-typed
    ordinal text vary in exactly these ways, and a mismatch here would silently drop a real
    article rather than mis-number it (find_ordinal returns None, never a guess)."""
    s = _TASHKEEL_RE.sub("", s or "")
    s = _ALEF_RE.sub("ا", s)
    s = s.replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"\s+", " ", s).strip()


# Masculine forms — "الفصل" (chapter) is grammatically masculine, unlike "المادة" (article),
# so chapter headers use "الثالث" (third) not the feminine "الثالثة" used for articles. The
# tens (20, 30, ...) are gender-invariant, so only the ones/teens tables differ from the
# feminine set above.
_ONES_M = {
    1: "الأول", 2: "الثاني", 3: "الثالث", 4: "الرابع", 5: "الخامس",
    6: "السادس", 7: "السابع", 8: "الثامن", 9: "التاسع",
}
_ONES_COMPOUND_M = {**_ONES_M, 1: "الحادي"}


def _build_table(ones: dict[int, str], ones_compound: dict[int, str],
                 teen_suffix: str) -> dict[str, int]:
    table: dict[str, int] = {}
    for n, word in ones.items():
        table[_normalize(word)] = n
    for n, word in _TENS.items():
        table[_normalize(word)] = n
    for tens in (20, 30, 40, 50, 60, 70, 80, 90):
        for units in range(1, 10):
            n = tens + units
            if n >= 100:
                continue
            word = f"{ones_compound[units]} و{_TENS[tens]}"
            table[_normalize(word)] = n
    for units in range(1, 10):  # 11-19: "<ones-compound> عشر[ة]"
        n = 10 + units
        word = f"{ones_compound[units]} {teen_suffix}"
        table[_normalize(word)] = n
    return table


ORDINAL_TO_INT = _build_table(_ONES, _ONES_COMPOUND, "عشرة")           # feminine — articles
ORDINAL_TO_INT_MASCULINE = _build_table(_ONES_M, _ONES_COMPOUND_M, "عشر")  # masculine — chapters


_TRAILING_NOTE_RE = re.compile(
    r"\s*(?:\((?:مكرر|مكررة)(?:\s*\d*)?\)|(?:مكرر|مكررة)(?:\s*\(\s*\d+\s*\))?)\s*$")


def parse_ordinal(text: str) -> int | None:
    """"التاسعة" -> 9, "الحادية عشرة" -> 11, "الثانية والعشرون" -> 22. Returns None rather
    than guessing when the text doesn't match a known ordinal — a silent wrong number is worse
    than a dropped article that gets flagged for manual review.

    Tolerates two real extraction artifacts seen in the actual ZATCA PDF: a trailing "(مكرر)"
    ("repeated"/bis) amendment-article marker, stripped and reported separately by the caller
    rather than folded into the base article's number; and a stray space PDF kerning sometimes
    inserts inside a single ordinal word (e.g. "الس ادسة" for "السادسة") — collapsed away only
    as a fallback, after an exact match has already failed.
    """
    return _lookup(text, ORDINAL_TO_INT)


def parse_ordinal_masculine(text: str) -> int | None:
    """Same as parse_ordinal, but against the masculine ordinal forms used by "الفصل"
    (chapter) headers — "الثالث" (third), not the feminine "الثالثة" articles use."""
    return _lookup(text, ORDINAL_TO_INT_MASCULINE)


def _lookup(text: str, table: dict[str, int]) -> int | None:
    stripped = _TRAILING_NOTE_RE.sub("", text or "")
    exact = table.get(_normalize(stripped))
    if exact is not None:
        return exact
    despaced = _normalize(stripped).replace(" ", "")
    for key, val in table.items():
        if key.replace(" ", "") == despaced:
            return val
    return None


def repeated_marker_suffix(text: str) -> str | None:
    """None if the ordinal carries no "(مكرر)" marker. "" for a bare repeated/bis article
    ("Article 32 (مكرر)", inserted by amendment between 32 and 33). A digit string for a
    *further* repeated instance ("مكرر (2)" — a second bis article for the same base number,
    distinct from the first) — so "36 (مكرر)" and "36 مكرر (2)" get different unit_ids rather
    than colliding on the same one."""
    m = _TRAILING_NOTE_RE.search(text or "")
    if not m:
        return None
    digits = re.search(r"\d+", m.group(0))
    return digits.group(0) if digits else ""

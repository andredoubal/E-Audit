"""Arabic ordinal-word -> integer, verified against values read directly from the real ZATCA
Implementing Regulations table of contents (Article 9 = "التاسعة", Article 12 = "الثانية عشرة",
etc.) — not invented test data."""
from __future__ import annotations

import pytest

from app.regulatory.arabic_ordinals import parse_ordinal

CASES = [
    ("الأولى", 1), ("الثانية", 2), ("الثالثة", 3), ("التاسعة", 9),
    ("العاشرة", 10), ("الحادية عشرة", 11), ("الثانية عشرة", 12),
    ("التاسعة عشرة", 19), ("العشرون", 20), ("الحادية والعشرون", 21),
    ("التاسعة والعشرون", 29), ("الثلاثون", 30), ("الرابعة والسبعون", 74),
    ("الثمانون", 80), ("التاسعة والتسعون", 99),
]


@pytest.mark.parametrize("word,expected", CASES)
def test_known_ordinals_parse_correctly(word, expected):
    assert parse_ordinal(word) == expected


def test_diacritics_and_alef_variants_are_normalized():
    assert parse_ordinal("التّاسعة") == 9          # with a shadda diacritic
    assert parse_ordinal("الاولى") == 1             # bare alef instead of hamza-on-alef


def test_unrecognised_text_returns_none_rather_than_a_guess():
    assert parse_ordinal("ليست عبارة عن رقم") is None
    assert parse_ordinal("") is None
    assert parse_ordinal("Article 9") is None


def test_every_ordinal_one_to_ninety_nine_is_covered():
    from app.regulatory.arabic_ordinals import ORDINAL_TO_INT

    assert sorted(set(ORDINAL_TO_INT.values())) == list(range(1, 100))

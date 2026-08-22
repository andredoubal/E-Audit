"""Read the Arabic edition — for the article numbers, and for what has changed since.

Two jobs, and neither is about wording. The English edition is what an auditor reads; this one
is consulted for the two things the English cannot supply.

**The numbers.** English article headers carry their number as an image (see `extract_en`), so
English numbering is derived from position. Arabic headers carry the number in words —
`المادة الرابعة عشرة` — so parsing them gives a second, independent numbering that the first
can be checked against. Agreement is what makes the numbering safe to cite; disagreement is
reported rather than resolved by preferring one.

**What is out of date.** The English edition is ZATCA's Eighth Edition of November 2021, and
says on its own cover that it is an unofficial translation. The Arabic carries amendments
through November 2024. So an article whose Arabic text was amended after the English edition
was published has English wording that no longer states the current rule — Article 14, the
charging provision, is one of them. Citing it without saying so would put superseded wording
under a finding, which is exactly the kind of error that surfaces on appeal.

Extraction needs bidi reconstruction: this PDF's text comes out in Arabic presentation forms in
visual order, so a plain read finds no articles at all. `get_display` plus NFKC recovers it.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .arabic_ordinals import parse_ordinal

# `المادة <ordinal>: <title>` — .search rather than .match because extraction leaves stray
# footnote digits and page numbers at the start of some lines.
_ARTICLE = re.compile(r"المادة\s+([^:\d]{2,45}?(?:\([^)]*\))?)\s*:\s*(.*)")
_TOC_LEADER = re.compile(r"\.{3,}")          # contents lines run to a page number with dots

# A footnote recording an amendment, e.g.
#   "تم تعديل الفقرة بموجب قرار مجلس إدارة ... وتاريخ 17 جمادى الأولى 1446هـ الموافق 19 نوفمبر 2024م"
_AMENDMENT = re.compile(r"تم\s+(?:تعديل|إضافة|حذف)")
_GREGORIAN = re.compile(r"(19|20)\d\d\s*م")

ENGLISH_EDITION_YEAR = 2021          # ZATCA English Eighth Edition, 09/11/2021


@dataclass
class ArabicArticle:
    number: int
    title: str
    line: int
    last_amended_year: int | None = None

    @property
    def stale_in_english(self) -> bool:
        return bool(self.last_amended_year and self.last_amended_year > ENGLISH_EDITION_YEAR)


def reconstruct(pdf_path: str | Path) -> list[str]:
    """Bidi-reorder and normalise every line. Without this the file yields no articles."""
    import pdfplumber
    from bidi.algorithm import get_display

    out: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").split("\n"):
                if line.strip():
                    out.append(unicodedata.normalize("NFKC", get_display(line, base_dir="L")))
    return out


def articles(pdf_path: str | Path) -> list[ArabicArticle]:
    """Numbered articles from the body, with the year each was last amended."""
    lines = reconstruct(pdf_path)
    found: list[ArabicArticle] = []
    seen: set[int] = set()

    for n, line in enumerate(lines):
        if _TOC_LEADER.search(line):
            continue                                  # table of contents, not the body
        m = _ARTICLE.search(line)
        if not m:
            continue
        number = parse_ordinal(m.group(1).strip())
        if number is None or number in seen:
            continue                                  # never guess a number we cannot parse
        seen.add(number)
        found.append(ArabicArticle(number=number, title=m.group(2).strip(), line=n))

    # Amendment footnotes sit at the foot of the page they annotate, so each belongs to the
    # article whose text it falls within. Attributing by position is what lets a per-article
    # "amended in 2024" flag exist at all.
    found.sort(key=lambda a: a.line)
    for i, art in enumerate(found):
        end = found[i + 1].line if i + 1 < len(found) else len(lines)
        years = [int(y.group(0)[:4]) for line in lines[art.line:end]
                 if _AMENDMENT.search(line) for y in _GREGORIAN.finditer(line)]
        art.last_amended_year = max(years) if years else None

    return sorted(found, key=lambda a: a.number)

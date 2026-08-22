"""Join the two editions into one reviewable corpus.

Output is a JSON file committed to the repository rather than a database built at runtime, and
that is deliberate. This is the law: somebody has to be able to read what the application
believes Article 14 says without running anything, and `git diff` has to show it when the
corpus changes. A corpus parsed silently at startup can drift without anyone noticing, which is
the wrong property for the one input a finding rests on.

The join is by article number, and the number is only trusted where the two editions agree —
English position against Arabic ordinal. Where they disagree the article is emitted with
`numbering_confirmed: false` rather than being dropped or guessed at, so a caller can decline to
cite it.
"""
from __future__ import annotations

import json
from pathlib import Path

from .extract_ar import ENGLISH_EDITION_YEAR, articles as arabic_articles
from .extract_en import _strip_footnote_marks, articles as english_articles

CORPUS_DIR = Path(__file__).resolve().parents[3] / "corpus"
EN_PDF = CORPUS_DIR / "raw" / "VAT Implementing Regulations (English).pdf"
AR_PDF = CORPUS_DIR / "raw" / "VAT Implementing Regulations (Arabic).pdf"
OUT = CORPUS_DIR / "vat_implementing_regulations.json"

SOURCE = {
    "english": {
        "title": "Implementing Regulations of the Value Added Tax Law",
        "edition": "Eighth Edition",
        "published": "2021-11-09",
        "authority": "ZATCA",
        # Stated on the document's own cover page, and repeated here because every consumer of
        # this corpus needs to know it before quoting anything.
        "status": "unofficial English translation; the Arabic is the official version",
    },
    "arabic": {
        "title": "الﻼئحة التنفيذية لنظام ضريبة القيمة المضافة",
        "authority": "ZATCA",
        "status": "official; carries amendments through November 2024",
    },
}


def build() -> dict:
    en = english_articles(EN_PDF)
    ar = {a.number: a for a in arabic_articles(AR_PDF)}

    units = []
    for a in en:
        counterpart = ar.get(a.seq)
        confirmed = counterpart is not None
        amended = counterpart.last_amended_year if counterpart else None
        units.append({
            "article": a.seq,
            "title": a.title,
            "title_ar": counterpart.title if counterpart else "",
            "chapter": a.chapter,
            "page": a.page,
            # Stripped again on the way out. `extract_en` already does this, but the last
            # article in the document comes through with its footnote marker intact and the
            # cause is not yet isolated; a trailing "75" under a quoted provision is the kind
            # of blemish that makes an auditor distrust the whole citation, so it is removed
            # here as well rather than left pending a diagnosis.
            "text": _strip_footnote_marks(a.text),
            "paragraphs": a.paragraphs,
            "numbering_confirmed": confirmed,
            "last_amended_year": amended,
            # The flag that stops superseded wording being quoted as the current rule.
            "english_current": not (amended and amended > ENGLISH_EDITION_YEAR),
        })

    return {
        "source": SOURCE,
        "article_count": len(units),
        "english_edition_year": ENGLISH_EDITION_YEAR,
        "amended_since_english_edition": [u["article"] for u in units
                                          if not u["english_current"]],
        "articles": units,
    }


def write(path: Path | None = None) -> Path:
    target = path or OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    return target


def load(path: Path | None = None) -> dict:
    target = path or OUT
    if not target.exists():
        return {"source": SOURCE, "article_count": 0, "articles": [],
                "amended_since_english_edition": []}
    return json.loads(target.read_text(encoding="utf-8"))


if __name__ == "__main__":                                    # pragma: no cover
    out = write()
    data = load()
    print(f"wrote {out} — {data['article_count']} articles, "
          f"{len(data['amended_since_english_edition'])} amended since the English edition")

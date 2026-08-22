"""Resolve a finding's outcome code to the article behind it.

Deterministic, and deliberately so. The corpus is loaded once, the mapping in `basis.py` says
which provision founds which outcome, and this module joins the two and reports what it found —
including when it found nothing.

`state` is the field that matters:

* **found** — the article is in the corpus, its numbering was confirmed by both editions, and
  its English text is current.
* **needs-validation** — the article is there and the numbering is confirmed, but the English
  edition predates the current Arabic, so the wording shown is superseded. Article 14 is in
  this state, and it founds six of the twelve outcomes, so this is the common case rather than
  an edge one.
* **not-found** — no basis is recorded for the code, or the article is missing from the corpus.
  Stored as a real answer, never as silence: "the applicable provision could not be identified"
  is something an auditor needs to see, and an empty field looks identical to nobody having
  looked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from . import basis as basis_table
from .build import load

FOUND = "found"
NEEDS_VALIDATION = "needs-validation"
NOT_FOUND = "not-found"

MAX_QUOTE = 700          # enough to read the operative words; not the whole article


@dataclass
class Citation:
    state: str
    outcome_code: str = ""
    article: int | None = None
    label: str = ""                  # "Article 14"
    title: str = ""
    chapter: str = ""
    establishes: str = ""            # the editorial gloss from the basis table
    consequence: str = ""
    text: str = ""                   # the article's own words, from the English edition
    english_current: bool = True
    last_amended_year: int | None = None
    supporting: list[dict] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {"state": self.state, "outcome_code": self.outcome_code,
                "article": self.article, "label": self.label, "title": self.title,
                "chapter": self.chapter, "establishes": self.establishes,
                "consequence": self.consequence, "text": self.text,
                "english_current": self.english_current,
                "last_amended_year": self.last_amended_year,
                "supporting": self.supporting, "note": self.note}


@lru_cache(maxsize=1)
def _corpus() -> dict:
    return load()


@lru_cache(maxsize=1)
def _by_article() -> dict[int, dict]:
    return {a["article"]: a for a in _corpus().get("articles", [])}


def available() -> bool:
    """Is a corpus loaded at all? With none, every lookup is honestly `not-found`."""
    return bool(_by_article())


def article(number: int) -> dict | None:
    return _by_article().get(number)


def _quote(a: dict) -> str:
    text = (a.get("text") or "").replace("\n", " ").strip()
    return text if len(text) <= MAX_QUOTE else text[:MAX_QUOTE].rsplit(" ", 1)[0] + "…"


def for_outcome(code: str) -> Citation:
    """The provision that founds this outcome, or an explicit record that there is none."""
    b = basis_table.for_code(code)
    if b is None:
        return Citation(state=NOT_FOUND, outcome_code=code,
                        note="No legal basis is recorded for this outcome, so no provision is "
                             "cited. The finding rests on the evidence alone.")
    a = article(b.article)
    if a is None:
        return Citation(state=NOT_FOUND, outcome_code=code, article=b.article,
                        label=f"Article {b.article}",
                        note="The regulations corpus is not loaded, so the article behind this "
                             "finding could not be retrieved.")

    stale = not a.get("english_current", True)
    unconfirmed = not a.get("numbering_confirmed", True)
    note = ""
    if unconfirmed:
        note = ("The two editions do not agree on this article's number, so the citation "
                "should be checked against the Arabic before it is relied on.")
    elif stale:
        note = (f"The English edition dates from {_corpus().get('english_edition_year')} and "
                f"this article was amended in {a['last_amended_year']}. The wording shown is "
                f"superseded — verify against the Arabic before quoting it.")

    return Citation(
        state=NEEDS_VALIDATION if (stale or unconfirmed) else FOUND,
        outcome_code=code, article=b.article, label=f"Article {b.article}",
        title=a["title"].title(), chapter=a.get("chapter", ""),
        establishes=b.establishes, consequence=b.consequence,
        text=_quote(a), english_current=not stale,
        last_amended_year=a.get("last_amended_year"),
        supporting=[{"article": n, "label": f"Article {n}",
                     "title": (article(n) or {}).get("title", "").title()}
                    for n in b.supporting if article(n)],
        note=note)


def sentence(code: str) -> str:
    """The finding as an auditor would write it: evidence · basis · consequence.

    The evidence half is the Authority's own outcome statement, which the engine already owns;
    this supplies the two halves that were missing.
    """
    from .. import outcomes as oc

    c = for_outcome(code)
    statement = oc.statement(code) if code in oc.BY_CODE else ""
    if c.state == NOT_FOUND:
        return statement
    return (f"{statement} {c.label} establishes that {c.establishes}; accordingly, "
            f"{c.consequence}.")


def coverage() -> dict:
    """What the corpus covers, and which outcomes have no basis recorded."""
    from .. import outcomes as oc

    codes = [o.code for o in oc.OUTCOMES]
    corpus = _corpus()
    return {
        "loaded": available(),
        "article_count": corpus.get("article_count", 0),
        "english_edition_year": corpus.get("english_edition_year"),
        "amended_since_english_edition": corpus.get("amended_since_english_edition", []),
        "outcomes_total": len(codes),
        "outcomes_with_basis": len([c for c in codes if basis_table.for_code(c)]),
        "outcomes_without_basis": basis_table.uncovered(codes),
        "problems": basis_table.validate(corpus),
    }

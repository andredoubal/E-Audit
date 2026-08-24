"""The regulatory controls, loaded and validated against the articles they cite.

`basis.py` answers "which article founds this finding" for the twelve outcome codes the auditors
gave us. That is the wrong shape for screening a case: it starts from a finding that already
exists, so a case with no findings gets no regulatory analysis at all — which is exactly the
cell the specification says must be reachable, where the numbers reconcile and a compliance
question remains.

A **control** starts from the other end. It is a testable statement of what a provision
requires, carrying the conditions that bring it into scope, the exceptions that take it out
again, the evidence needed to assess it, and an honest declaration of whether it can be settled
by Python, needs a model, or needs a person.

Three properties this file exists to guarantee:

* **A control cites a real article, or it does not load.** `validate()` joins every control to
  the corpus at import and refuses a control whose article is not there. Nothing downstream can
  invent a provision because there is no path by which an unvalidated control reaches it.
* **The corpus is a file in the repository, not a table built at startup.** Somebody has to be
  able to read what the application believes Article 53 requires without running anything, and
  `git diff` has to show it when that changes. Same rule the article corpus follows.
* **The draft says it is a draft.** These are an editorial reading, not reviewed legal analysis,
  and every assessment produced from one carries that on its face. A control framework that
  looked authoritative while being unreviewed would be the most dangerous thing in this
  application.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .build import load as load_articles

CORPUS = Path(__file__).resolve().parents[3] / "corpus" / "regulatory_controls.json"

# ---------------------------------------------------------------- testability
DETERMINISTIC = "deterministic"
AI_ASSISTED = "ai-assisted"
MANUAL = "manual"

# ---------------------------------------------------------------- applicability statuses
TESTED = "applicable-tested"
CONCERN = "applicable-potential-concern"
NO_EVIDENCE = "applicable-insufficient-evidence"
POTENTIAL = "potentially-applicable"
NOT_APPLICABLE = "not-applicable"
NOT_TESTABLE = "not-testable"

STATUSES = (TESTED, CONCERN, NO_EVIDENCE, POTENTIAL, NOT_APPLICABLE, NOT_TESTABLE)

STATUS_LABEL: dict[str, str] = {
    TESTED: "Assessed — no issue identified",
    CONCERN: "Potential concern",
    NO_EVIDENCE: "Applicable — evidence missing",
    POTENTIAL: "Potentially applicable — needs clarification",
    NOT_APPLICABLE: "Not applicable",
    NOT_TESTABLE: "Not testable with the evidence held",
}

#: Order the coverage summary reads in: what needs a person first.
STATUS_ATTENTION: dict[str, int] = {
    CONCERN: 5, NO_EVIDENCE: 4, POTENTIAL: 3, NOT_TESTABLE: 2, TESTED: 1, NOT_APPLICABLE: 0,
}


@dataclass(frozen=True)
class Control:
    control_id: str
    title: str
    topic: str
    applies_to: str                  # sales | purchases | both
    article: int
    requirement: str
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    applies_when: dict
    evidence_required: dict
    testability: str
    check: str
    check_params: dict
    related: tuple[int, ...]
    paragraph: str = ""
    source_note: str = ""

    def to_dict(self) -> dict:
        return {
            "control_id": self.control_id, "title": self.title, "topic": self.topic,
            "applies_to": self.applies_to, "article": self.article,
            "paragraph": self.paragraph, "requirement": self.requirement,
            "conditions": list(self.conditions), "exceptions": list(self.exceptions),
            "evidence_required": self.evidence_required, "testability": self.testability,
            "related": list(self.related), "source_note": self.source_note,
        }


@dataclass
class Corpus:
    document: str
    jurisdiction: str
    review_status: str
    review_note: str
    controls: tuple[Control, ...]
    #: Articles in the regulations that no control covers. Published, because "we did not look"
    #: and "we looked and there was nothing" are different answers and an empty list conflates
    #: them.
    uncovered_articles: tuple[int, ...] = ()

    def by_id(self, control_id: str) -> Control | None:
        return next((c for c in self.controls if c.control_id == control_id), None)

    def for_article(self, article: int) -> tuple[Control, ...]:
        return tuple(c for c in self.controls if c.article == article)


class ControlError(ValueError):
    """A control that cannot be trusted to load. Deliberately fatal rather than skipped."""


def _parse(raw: dict, known_articles: set[int]) -> Control:
    for required in ("control_id", "title", "article", "requirement", "testability", "check"):
        if not raw.get(required):
            raise ControlError(f"control {raw.get('control_id', '?')} has no {required}")

    article = int(raw["article"])
    if article not in known_articles:
        raise ControlError(
            f"control {raw['control_id']} cites Article {article}, which is not in the "
            f"corpus — a control may not rest on a provision the application cannot show")
    if raw["testability"] not in (DETERMINISTIC, AI_ASSISTED, MANUAL):
        raise ControlError(f"control {raw['control_id']} has an unknown testability "
                           f"'{raw['testability']}'")

    return Control(
        control_id=raw["control_id"], title=raw["title"], topic=raw.get("topic", ""),
        applies_to=raw.get("applies_to", "both"), article=article,
        paragraph=str(raw.get("paragraph", "")), requirement=raw["requirement"],
        conditions=tuple(raw.get("conditions") or ()),
        exceptions=tuple(raw.get("exceptions") or ()),
        applies_when=raw.get("applies_when") or {"always": True},
        evidence_required=raw.get("evidence_required") or {},
        testability=raw["testability"], check=raw["check"],
        check_params=raw.get("check_params") or {},
        related=tuple(int(r) for r in (raw.get("related") or ())),
        source_note=raw.get("source_note", ""))


@lru_cache(maxsize=1)
def load() -> Corpus:
    """The control set, joined to the articles at load. Cached — it is a file, not a query."""
    if not CORPUS.exists():
        return Corpus(document="", jurisdiction="", review_status="none",
                      review_note="No control corpus is present.", controls=())

    raw = json.loads(CORPUS.read_text(encoding="utf-8"))
    articles = load_articles()
    known = {a["article"] for a in articles["articles"]}

    controls = tuple(_parse(c, known) for c in raw.get("controls") or ())
    ids = [c.control_id for c in controls]
    if len(set(ids)) != len(ids):
        raise ControlError("two controls share a control_id, so one would silently shadow "
                           "the other")

    covered = {c.article for c in controls}
    return Corpus(
        document=raw.get("document", ""), jurisdiction=raw.get("jurisdiction", ""),
        review_status=raw.get("review_status", "draft-unreviewed"),
        review_note=raw.get("review_note", ""),
        controls=controls,
        uncovered_articles=tuple(sorted(known - covered)))


def coverage() -> dict:
    """How much of the regulations the control set actually reaches.

    The honest headline for a stakeholder, and the one a screening tool most wants to hide:
    ten controls over seventy-nine articles is a start, not coverage, and the number says so.
    """
    c = load()
    articles = load_articles()
    total = int(articles.get("article_count") or 0)
    return {
        "document": c.document,
        "review_status": c.review_status,
        "review_note": c.review_note,
        "controls": len(c.controls),
        "articles_total": total,
        "articles_covered": total - len(c.uncovered_articles),
        "articles_uncovered": len(c.uncovered_articles),
        "uncovered_articles": list(c.uncovered_articles),
        "by_testability": {
            k: sum(1 for x in c.controls if x.testability == k)
            for k in (DETERMINISTIC, AI_ASSISTED, MANUAL)
        },
    }

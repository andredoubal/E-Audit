"""Screening the control set against a case, and assessing what survives.

This module is the answer to the specification's central asymmetry: **a clean reconciliation is
not evidence of compliance.** Every regulatory citation in the application until now hung off a
confirmed hypothesis, so a case whose numbers agreed produced no regulatory analysis at all.
The top-right cell — reconciled, and a compliance question remains — was structurally
unreachable. Screening starts from the evidence instead, so it is reached whether or not
anything differs.

Three passes, in order, each of which can stop a control before the next:

    scope        do the circumstances the control names arise on this case?
    testability  is the evidence it needs actually here?
    assessment   run the check, or say honestly that it needs a person

Two rules the engine may not break:

* **The article is retrieved, never generated.** A control cites an article validated at load,
  and the citation carries that article's own words from the corpus. There is no path by which a
  provision can be invented, because nothing here composes one.
* **Superseded wording is never quoted as the operative rule.** 31 of the 79 articles are shown
  in an English edition that predates the current Arabic, and an assessment resting on one says
  so on its face. Article 50 — the blocked-input provision — is among them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import checks as CK
from . import controls as C
from . import facts as F
from .build import load as load_articles
from .lookup import MAX_QUOTE


@dataclass
class Assessment:
    control: C.Control
    status: str
    scope_reason: str
    detail: str = ""
    outcome: dict = field(default_factory=dict)
    citation: dict = field(default_factory=dict)
    missing_evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            **self.control.to_dict(),
            "status": self.status,
            "status_label": C.STATUS_LABEL[self.status],
            "attention": C.STATUS_ATTENTION[self.status],
            "scope_reason": self.scope_reason,
            "detail": self.detail,
            "outcome": self.outcome,
            "citation": self.citation,
            "missing_evidence": self.missing_evidence,
        }


def _citation(article_no: int) -> dict:
    """The provision's own words, and whether they are the current ones.

    Version awareness has a hard ceiling with the corpus we hold: one English edition of 2021
    against Arabic amendments to 2024, with no per-article effective-date history. So this can
    honestly say "current" or "superseded since 2024 — validate before relying on it", and it
    does not pretend to point-in-time retrieval it cannot perform.
    """
    articles = {a["article"]: a for a in load_articles()["articles"]}
    a = articles.get(article_no)
    if a is None:
        return {"state": "not-found", "article": article_no,
                "note": "the article is not in the corpus"}

    current = bool(a.get("english_current", True))
    amended = a.get("last_amended_year")
    text = (a.get("text") or "")[:MAX_QUOTE]
    return {
        "state": "found" if current else "needs-validation",
        "article": article_no,
        "label": f"Article {article_no}",
        "title": a.get("title", ""),
        "chapter": a.get("chapter", ""),
        "text": text,
        "english_current": current,
        "last_amended_year": amended,
        "note": ("" if current else
                 f"The English edition of this article predates the current Arabic, which "
                 f"carries amendments to {amended}. The wording shown is superseded and must "
                 f"be validated against the current Arabic before it is relied on."),
    }


def _missing_evidence(control: C.Control, facts: F.CaseFacts) -> list[str]:
    """What the control needs that the case does not have.

    `dataset_types` is **any of**: it names the kinds of file this control can be read from, and
    one of them is enough. A control that needs two datasets *together* says so in its own
    `check_params`, where the check that requires them can report which one is absent — reading
    the list as all-of here would report a control unassessable because a second, alternative
    source of the same evidence happened not to be filed.
    """
    needed_types = list(control.evidence_required.get("dataset_types") or ())
    needed_roles = list(control.evidence_required.get("roles") or ())

    out: list[str] = []
    if needed_types and not (set(needed_types) & facts.dataset_types):
        out.append(" or ".join(t.replace("-", " ") for t in needed_types))
    out += [r.replace("_", " ") for r in needed_roles if r not in facts.roles_present]
    return out


def assess_one(control: C.Control, facts: F.CaseFacts, profiles: list[dict],
               rows_by_file: dict[str, list]) -> Assessment:
    citation = _citation(control.article)

    # --- pass 1: scope
    in_scope, reason = F.applies(control.applies_when, facts)
    if not in_scope:
        return Assessment(control=control, status=C.NOT_APPLICABLE, scope_reason=reason,
                          detail=f"Not in scope for this case — {reason}.", citation=citation)

    # --- pass 2: testability
    missing = _missing_evidence(control, facts)
    if missing:
        return Assessment(
            control=control, status=C.NO_EVIDENCE, scope_reason=reason,
            detail=("In scope, but the evidence needed to assess it is not on the case: "
                    + ", ".join(missing) + "."),
            citation=citation, missing_evidence=missing)

    check = CK.CHECKS.get(control.check)
    if check is None:
        return Assessment(
            control=control, status=C.NOT_TESTABLE, scope_reason=reason,
            detail=f"No check implements '{control.check}', so this control cannot be settled.",
            citation=citation)

    # --- pass 3: assessment
    outcome = check(control, profiles, rows_by_file)
    status = {
        CK.PASSED: C.TESTED,
        CK.CONCERN: C.CONCERN,
        CK.NEEDS_REVIEW: C.POTENTIAL,
        CK.NO_EVIDENCE: C.NO_EVIDENCE,
    }[outcome.result]

    detail = outcome.detail
    if status == C.CONCERN and citation.get("state") == "needs-validation":
        detail += (" " + citation["note"])

    # Nothing is missing here by construction: the testability gate above returns early when
    # anything is, so reaching this point means the evidence was present and was read.
    return Assessment(control=control, status=status, scope_reason=reason, detail=detail,
                      outcome=outcome.to_dict(), citation=citation)


def assess(profiles: list[dict], rows_by_file: dict[str, list],
           declared: dict[str, float], *, workstream: str = "") -> dict:
    """Screen and assess every control, for one workstream or both."""
    corpus = C.load()
    case_facts = F.build(profiles, rows_by_file, declared)

    wanted = [c for c in corpus.controls
              if not workstream or c.applies_to in (workstream, "both")]
    results = [assess_one(c, case_facts, profiles, rows_by_file).to_dict() for c in wanted]
    results.sort(key=lambda r: (-r["attention"], r["control_id"]))

    by_status = {s: sum(1 for r in results if r["status"] == s) for s in C.STATUSES}
    return {
        "review_status": corpus.review_status,
        "review_note": corpus.review_note,
        "facts": case_facts.to_dict(),
        "summary": {
            "assessed": len(results),
            "by_status": by_status,
            # The honest headline, and the one a screening tool most wants to hide.
            "coverage": C.coverage(),
            "superseded_citations": sum(
                1 for r in results
                if r["citation"].get("state") == "needs-validation"
                and r["status"] in (C.CONCERN, C.POTENTIAL)),
        },
        "controls": results,
    }

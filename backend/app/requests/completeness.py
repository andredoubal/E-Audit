"""Compare what was requested against what arrived.

This is the check the auditors described doing by hand on every response, and it is most of
pain point 2: time spent on structure, completeness, fields, calculations and formatting rather
than on tax. It is also the reason a case takes months — each round of "you left out two
columns" costs weeks.

**Deterministic first, model second.** Almost none of this needs judgement. Whether a column is
present, whether a mandatory field is blank, whether the rows cover the period asked for, and
whether a stated total equals the sum of its own column are all *checks*. They run here, with no
model, no credentials, and a reproducible answer. Only two questions genuinely need judgement —
whether a document addresses what was asked, and whether an explanation is specific enough — and
those belong to the document reviewer, which is allowed to be wrong and is checked afterwards.

Gaps are recomputed from scratch on every run. A resolved gap simply stops being produced, so
there is no reconciliation of gap state to get wrong.

The arithmetic check is the taxpayer half of §7's two error sources; the auditor half — did we
transcribe the taxpayer's own total correctly — is the `RecomputedTotal` test in the adjudicator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..pipeline.predicates import is_null
from .catalog import ITEM_BY_KEY
from .extract import display, normalise

TOLERANCE = 1.0          # SAR — the same one riyal the adjudicator works to
MAX_CITED_ROWS = 5       # enough for the auditor to find it; not a data dump
COVERAGE_SLACK = 3       # days: a period end a day or two short is not a gap worth a round trip
SPARSE_THRESHOLD = 0.5   # a non-mandatory column blank on more than half the rows
MIN_ROWS_FOR_DENSITY = 8  # below this, "half the rows are blank" is not a pattern

BLOCKING = "blocking"
ADVISORY = "advisory"


@dataclass
class Gap:
    kind: str
    detail: str
    severity: str = BLOCKING
    citation: str = ""
    item_label: str = ""
    request_item_id: int | None = None
    document_id: int | None = None
    source: str = "deterministic"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "detail": self.detail, "severity": self.severity,
            "citation": self.citation, "item_label": self.item_label,
            "request_item_id": self.request_item_id, "document_id": self.document_id,
            "source": self.source,
        }


@dataclass
class Report:
    case_id: str
    round: int
    gaps: list[Gap] = field(default_factory=list)
    checked_items: int = 0
    checked_documents: int = 0

    @property
    def blocking(self) -> list[Gap]:
        return [g for g in self.gaps if g.severity == BLOCKING]

    @property
    def complete(self) -> bool:
        """The gate: the substantive review opens only when nothing blocking remains."""
        return not self.blocking

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id, "round": self.round,
            "complete": self.complete,
            "checked_items": self.checked_items,
            "checked_documents": self.checked_documents,
            "blocking": len(self.blocking),
            "advisory": len(self.gaps) - len(self.blocking),
            "gaps": [g.to_dict() for g in self.gaps],
        }


# --------------------------------------------------------------------------------- helpers

def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _rows_as_dicts(content: dict) -> list[dict]:
    cols = content.get("columns") or []
    out = []
    for row in content.get("rows") or []:
        d = {c: (row[i] if i < len(row) else None) for i, c in enumerate(cols)}
        # normalise "" to None so `is_null` means "not populated", which is what was asked
        out.append({k: (None if (v is None or (isinstance(v, str) and not v.strip())) else v)
                    for k, v in d.items()})
    return out


def _best_catalog_match(columns: list[str]) -> tuple[str, float]:
    """Which catalogue item do these columns look most like? Used to spot a wrong document."""
    best, best_score = "", 0.0
    present = set(columns)
    for item in ITEM_BY_KEY.values():
        req = set(item.required_columns)
        if not req:
            continue
        score = len(req & present) / len(req)
        if score > best_score:
            best, best_score = item.key, score
    return best, round(best_score, 3)


# --------------------------------------------------------------------------------- the checks

def _check_columns(item, content: dict) -> list[Gap]:
    present = set(content.get("columns") or [])
    required = [normalise(c) for c in (item.required_columns or [])]
    gaps = []
    for col in required:
        if col not in present:
            gaps.append(Gap(kind="missing-column",
                            detail=f"The '{display(col)}' column was requested but is not in "
                                   f"the file.",
                            citation=f"header row of {content.get('format', 'file')}"))
    return gaps


def _check_mandatory(item, content: dict) -> list[Gap]:
    """Present-but-blank. Reuses the predicate algebra: `is_null(column)` over each row."""
    rows = _rows_as_dicts(content)
    if not rows:
        return []
    present = set(content.get("columns") or [])
    gaps = []
    for col in [normalise(c) for c in (item.mandatory_columns or [])]:
        if col not in present:
            continue                      # already reported as a missing column
        test = is_null(col)
        blank_rows = [i for i, r in enumerate(rows, start=1) if test.evaluate(r)]
        if blank_rows:
            cited = ", ".join(str(i) for i in blank_rows[:MAX_CITED_ROWS])
            more = f" (+{len(blank_rows) - MAX_CITED_ROWS} more)" \
                if len(blank_rows) > MAX_CITED_ROWS else ""
            gaps.append(Gap(
                kind="empty-mandatory-field",
                detail=f"'{display(col)}' must be completed on every row, but is empty "
                       f"in {len(blank_rows)} of {len(rows)} rows.",
                citation=f"rows {cited}{more}"))
    return gaps


def _check_worksheets(item, content: dict) -> list[Gap]:
    """The requested columns are missing here — are they on another tab of the same workbook?

    A taxpayer who puts a cover sheet in front of the data has supplied the data. Reporting the
    columns as absent and sending them a chase letter for a file they already sent is the single
    most annoying way for this tool to be wrong, so when the columns are elsewhere in the
    workbook we say exactly where.
    """
    sheets = [s for s in (content.get("sheets") or []) if not s.get("primary")]
    if not sheets:
        return []
    required = [normalise(c) for c in (item.required_columns or [])]
    missing = [c for c in required if c not in set(content.get("columns") or [])]
    if not missing:
        return []
    gaps = []
    for sheet in sheets:
        found = [c for c in missing if c in set(sheet.get("columns") or [])]
        if len(found) < max(2, (len(missing) + 1) // 2):
            continue
        gaps.append(Gap(
            kind="other-worksheet", severity=ADVISORY,
            detail=f"{len(found)} of the {len(missing)} columns reported missing are present on "
                   f"the '{sheet['name']}' worksheet, which is not the one that was read. The "
                   f"data may have been supplied on the wrong tab.",
            citation=f"worksheet '{sheet['name']}' ({sheet.get('row_count', 0)} rows)"))
    return gaps


def _check_null_density(item, content: dict) -> list[Gap]:
    """A column that is there but mostly empty answers the request in form only.

    Advisory, and deliberately not the mandatory-blank check: nobody asked for every row to be
    populated. But a supplier VAT number present on four rows out of ninety is not a column an
    auditor can work from, and it is better to say so in this round than to discover it in the
    analysis.
    """
    rows = _rows_as_dicts(content)
    if len(rows) < MIN_ROWS_FOR_DENSITY:
        return []
    present = set(content.get("columns") or [])
    mandatory = {normalise(c) for c in (item.mandatory_columns or [])}
    gaps = []
    for col in [normalise(c) for c in (item.required_columns or [])]:
        if col not in present or col in mandatory:
            continue                       # blanks in a mandatory column are already reported
        blank = sum(1 for r in rows if is_null(col).evaluate(r))
        if blank / len(rows) < SPARSE_THRESHOLD:
            continue
        gaps.append(Gap(
            kind="sparse-column", severity=ADVISORY,
            detail=f"'{display(col)}' was supplied but is empty on {blank} of {len(rows)} rows "
                   f"({blank / len(rows):.0%}). The column is present without being usable.",
            citation=f"{blank} of {len(rows)} rows"))
    return gaps


def _check_period(item, content: dict, period_from: date, period_to: date) -> list[Gap]:
    pf, pt = _as_date(content.get("period_from")), _as_date(content.get("period_to"))
    want_from = item.period_from or period_from
    want_to = item.period_to or period_to
    if pf is None or pt is None:
        return []                          # no dated column — nothing to compare against
    gaps = []
    if (want_from - pf).days > COVERAGE_SLACK:
        gaps.append(Gap(kind="wrong-period", severity=ADVISORY,
                        detail=f"The file starts at {pf:%d %b %Y}, before the period requested "
                               f"({want_from:%d %b %Y}). Rows outside the period were supplied.",
                        citation="earliest dated row"))
    if (want_to - pt).days > COVERAGE_SLACK:
        gaps.append(Gap(kind="wrong-period",
                        detail=f"The file stops at {pt:%d %b %Y} but the period requested runs "
                               f"to {want_to:%d %b %Y} — "
                               f"{(want_to - pt).days} days are not covered.",
                        citation="latest dated row"))
    return gaps


def _check_footing(item, content: dict) -> list[Gap]:
    """Does the total the taxpayer states equal the sum of the column it claims to total?"""
    footed = list(item.footed_by or [])
    if len(footed) != 2:
        return []
    stated_key, column = normalise(footed[0]), normalise(footed[1])
    stated_totals = {normalise(k): v for k, v in (content.get("stated_totals") or {}).items()}
    stated = _num(stated_totals.get(stated_key, stated_totals.get(column)))
    if stated is None:
        return []                          # nothing stated to disagree with
    rows = _rows_as_dicts(content)
    values = [_num(r.get(column)) for r in rows]
    computed = round(sum(v for v in values if v is not None), 2)
    diff = round(stated - computed, 2)
    if abs(diff) <= TOLERANCE:
        return []
    return [Gap(kind="arithmetic-mismatch",
                detail=f"The stated total for '{display(column)}' is SAR {stated:,.2f}, but the "
                       f"rows sum to SAR {computed:,.2f} — a difference of SAR {diff:,.2f}.",
                citation=f"totals row vs {len(rows)} data rows")]


def _check_format(item, doc_format: str) -> list[Gap]:
    want = (item.expected_format or "").lower()
    got = (doc_format or "").lower()
    if not want or not got or want == got:
        return []
    tabular = {"xlsx", "xlsm", "csv"}
    if want in tabular and got in tabular:
        return []                          # a csv where we asked for xlsx is checkable anyway
    severity = BLOCKING if want in tabular else ADVISORY
    return [Gap(kind="wrong-format", severity=severity,
                detail=f"Supplied as {got}; a {want} was requested. "
                       + ("A tabular file is needed before the analysis can be checked."
                          if severity == BLOCKING else
                          "The content may still be usable."))]


def _check_is_right_document(item, content: dict) -> list[Gap]:
    """Did they send the thing we asked for, or something else that looks like a spreadsheet?"""
    required = [normalise(c) for c in (item.required_columns or [])]
    if not required or not content.get("columns"):
        return []
    present = set(content["columns"])
    overlap = len(set(required) & present) / len(required)
    if overlap >= 0.5:
        return []
    best, best_score = _best_catalog_match(content["columns"])
    looks_like = ITEM_BY_KEY[best].label if best and best_score > overlap else None
    detail = (f"Only {overlap:.0%} of the requested columns are present.")
    if looks_like:
        detail += f" The file looks more like a {looks_like.lower()}."
    return [Gap(kind="wrong-document", detail=detail, citation="header row")]


# --------------------------------------------------------------------------------- entry point

def _latest(docs: list):
    """The version of a document that counts — the one received last, id breaking ties."""
    return max(docs, key=lambda d: (getattr(d, "received_at", None) or date.min, d.id or 0))


def superseded_ids(documents: list) -> set[int]:
    """Documents replaced by a later upload against the same item. History, not evidence."""
    by_item: dict[int, list] = {}
    for d in documents:
        if d.request_item_id is not None:
            by_item.setdefault(d.request_item_id, []).append(d)
    out: set[int] = set()
    for docs in by_item.values():
        keep = _latest(docs)
        out |= {d.id for d in docs if d.id != keep.id}
    return out


def check(*, case_id: str, round_: int, items: list, documents: list,
          period_from: date, period_to: date) -> Report:
    """Run every deterministic check for one round of correspondence.

    `items` are `models.RequestItem` rows (or anything with the same attributes) and
    `documents` are `models.ReceivedDocument` rows. Both are passed in rather than queried so
    the checker stays a pure function — which is what makes it testable against a fixture.

    **The latest document for an item is the one that counts.** When a taxpayer answers a
    follow-up, they resend the corrected file against the same item; checking the superseded
    version too would keep reporting gaps the taxpayer has already fixed, and the loop could
    never close. Earlier versions stay on the case file as history — see
    `superseded_ids()` — they are simply not re-checked.
    """
    report = Report(case_id=case_id, round=round_,
                    checked_items=len(items), checked_documents=len(documents))
    by_item: dict[int, list] = {}
    for d in documents:
        by_item.setdefault(d.request_item_id, []).append(d)

    for item in items:
        if item.status == "waived":
            continue
        docs = by_item.get(item.id, [])
        if not docs:
            report.gaps.append(Gap(
                kind="missing-item", item_label=item.label, request_item_id=item.id,
                detail=f"Nothing was supplied for '{item.label}'."))
            continue
        for doc in [_latest(docs)]:
            content = doc.content or {}
            found: list[Gap] = []
            found += _check_format(item, doc.file_format or content.get("format", ""))
            if content.get("columns"):
                found += _check_is_right_document(item, content)
                found += _check_columns(item, content)
                found += _check_worksheets(item, content)
                found += _check_mandatory(item, content)
                found += _check_null_density(item, content)
                found += _check_period(item, content, period_from, period_to)
                found += _check_footing(item, content)
            elif item.kind == "analysis":
                found.append(Gap(
                    kind="wrong-format",
                    detail=f"'{item.label}' was requested as a tabular analysis, but the file "
                           f"supplied has no readable table."
                           + (f" {content['note']}" if content.get("note") else "")))
            for g in found:
                g.item_label = item.label
                g.request_item_id = item.id
                g.document_id = doc.id
            report.gaps.extend(found)

    for doc in by_item.get(None, []):
        report.gaps.append(Gap(
            # This gap belongs to no request item — that is the whole of what it says. It still
            # needs a label, because every other gap has one and a blank cell in the middle of
            # the column reads as a defect in the checker rather than a fact about the file.
            kind="unrequested-document", severity=ADVISORY, document_id=doc.id,
            item_label="Not requested",
            detail=f"'{doc.filename}' was supplied but does not answer any item on the request. "
                   f"It may be a misfiled response, or evidence worth reading anyway."))

    return report


# ------------------------------------------------------------------------------ presentation

RECEIVED = "received"
MISSING = "missing"
INCOMPLETE = "incomplete"
NEEDS_REVIEW = "needs-review"

STATE_LABEL = {
    RECEIVED: "Received",
    MISSING: "Missing",
    INCOMPLETE: "Incomplete",
    NEEDS_REVIEW: "Needs auditor review",
}

# Gaps a machine cannot settle: the file may well be the right one under a name we did not
# expect, on a tab we did not read, or explained in words only a person can weigh. Reporting
# these as "incomplete" would tell the auditor the taxpayer failed, when what actually happened
# is that the check reached the end of what it can decide.
_REVIEW_KINDS = {"wrong-document", "other-worksheet", "too-vague", "unrequested-document"}

_RANK = {MISSING: 3, INCOMPLETE: 2, NEEDS_REVIEW: 1, RECEIVED: 0}


def _state_for(gaps: list) -> tuple[str, str]:
    """The worst thing said about one item, and why."""
    state, reason = RECEIVED, ""
    for g in gaps:
        kind = getattr(g, "kind", "")
        if kind == "missing-item":
            candidate = MISSING
        elif kind in _REVIEW_KINDS or getattr(g, "source", "deterministic") != "deterministic":
            candidate = NEEDS_REVIEW
        elif getattr(g, "severity", BLOCKING) == BLOCKING:
            candidate = INCOMPLETE
        else:
            candidate = NEEDS_REVIEW
        if _RANK[candidate] > _RANK[state]:
            state, reason = candidate, getattr(g, "detail", "")
    return state, reason


def item_key(row: dict) -> str:
    """What a review is stored against. Stable across recomputation, which a row id is not:
    the assessment is derived fresh on every request, so an id would point at nothing by the
    time the auditor came back to their challenge."""
    return f"{row.get('kind') or 'item'}::{row.get('label', '')}"


def assessment(items: list, documents: list, gaps: list, reviews: dict | None = None) -> dict:
    """Every requested item under one of four words, for the auditor rather than for the engine.

    The engine works in gaps because a gap is what a check produces. An auditor works in "what
    is still outstanding", and nine gap kinds across two severities do not answer that at a
    glance. This is presentation over the same rows — nothing new is stored, and the four states
    are derived fresh every time, so a fixed gap changes the word without any state to reconcile.

    The distinction that earns its place is **incomplete** against **needs auditor review**: the
    first is a defect the taxpayer must fix, the second is a question the tool cannot answer. A
    chase letter written from the second is a letter that should not have been sent.
    """
    by_item: dict[int | None, list] = {}
    for g in gaps:
        by_item.setdefault(getattr(g, "request_item_id", None), []).append(g)
    docs_by_item: dict[int | None, list] = {}
    for d in documents:
        docs_by_item.setdefault(getattr(d, "request_item_id", None), []).append(d)

    rows = []
    for item in items:
        if getattr(item, "status", "") == "waived":
            continue
        found = by_item.get(item.id, [])
        state, reason = _state_for(found)
        if state == MISSING:
            reason = ""            # "Nothing was supplied for X" under a heading reading X
        docs = docs_by_item.get(item.id, [])
        rows.append({
            "request_item_id": item.id, "label": item.label, "kind": item.kind,
            "state": state, "state_label": STATE_LABEL[state], "reason": reason,
            "documents": [d.filename for d in docs],
            "blocking": sum(1 for g in found if getattr(g, "severity", "") == BLOCKING),
            "advisory": sum(1 for g in found if getattr(g, "severity", "") == ADVISORY),
            "kinds": sorted({getattr(g, "kind", "") for g in found}),
        })

    # Files that answer nothing on the request are the auditor's call, not the checker's.
    for doc in docs_by_item.get(None, []):
        rows.append({
            "request_item_id": None, "label": doc.filename, "kind": "unrequested",
            "state": NEEDS_REVIEW, "state_label": STATE_LABEL[NEEDS_REVIEW],
            "reason": "Supplied without answering any item on the request.",
            "documents": [doc.filename], "blocking": 0, "advisory": 1,
            "kinds": ["unrequested-document"],
        })

    # The auditor's own verdict on each row, and what it changes.
    #
    # A challenged row stops being chased — anything less would have the Authority writing to a
    # taxpayer for a document its own auditor has said was already supplied. The row is *not*
    # removed and its state is *not* rewritten: the file has to show both what the checker found
    # and why a person overrode it, so the finding stays and the challenge sits beside it.
    seen = reviews or {}
    for row in rows:
        review = seen.get(item_key(row))
        row["key"] = item_key(row)
        row["review"] = review
        row["chased"] = bool(row["state"] != RECEIVED
                             and not (review and review["verdict"] == "challenged"))

    summary = {s: sum(1 for r in rows if r["state"] == s)
               for s in (RECEIVED, MISSING, INCOMPLETE, NEEDS_REVIEW)}
    summary["challenged"] = sum(1 for r in rows if (r["review"] or {}).get("verdict") == "challenged")
    summary["approved"] = sum(1 for r in rows if (r["review"] or {}).get("verdict") == "approved")
    return {"items": rows, "summary": summary,
            "outstanding": sum(1 for r in rows if r["chased"])}

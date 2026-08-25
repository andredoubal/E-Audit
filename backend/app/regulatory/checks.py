"""The deterministic half of control assessment.

A control declares which of these settles it. Each returns the same shape — an outcome, a
sentence, and the rows behind it — so the applicability engine treats a check it can run and a
check it cannot identically.

Two rules run through all of them.

**A defect in a listing is a question about the invoice, not a finding against it.** The listing
is the taxpayer's account of what they issued; a row missing a customer VAT number evidences
that the *row* is incomplete, and inferring that the invoice was is a step the evidence does not
support. Every sentence here is written to survive that distinction.

**`needs_review` is a real result.** A control whose article carries exceptions this engine does
not model cannot be settled by matching words in a description column, and saying so beats a
confident answer computed from nothing. It is not a gap to be filled later with a keyword list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..evidence import roles as R

PASSED = "passed"                # assessed against the evidence, nothing arising
CONCERN = "concern"              # something the auditor should look at
NEEDS_REVIEW = "needs-review"    # cannot be settled deterministically, and says why
NO_EVIDENCE = "no-evidence"      # the evidence this needs is not on the case

MAX_CITED = 25


@dataclass
class Outcome:
    result: str
    detail: str
    count: int = 0
    total: int = 0
    rows: list[int] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"result": self.result, "detail": self.detail, "count": self.count,
                "total": self.total, "rows": self.rows[:MAX_CITED], "files": self.files}


def _cell(row: list[Any], i: int) -> Any:
    return row[i] if 0 <= i < len(row) else None


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _datasets(profiles: list[dict], types: list[str]) -> list[dict]:
    return [p for p in profiles if p.get("dataset_type") in types]


# ------------------------------------------------------------------ the checks
def fields_present(control, profiles: list[dict], rows_by_file: dict[str, list]) -> Outcome:
    """Every row carries the particulars the provision requires the document to show."""
    wanted = list(control.check_params.get("roles") or ())
    advisory = list(control.check_params.get("advisory_roles") or ())
    targets = _datasets(profiles, control.evidence_required.get("dataset_types") or [])
    if not targets:
        return Outcome(NO_EVIDENCE, "No dataset of the required kind is on the case.")

    missing: dict[str, list[int]] = {}
    soft: dict[str, list[int]] = {}
    total = 0
    files: list[str] = []

    for p in targets:
        columns = list(p.get("columns") or [])
        by_role = {r["role"]: r["column"] for r in p.get("roles") or []}
        rows = rows_by_file.get(p["filename"], [])
        total += len(rows)
        files.append(p["filename"])

        for role_set, bucket in ((wanted, missing), (advisory, soft)):
            for role in role_set:
                column = by_role.get(role)
                if column is None or column not in columns:
                    bucket.setdefault(role, [])       # absent column: every row lacks it
                    continue
                i = columns.index(column)
                for n, row in enumerate(rows, start=1):
                    if _blank(_cell(row, i)):
                        bucket.setdefault(role, []).append(n)

    if missing:
        named = "; ".join(
            f"{role.replace('_', ' ')} ({len(rows) if rows else 'the column is not in the file'}"
            + (" row(s)" if rows else "") + ")"
            for role, rows in sorted(missing.items()))
        every = sorted({n for rows in missing.values() for n in rows})
        return Outcome(
            CONCERN,
            f"Rows in the listing do not show every particular the provision requires: {named}. "
            f"The listing is the taxpayer's account of what was issued, so this is a question "
            f"about those documents rather than evidence that the invoices themselves lacked "
            f"the particulars.",
            count=len(every) or 1, total=total, rows=every, files=files)

    if soft:
        named = "; ".join(f"{role.replace('_', ' ')} ({len(rows)} row(s))"
                          for role, rows in sorted(soft.items()) if rows)
        if named:
            every = sorted({n for rows in soft.values() for n in rows})
            return Outcome(
                CONCERN,
                f"Every required particular is present. Rows are missing particulars the "
                f"provision requires only in some circumstances: {named} — which may be "
                f"correct where those circumstances do not arise.",
                count=len(every), total=total, rows=every, files=files)

    return Outcome(PASSED,
                   f"Every row across {total} record(s) carries the particulars the provision "
                   f"requires.", total=total, files=files)


def reference_to_original(control, profiles: list[dict],
                          rows_by_file: dict[str, list]) -> Outcome:
    """A note identifies the invoice it adjusts."""
    targets = _datasets(profiles, control.evidence_required.get("dataset_types") or [])
    if not targets:
        return Outcome(NO_EVIDENCE, "No credit or debit note listing is on the case.")

    orphans: list[int] = []
    total = 0
    files: list[str] = []
    column_found = False

    for p in targets:
        columns = list(p.get("columns") or [])
        rows = rows_by_file.get(p["filename"], [])
        total += len(rows)
        files.append(p["filename"])
        # The role vocabulary has no "original invoice" role, so this reads the column the
        # extractor already canonicalises. Absent, the check reports that rather than passing.
        candidates = [c for c in columns if "original" in c or "against" in c or "related" in c]
        if not candidates:
            continue
        column_found = True
        i = columns.index(candidates[0])
        orphans += [n for n, row in enumerate(rows, start=1) if _blank(_cell(row, i))]

    if not column_found:
        return Outcome(
            NEEDS_REVIEW,
            "The listing does not carry a column identifying the invoice each note adjusts, so "
            "whether the notes reference their originals cannot be established from it.",
            total=total, files=files)
    if orphans:
        return Outcome(
            CONCERN,
            f"{len(orphans)} note(s) do not identify the tax invoice they adjust.",
            count=len(orphans), total=total, rows=orphans, files=files)
    return Outcome(PASSED, f"All {total} note(s) identify the invoice they adjust.",
                   total=total, files=files)


def supporting_dataset_present(control, profiles: list[dict],
                               rows_by_file: dict[str, list]) -> Outcome:
    """The evidence the provision requires to be held is on the case at all.

    A precondition, and reported as one. Holding customs records does not establish that the
    evidence is adequate for any particular supply, and this does not claim it does.
    """
    wanted = list(control.check_params.get("dataset_types") or ())
    have = {p["dataset_type"] for p in profiles}
    missing = [w for w in wanted if w not in have]
    if missing:
        return Outcome(
            NO_EVIDENCE,
            "The evidence this provision requires is not on the case: "
            + ", ".join(m.replace("-", " ") for m in missing) + ".")
    files = [p["filename"] for p in profiles if p["dataset_type"] in wanted]
    return Outcome(
        PASSED,
        "The evidence the provision requires is on the case (" + ", ".join(files) + "). "
        "Whether it is adequate for any particular supply is a question this cannot reach.",
        files=files)


def records_readable(control, profiles: list[dict], rows_by_file: dict[str, list]) -> Outcome:
    """The records supplied can be read well enough to establish a figure."""
    blocking = [(p["filename"], f) for p in profiles
                for f in (p.get("quality_flags") or []) if f["severity"] == "blocking"]
    advisory = [(p["filename"], f) for p in profiles
                for f in (p.get("quality_flags") or [])
                if f["severity"] != "blocking"
                and f["code"] in ("stated-total-does-not-foot", "malformed-date",
                                  "blank-reference", "vat-not-consistent-with-rate")]
    if not profiles:
        return Outcome(NO_EVIDENCE, "No records have been supplied on this case.")
    if blocking:
        named = "; ".join(f"{name}: {f['detail']}" for name, f in blocking[:4])
        return Outcome(CONCERN,
                       f"Records supplied cannot be read well enough to establish a figure. "
                       f"{named}",
                       count=len(blocking), files=[n for n, _ in blocking])
    if advisory:
        named = "; ".join(f"{name}: {f['detail']}" for name, f in advisory[:4])
        return Outcome(CONCERN,
                       f"The records are usable, with defects that bear on what can be "
                       f"established from them. {named}",
                       count=len(advisory), files=[n for n, _ in advisory])
    return Outcome(PASSED,
                   f"The {len(profiles)} dataset(s) supplied are readable, with no defect that "
                   f"prevents a figure being established from them.",
                   files=[p["filename"] for p in profiles])


def needs_review(control, profiles: list[dict], rows_by_file: dict[str, list]) -> Outcome:
    """Honestly declining. The provision needs a judgement this engine cannot make."""
    why = control.source_note or (
        "the provision turns on facts about the business that a spreadsheet does not carry")
    return Outcome(
        NEEDS_REVIEW,
        f"This provision cannot be settled from the records alone — {why} It is in scope for "
        f"this case and is put to the auditor rather than answered.",
        files=[p["filename"] for p in profiles
               if p["dataset_type"] in (control.evidence_required.get("dataset_types") or [])])


CHECKS: dict[str, Callable] = {
    "fields_present": fields_present,
    "reference_to_original": reference_to_original,
    "supporting_dataset_present": supporting_dataset_present,
    "records_readable": records_readable,
    "needs_review": needs_review,
}

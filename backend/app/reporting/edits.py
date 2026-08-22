"""Overlay what the auditor wrote onto what the engine built.

One function does the work, and it is applied in `_audit_report` — the single place the JSON
view, the Word download and the printable page all pass through. That placement is the whole
design: an edit that showed on screen but not in the downloaded document would be worse than no
editing at all, because the auditor would send the version they had already corrected.

Three rules:

* **An edit is a value, never a number the engine computed.** Nothing here recomputes anything.
  The completeness tally is recounted afterwards, because a field the auditor filled in *is*
  answered and the header would otherwise keep reporting it as outstanding.
* **What was replaced is kept and shown.** `original` travels with the field, so the auditor can
  see what the tool said and put it back. An override nobody can detect is not an override, it
  is a forgery.
* **An empty edit is a revert, not an empty field.** Saving "" deletes the row and the engine's
  own value comes back, which is the behaviour an auditor expects from clearing a box.
"""
from __future__ import annotations

from sqlalchemy import select

from ..models import ReportFieldEdit

# The markers the template uses for the two kinds of gap. A field still carrying one of these
# has not been answered, whoever last touched it.
from .audit_report import FOR_AUDITOR, NOT_HELD

GAP_MARKERS = (NOT_HELD, FOR_AUDITOR, "")


def field_key(section_title: str, label: str) -> str:
    return f"{section_title}::{label}"


def edits_for(db, case_id: str) -> dict[str, ReportFieldEdit]:
    rows = db.scalars(select(ReportFieldEdit)
                      .where(ReportFieldEdit.case_id == case_id)).all()
    return {r.field_key: r for r in rows}


def apply(db, case_id: str, report: dict) -> dict:
    """The report as it should be read, signed and downloaded: engine values, auditor overrides.

    Mutates and returns `report` — it is a freshly built dict on every request, so there is
    nothing shared to protect.
    """
    saved = edits_for(db, case_id)
    if not saved:
        for section in report.get("sections", []):
            for f in section["fields"]:
                f["key"] = field_key(section["title"], f["label"])
                f["edited"] = False
                f["original"] = ""
                f["editable"] = True
        return report

    touched = 0
    for section in report.get("sections", []):
        for f in section["fields"]:
            key = field_key(section["title"], f["label"])
            f["key"] = key
            f["editable"] = True
            row = saved.get(key)
            if row is None or not (row.value or "").strip():
                f["edited"] = False
                f["original"] = ""
                continue
            f["original"] = row.original or f["value"]
            f["value"] = row.value
            f["held"] = row.value not in GAP_MARKERS
            f["edited"] = True
            f["edited_at"] = row.edited_at.isoformat() if row.edited_at else ""
            f["edited_by"] = row.edited_by
            touched += 1

    if touched:
        fields = [f for s in report.get("sections", []) for f in s["fields"]]
        held = sum(1 for f in fields if f["held"])
        report["completeness"] = {"fields": len(fields), "filled": held,
                                  "outstanding": len(fields) - held}
    report["edited_fields"] = touched
    return report


def save(db, case_id: str, key: str, value: str, original: str = "",
         by: str = "auditor") -> ReportFieldEdit | None:
    """Record one field. An empty value reverts it to whatever the engine produces."""
    row = db.scalar(select(ReportFieldEdit).where(ReportFieldEdit.case_id == case_id,
                                                  ReportFieldEdit.field_key == key))
    if not (value or "").strip():
        if row is not None:
            db.delete(row)
        return None
    if row is None:
        row = ReportFieldEdit(case_id=case_id, field_key=key, original=original or "")
        db.add(row)
    elif not row.original:
        # First override of an engine value: remember what it was. A later edit of the auditor's
        # own text must not overwrite that with their previous draft, or "restore" would restore
        # the wrong thing.
        row.original = original or ""
    row.value = value.strip()
    row.edited_by = by
    return row

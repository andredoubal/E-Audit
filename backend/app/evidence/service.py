"""The case's evidence, profiled — and what it makes possible.

Two jobs. It profiles every document on a case, applying the auditor's override where one
exists, and it answers the question the whole rebuild turns on: **given what arrived, which
comparisons can actually be run, and which cannot, and why not.**

That second answer is a published result rather than an internal decision. "Purchases register
against the return: not possible, no purchases register on file" is exactly what an auditor
needs to see, and it is what tells them which document to chase. A test that silently does not
run looks identical to a test that ran and found nothing.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditCase, DatasetOverride, ZatcaDataset
from ..requests import service as req_service
from . import profile as prof


def _overrides(db: Session, case_id: str) -> dict[str, DatasetOverride]:
    rows = db.scalars(select(DatasetOverride).where(
        DatasetOverride.case_id == case_id)).all()
    return {r.filename: r for r in rows if r.dataset_type or r.workstream}


def _sources(db: Session, case_id: str) -> list[tuple[Any, str]]:
    """Every tabular file on the case, with where it came from.

    The taxpayer's documents and the Authority's own extract are deliberately different tables —
    one is evidence the taxpayer produced and is checked against what was requested, the other
    answers to no request. But they carry the same extracted shape, and a comparison needs both,
    so profiling reads both and keeps the provenance on the profile rather than in the plumbing.
    """
    rows: list[tuple[Any, str]] = [(d, "taxpayer") for d in req_service.documents(db, case_id)]
    rows += [(z, "authority") for z in db.scalars(
        select(ZatcaDataset).where(ZatcaDataset.case_id == case_id)).all()]
    return rows


def profiles(db: Session, case_id: str) -> list[dict]:
    """Every dataset on the case, read for what it is. Derived fresh on every call."""
    over = _overrides(db, case_id)
    out: list[dict] = []
    for d, provenance in _sources(db, case_id):
        p = prof.build({"filename": d.filename, "content": d.content or {}}).to_dict()
        p["document_id"] = d.id
        p["provenance"] = provenance
        received = getattr(d, "received_at", None) or getattr(d, "uploaded_at", None)
        p["received_at"] = received.isoformat() if received else ""

        # The Authority's own extract is an e-invoice record by definition — it is what the
        # system that produced it holds. Reading that off its columns would be inferring a fact
        # already known, and getting it wrong on a file that happens to lack a status column.
        if provenance == "authority" and p["dataset_type"] in (
                prof.UNKNOWN, prof.SALES_REGISTER, prof.PURCHASE_REGISTER):
            p["read_as"] = {"dataset_type": p["dataset_type"], "label": p["dataset_label"],
                            "confidence": p["confidence"], "why": p["why"]}
            p["dataset_type"] = prof.EINVOICE_EXTRACT
            p["dataset_label"] = prof.LABEL[prof.EINVOICE_EXTRACT]
            p["workstream"] = prof.WORKSTREAM[prof.EINVOICE_EXTRACT]
            p["confidence"] = "high"
            p["why"] = ("loaded as the Authority's own invoice extract, which is what it is "
                        "regardless of which columns it happens to carry")

        o = over.get(d.filename)
        if o:
            # The auditor's reading replaces the profiler's, and the profiler's is kept beside
            # it. Confidence becomes "confirmed": a person looked, which is a stronger claim
            # than any column heuristic can make.
            p["read_as"] = {"dataset_type": p["dataset_type"], "label": p["dataset_label"],
                            "confidence": p["confidence"], "why": p["why"]}
            if o.dataset_type:
                p["dataset_type"] = o.dataset_type
                p["dataset_label"] = prof.LABEL.get(o.dataset_type, o.dataset_type)
                p["workstream"] = o.workstream or prof.WORKSTREAM.get(o.dataset_type, "unknown")
            elif o.workstream:
                p["workstream"] = o.workstream
            p["confidence"] = "confirmed"
            p["why"] = (o.note.strip()
                        or f"set by the auditor on {o.set_at.date().isoformat()}")
            p["overridden"] = True
        else:
            p["overridden"] = False
        out.append(p)
    return out


def set_override(db: Session, case_id: str, *, filename: str, dataset_type: str,
                 workstream: str = "", note: str = "") -> DatasetOverride | None:
    """Record the auditor's own reading. An empty type and workstream clears it."""
    row = db.scalar(select(DatasetOverride).where(
        DatasetOverride.case_id == case_id, DatasetOverride.filename == filename))

    if not dataset_type and not workstream:
        if row is not None:
            db.delete(row)
        return None

    if row is None:
        row = DatasetOverride(case_id=case_id, filename=filename)
        db.add(row)
        # What the profiler had said, captured the first time it is overruled. A classifier
        # being overruled often is a classifier to fix, and that is invisible without this.
        current = next((p for p in profiles(db, case_id) if p["filename"] == filename), None)
        if current:
            row.original_type = current.get("read_as", {}).get("dataset_type") \
                or current["dataset_type"]
            row.original_confidence = current.get("read_as", {}).get("confidence") \
                or current["confidence"]

    row.dataset_type = dataset_type
    row.workstream = workstream or prof.WORKSTREAM.get(dataset_type, "")
    row.note = note.strip()
    return row


def rows_by_file(db: Session, case_id: str) -> dict[str, list]:
    """The extracted rows behind every profile, keyed the same way the profiles are.

    Lives here rather than in the reconciliation service because this is the module that knows
    a case's evidence spans two tables. A consumer that built this itself would read one of them
    and silently compare against an empty population — which is a variance the size of the whole
    file, reported with total confidence.
    """
    return {d.filename: (d.content or {}).get("rows") or []
            for d, _ in _sources(db, case_id)}


# ------------------------------------------------------------------ what this makes possible

def available_types(rows: list[dict]) -> set[str]:
    return {p["dataset_type"] for p in rows if p["dataset_type"] != prof.UNKNOWN}


def state(db: Session, case_id: str) -> dict:
    """The evidence on a case, and a plain reading of what it supports.

    The return is always treated as present — it is the Authority's own record and does not
    arrive by upload — so a comparison that needs only the return and one listing becomes
    possible the moment that listing is profiled.
    """
    case = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if case is None:
        raise ValueError("case not found")

    rows = profiles(db, case_id)
    have = available_types(rows)

    unclassified = [p for p in rows if p["dataset_type"] == prof.UNKNOWN]
    low = [p for p in rows if p["confidence"] == "low" and p["dataset_type"] != prof.UNKNOWN]
    blocking = [
        {"filename": p["filename"], **f}
        for p in rows for f in p["quality_flags"] if f["severity"] == "blocking"
    ]

    return {
        "case_id": case_id,
        "period_from": case.period_from.isoformat(),
        "period_to": case.period_to.isoformat(),
        "datasets": rows,
        "by_workstream": {
            "sales": [p["filename"] for p in rows if p["workstream"] in ("sales", "both")],
            "purchases": [p["filename"] for p in rows
                          if p["workstream"] in ("purchases", "both")],
        },
        "available_types": sorted(have),
        "needs_attention": {
            "unclassified": [p["filename"] for p in unclassified],
            "low_confidence": [p["filename"] for p in low],
            "blocking_quality": blocking,
        },
        "known_types": [{"key": k, "label": v, "workstream": prof.WORKSTREAM[k]}
                        for k, v in prof.LABEL.items() if k != prof.UNKNOWN],
    }

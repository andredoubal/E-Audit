"""Reading and writing the auditor's approve-or-challenge on what the application concluded."""
from __future__ import annotations

from sqlalchemy import select

from ..models import ItemReview
from ..models.reviews import CHALLENGED, VERDICTS


def as_dict(row: ItemReview) -> dict:
    return {"verdict": row.verdict, "note": row.note, "by": row.reviewed_by,
            "at": row.reviewed_at.isoformat() if row.reviewed_at else ""}


def reviews_for(db, case_id: str, kind: str) -> dict[str, dict]:
    """Every review of one kind on this case, keyed by `item_key`."""
    rows = db.scalars(select(ItemReview).where(ItemReview.case_id == case_id,
                                               ItemReview.item_kind == kind)).all()
    return {r.item_key: as_dict(r) for r in rows}


def record(db, case_id: str, *, kind: str, key: str, verdict: str,
           note: str = "", by: str = "auditor") -> ItemReview | None:
    """Write one verdict. An empty verdict withdraws the review entirely.

    A challenge with no reason is refused by the caller, not here — "the auditor disagreed" with
    nothing after it is not something anyone can act on later, least of all the auditor.
    """
    row = db.scalar(select(ItemReview).where(ItemReview.case_id == case_id,
                                             ItemReview.item_kind == kind,
                                             ItemReview.item_key == key))
    if not verdict:
        if row is not None:
            db.delete(row)
        return None
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict: {verdict}")
    if row is None:
        row = ItemReview(case_id=case_id, item_kind=kind, item_key=key)
        db.add(row)
    row.verdict = verdict
    # An approval carries no note by design: the reason for agreeing with a check is the check.
    row.note = note.strip() if verdict == CHALLENGED else ""
    row.reviewed_by = by
    return row

"""Small-to-big expansion: a retrieved unit's parent article and explicitly cross-referenced
units. Never a raw token window — the boundaries are the ones the chunker already found."""
from __future__ import annotations

from sqlalchemy import select

from ..models.regulatory import LegalRelationship, LegalUnit


def expand(db, unit: LegalUnit) -> dict:
    parent = db.get(LegalUnit, unit.parent_id) if unit.parent_id else None
    rels = db.scalars(
        select(LegalRelationship).where(LegalRelationship.from_id == unit.unit_id)).all()
    related = [(r.relationship_type, db.get(LegalUnit, r.to_id)) for r in rels]
    return {
        "unit": unit,
        "parent": parent,
        "related": [(t, u) for t, u in related if u is not None],
    }

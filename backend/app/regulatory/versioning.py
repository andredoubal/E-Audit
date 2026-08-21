"""Version resolution: never assume the latest legal provision applies to every audit period.

`version_group` is the identifier shared by every version of the *same* provision over time.
`resolve_version` filters to the version whose effective window actually covers the requested
date. If no version covers it, the caller gets `None` — never a silent fallback to "whatever is
newest" — and flags the result NEEDS_LEGAL_VALIDATION (see regulatory/agent.py).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from ..models.regulatory import STATUS_ACTIVE, LegalUnit


def resolve_version(db, version_group: str, as_of: date | None) -> LegalUnit | None:
    units = db.scalars(
        select(LegalUnit).where(LegalUnit.version_group == version_group)
        .order_by(LegalUnit.effective_from)
    ).all()
    if not units:
        return None

    if as_of is None:
        active = [u for u in units if u.status == STATUS_ACTIVE]
        return active[0] if active else units[-1]

    for u in units:
        if u.effective_from <= as_of and (u.effective_to is None or as_of <= u.effective_to):
            return u
    return None  # no version covers this period — caller flags NEEDS_LEGAL_VALIDATION

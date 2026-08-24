"""Getting comparable numbers out of two files that do not have to agree on how to write them.

Two things have to be settled before any subtraction, and getting either wrong reports two
systems that agree as disagreeing.

**Signs carry meaning, and the meaning is not the same in every file.** A purchases export may
state input VAT negatively throughout; an accounting extract may use debits and credits; a sales
register may hold invoices positive and credit notes negative. Three different conventions, all
correct, all producing a different number from the same economic facts. So the convention is
*read* from the column and stated, never assumed:

    as-stated   every value has the same sign as its economic meaning
    inverted    the whole column is stated against its economic sign — take the magnitude
    mixed       signs distinguish document kinds within the file — sum as written, and say
                what the split is, because netting it away silently loses the credit notes

**A period is not a suggestion.** A full-year export against a quarterly return differs by
nine months of trade, and reporting that as a variance is the most confident way to be wrong
about a compliant taxpayer. So every series is split into what falls inside the period under
review and what falls outside it, both are kept, and the engine compares the scoped figures
while reporting what scoping moved. An out-of-period transaction is never itself a defect.

Rows that cannot be read are skipped and counted, never summed as zero — the same rule the
population follows, and for the same reason: a blank cell counted as nothing quietly shrinks a
total without saying so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..agents.calculation import as_date, as_number
from ..evidence import roles as R

AS_STATED = "as-stated"
INVERTED = "inverted"
MIXED = "mixed"


@dataclass
class Point:
    """One row's contribution, with everything needed to find it again."""

    row_number: int
    value: float
    when: date | None = None
    reference: str = ""

    def to_dict(self) -> dict:
        return {"row_number": self.row_number, "value": round(self.value, 2),
                "date": self.when.isoformat() if self.when else None,
                "reference": self.reference}


@dataclass
class Series:
    """A column of money, read for what it means rather than for how it is written."""

    role: str
    column: str
    points: list[Point] = field(default_factory=list)
    convention: str = AS_STATED
    convention_note: str = ""
    skipped_rows: list[int] = field(default_factory=list)
    positive_total: float = 0.0
    negative_total: float = 0.0

    @property
    def total(self) -> float:
        return round(sum(p.value for p in self.points), 2)

    @property
    def count(self) -> int:
        return len(self.points)

    def scoped(self, period_from: date, period_to: date) -> tuple[list[Point], list[Point]]:
        """(in period, outside it). A point with no date is kept in period — the file gives no
        reason to move it, and quietly excluding it would understate the side it belongs to."""
        inside = [p for p in self.points
                  if p.when is None or period_from <= p.when <= period_to]
        outside = [p for p in self.points
                   if p.when is not None and not (period_from <= p.when <= period_to)]
        return inside, outside

    def to_dict(self) -> dict:
        return {"role": self.role, "column": self.column, "count": self.count,
                "total": self.total, "convention": self.convention,
                "convention_note": self.convention_note,
                "skipped_rows": self.skipped_rows[:25],
                "skipped_count": len(self.skipped_rows),
                "positive_total": round(self.positive_total, 2),
                "negative_total": round(self.negative_total, 2)}


def _index(columns: list[str], name: str) -> int:
    try:
        return columns.index(name)
    except ValueError:
        return -1


def _cell(row: list[Any], i: int) -> Any:
    return row[i] if 0 <= i < len(row) else None


def read_convention(values: list[float]) -> tuple[str, str]:
    """Which of the three conventions this column uses, and how we can tell."""
    if not values:
        return AS_STATED, "the column carries no readable values"
    negatives = sum(1 for v in values if v < 0)
    positives = sum(1 for v in values if v > 0)
    if negatives and not positives:
        return INVERTED, ("every value in the column is negative, so the file states this side "
                          "against its economic sign; magnitudes are used and the sign is "
                          "recorded rather than dropped")
    if negatives and positives:
        return MIXED, (f"{positives} positive and {negatives} negative values, so signs "
                       f"distinguish document kinds within the file; the column is summed as "
                       f"written and the two sides are reported separately")
    return AS_STATED, "every value is stated with its economic sign"


def series(profile: dict, rows: list[list[Any]], role: str, *,
           date_role: str = "") -> Series | None:
    """Read one role out of a profiled dataset. `None` when the file does not carry it."""
    columns = list(profile.get("columns") or [])
    by_role = {r["role"]: r for r in profile.get("roles") or []}
    r = by_role.get(role)
    if not r:
        return None
    i = _index(columns, r["column"])
    if i < 0:
        return None

    di = -1
    date_column = date_role or profile.get("date_role") or ""
    if date_column:
        dr = by_role.get(date_column)
        if dr:
            di = _index(columns, dr["column"])
    ref = by_role.get(R.REFERENCE)
    ri = _index(columns, ref["column"]) if ref else -1

    raw: list[tuple[int, float, date | None, str]] = []
    skipped: list[int] = []
    for n, row in enumerate(rows, start=1):
        v = as_number(_cell(row, i))
        if v is None:
            # Skipped, not zero. A blank cell is a completeness defect the profiler already
            # reports, and counting it as nothing would quietly shrink this side.
            cell = _cell(row, i)
            if cell is not None and str(cell).strip():
                skipped.append(n)
            elif any(c is not None and str(c).strip() for c in row):
                skipped.append(n)
            continue
        when = as_date(_cell(row, di)) if di >= 0 else None
        reference = str(_cell(row, ri) or "").strip() if ri >= 0 else ""
        raw.append((n, v, when, reference))

    convention, note = read_convention([v for _, v, _, _ in raw])
    out = Series(role=role, column=r["column"], convention=convention, convention_note=note,
                 skipped_rows=skipped)
    out.positive_total = round(sum(v for _, v, _, _ in raw if v > 0), 2)
    out.negative_total = round(sum(v for _, v, _, _ in raw if v < 0), 2)
    for n, v, when, reference in raw:
        # Only a wholly inverted column is flipped. A mixed column is summed as written,
        # because there the signs are information rather than a convention to undo.
        value = abs(v) if convention == INVERTED else v
        out.points.append(Point(row_number=n, value=value, when=when, reference=reference))
    return out


def period_split(s: Series, period_from: date, period_to: date) -> dict:
    """What scoping to the period under review moves, stated in figures.

    Returned whether or not it changes anything, because "the whole dataset is in period" is
    the answer that lets an auditor stop wondering.
    """
    inside, outside = s.scoped(period_from, period_to)
    return {
        "in_period_total": round(sum(p.value for p in inside), 2),
        "in_period_count": len(inside),
        "out_of_period_total": round(sum(p.value for p in outside), 2),
        "out_of_period_count": len(outside),
        "undated_count": sum(1 for p in inside if p.when is None),
        "covers_whole_period": bool(inside) and not outside,
        "earliest": min((p.when for p in s.points if p.when), default=None),
        "latest": max((p.when for p in s.points if p.when), default=None),
    }

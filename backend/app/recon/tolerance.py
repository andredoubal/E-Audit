"""How close two figures have to be before they are treated as agreeing.

Four kinds, because they answer different questions and a single number cannot stand in for
all of them:

* **absolute** — SAR. Below this, a difference is arithmetic noise on any size of case.
* **percentage** — of the larger side. What counts as noise on a hundred-million-riyal return
  is a real difference on a hundred-thousand-riyal one.
* **rounding** — per transaction, multiplied by the row count. Two systems that round each line
  differently will disagree by a few halalas per row and by a visible amount over ten thousand
  rows, and that is a rounding difference however large the total looks.
* **date** — days. Whether an invoice dated the 31st and cleared on the 2nd is the same event.

The rule that matters more than the numbers: **a difference under tolerance is reported and
classified, never hidden.** `within()` returning true changes the *status* to reconciled; it
does not remove the figure from the result. An auditor looking for a pattern across a hundred
comparisons needs the small ones to still be there.

Defaults are derived from the 1% materiality the engine already uses, so nothing changes
behaviour silently on the cases that exist today. They are per-comparison, named, and published
with every result — a tolerance nobody can see is a tolerance nobody can argue with.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tolerance:
    name: str
    absolute: float = 0.0
    percentage: float = 0.0          # 0.01 == 1%
    rounding_per_row: float = 0.0
    date_days: int = 0
    note: str = ""

    def allowance(self, *, larger: float = 0.0, rows: int = 0) -> float:
        """The SAR a difference may reach before it stops being noise, for this comparison."""
        return round(max(self.absolute,
                         abs(larger) * self.percentage,
                         self.rounding_per_row * max(rows, 0)), 2)

    def within(self, difference: float, *, larger: float = 0.0, rows: int = 0) -> bool:
        return abs(difference) <= self.allowance(larger=larger, rows=rows)

    def to_dict(self, *, larger: float = 0.0, rows: int = 0) -> dict:
        return {"name": self.name, "absolute": self.absolute,
                "percentage": self.percentage, "rounding_per_row": self.rounding_per_row,
                "date_days": self.date_days, "note": self.note,
                "allowance": self.allowance(larger=larger, rows=rows)}


#: Two figures that should be identical to the halala — the same population summed twice.
EXACT = Tolerance("exact", absolute=0.01,
                  note="the two sources should agree exactly; only sub-halala noise is allowed")

#: A declared figure against evidence for it. 1% is the materiality the engine already applies,
#: kept so nothing on an existing case changes status because tolerances were introduced.
DECLARED = Tolerance("declared", absolute=1.0, percentage=0.01,
                     note="1% of the larger side, matching the materiality the engine applies "
                          "elsewhere, with a SAR 1 floor for small boxes")

#: Row-by-row populations that may each round differently.
PER_ROW = Tolerance("per-row", absolute=1.0, rounding_per_row=0.01,
                    note="one halala per row, because two systems may round each line "
                         "differently without either being wrong")

#: Documents whose dates may legitimately differ — clearance lag, posting lag, settlement.
DATED = Tolerance("dated", absolute=1.0, percentage=0.01, date_days=5,
                  note="as for a declared figure, and dates within five days are the same event")

PROFILES: dict[str, Tolerance] = {t.name: t for t in (EXACT, DECLARED, PER_ROW, DATED)}


def get(name: str) -> Tolerance:
    return PROFILES.get(name, DECLARED)

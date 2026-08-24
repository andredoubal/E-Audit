"""What is true about a case, in the terms a control's scope is written in.

Screening starts here. A control declares the circumstances that bring it into scope — a
purchases register is on file, exempt supplies appear, the input box was filed — and those have
to be read off the case deterministically, or two runs over identical evidence would screen
differently.

Everything here is derived from the evidence profiles and the return. Nothing is asked of a
model, and nothing is inferred from a filename.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..agents.calculation import as_number
from ..evidence import roles as R

STANDARD = "standard"
ZERO_RATED = "zero-rated"
EXEMPT = "exempt"
OUT_OF_SCOPE = "out-of-scope"

#: How a listing's own words map onto the treatments a control's scope is written in. Read from
#: the file rather than assumed: a rate column of 15 says standard-rated, a `category` column of
#: 'Z' says zero-rated, and a rate this table does not know is left uncategorised rather than
#: folded into standard — the same rule `pipeline/source.py` follows.
_TREATMENT_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ZERO_RATED, ("zero", "zero-rated", "zero rated", "z", "0%", "export")),
    (EXEMPT, ("exempt", "e", "exemption")),
    (OUT_OF_SCOPE, ("out of scope", "outside scope", "o", "non-taxable", "not taxable")),
    (STANDARD, ("standard", "s", "standard-rated", "standard rated", "15%")),
)


@dataclass
class CaseFacts:
    """The screening surface. Small on purpose — a control's scope should rest on few facts."""

    dataset_types: set[str] = field(default_factory=set)
    roles_present: set[str] = field(default_factory=set)
    vat_treatments: set[str] = field(default_factory=set)
    boxes_filed: set[str] = field(default_factory=set)
    #: Where each fact came from, so the screening can be argued with rather than trusted.
    provenance: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"dataset_types": sorted(self.dataset_types),
                "roles_present": sorted(self.roles_present),
                "vat_treatments": sorted(self.vat_treatments),
                "boxes_filed": sorted(self.boxes_filed),
                "provenance": {k: v for k, v in sorted(self.provenance.items())}}


def _cell(row: list[Any], i: int) -> Any:
    return row[i] if 0 <= i < len(row) else None


def _treatments(profile: dict, rows: list[list[Any]]) -> tuple[set[str], str]:
    """Which VAT treatments actually appear in one dataset, and how we can tell."""
    columns = list(profile.get("columns") or [])
    by_role = {r["role"]: r for r in profile.get("roles") or []}
    found: set[str] = set()

    treat = by_role.get(R.VAT_TREATMENT)
    if treat and treat["column"] in columns:
        i = columns.index(treat["column"])
        for row in rows:
            word = str(_cell(row, i) or "").strip().lower()
            if not word:
                continue
            for kind, spellings in _TREATMENT_WORDS:
                if word in spellings:
                    found.add(kind)
                    break
        if found:
            return found, f"read from the '{treat['column']}' column"

    rate = by_role.get(R.VAT_RATE)
    if rate and rate["column"] in columns:
        i = columns.index(rate["column"])
        rates = {as_number(_cell(row, i)) for row in rows}
        rates.discard(None)
        for v in rates:
            if v == 0:
                found.add(ZERO_RATED)
            elif v == 15:
                found.add(STANDARD)
            # A rate that is neither is deliberately left uncategorised: folding a genuinely
            # 5%-rated line into standard would put it in a box it was never shown to be in.
        if found:
            return found, f"inferred from the rates in '{rate['column']}'"

    return found, ""


def build(profiles: list[dict], rows_by_file: dict[str, list],
          declared: dict[str, float]) -> CaseFacts:
    facts = CaseFacts()
    for p in profiles:
        kind = p.get("dataset_type") or ""
        if kind and kind != "unknown":
            facts.dataset_types.add(kind)
            facts.provenance.setdefault(f"dataset:{kind}", []).append(p["filename"])
        for r in p.get("roles") or []:
            facts.roles_present.add(r["role"])

        found, how = _treatments(p, rows_by_file.get(p["filename"], []))
        for t in found:
            facts.vat_treatments.add(t)
            facts.provenance.setdefault(f"treatment:{t}", []).append(
                f"{p['filename']} — {how}")

    for box, amount in (declared or {}).items():
        if amount:
            facts.boxes_filed.add(box)
            facts.provenance.setdefault(f"box:{box}", []).append(
                f"declared {amount:,.2f} on the return")
    return facts


# ------------------------------------------------------------------ the predicate vocabulary
def applies(applies_when: dict, facts: CaseFacts) -> tuple[bool, str]:
    """Whether a control is in scope here, and the sentence explaining it either way.

    Deliberately a tiny closed vocabulary. A scope rule expressive enough to say anything is a
    scope rule nobody can review, and this is exactly the layer whose reviewability is the point.
    """
    if applies_when.get("always"):
        return True, "applies to every case"

    reasons: list[str] = []

    wanted = set(applies_when.get("has_dataset") or ())
    if wanted:
        hit = wanted & facts.dataset_types
        if not hit:
            return False, ("no " + " or ".join(sorted(w.replace("-", " ") for w in wanted))
                           + " is on the case")
        reasons.append(f"the case carries a {', '.join(sorted(hit)).replace('-', ' ')}")

    needed_roles = set(applies_when.get("has_role") or ())
    if needed_roles:
        missing = needed_roles - facts.roles_present
        if missing:
            return False, ("no dataset carries "
                           + ", ".join(sorted(m.replace("_", " ") for m in missing)))
        reasons.append("the required columns are present")

    treatments = set(applies_when.get("has_vat_treatment") or ())
    if treatments:
        hit = treatments & facts.vat_treatments
        if not hit:
            return False, (f"no {' or '.join(sorted(treatments))} supplies appear in the "
                           f"evidence")
        reasons.append(f"{', '.join(sorted(hit))} supplies appear in the evidence")

    boxes = set(applies_when.get("box_filed") or ())
    if boxes:
        hit = boxes & facts.boxes_filed
        if not hit:
            return False, "the return does not carry a figure in the relevant box"
        reasons.append("the return carries a figure in the relevant box")

    if not reasons:
        return False, "the control declares no circumstances that bring it into scope"
    return True, "; ".join(reasons)

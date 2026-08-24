"""Which comparisons this case's evidence supports, and what is missing for the rest.

The half of this that matters is the second half. A comparison that silently does not run looks
exactly like a comparison that ran and found nothing, and an auditor cannot tell the difference
without reading the source. So every definition in the registry produces an entry either way,
and a definition that cannot run says which document would unlock it — which is also the list
the chase letter should be asking for.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..evidence import profile as P
from ..evidence import roles as R
from . import registry as reg


@dataclass
class Plan:
    definition: reg.Definition
    runnable: bool
    #: The profiled dataset chosen for each side, by filename. Absent for a return box.
    sources: dict[str, str] = field(default_factory=dict)
    blocked_by: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = self.definition
        return {
            "id": d.id, "title": d.title, "workstream": d.workstream,
            "metric": d.metric, "metric_label": reg.METRIC_LABEL[d.metric],
            "grain": d.grain, "note": d.note,
            "sides": [d.a.describe(), d.b.describe()],
            "runnable": self.runnable, "sources": self.sources,
            "blocked_by": self.blocked_by, "needs": self.needs,
        }


def _pick(profiles: list[dict], dataset_type: str) -> dict | None:
    """The dataset for a type. An auditor-confirmed reading wins over an inferred one, then
    the larger file — a two-row extract and a two-thousand-row register both classified as a
    purchases listing are not equally likely to be the one the comparison wants."""
    matches = [p for p in profiles if p.get("dataset_type") == dataset_type]
    if not matches:
        return None
    rank = {"confirmed": 0, "high": 1, "medium": 2, "low": 3}
    matches.sort(key=lambda p: (rank.get(p.get("confidence", "low"), 4),
                                -int(p.get("record_count") or 0)))
    return matches[0]


def _has_roles(profile: dict, *roles: str) -> list[str]:
    """Which of these roles the dataset does not carry."""
    present = {r["role"] for r in profile.get("roles") or []}
    return [r for r in roles if r not in present]


def plan_one(definition: reg.Definition, profiles: list[dict], *,
             return_on_file: bool) -> Plan:
    plan = Plan(definition=definition, runnable=True)
    metric_role = reg.METRIC_ROLE[definition.metric]

    for label, side in (("a", definition.a), ("b", definition.b)):
        if side.kind == reg.RETURN_BOX:
            if not return_on_file:
                plan.runnable = False
                plan.blocked_by.append("no VAT return is on file for this period")
                plan.needs.append("the filed VAT return")
            continue

        chosen = _pick(profiles, side.dataset_type)
        if chosen is None:
            plan.runnable = False
            plan.blocked_by.append(
                f"no {P.LABEL.get(side.dataset_type, side.dataset_type).lower()} is on file")
            plan.needs.append(P.LABEL.get(side.dataset_type, side.dataset_type))
            continue

        plan.sources[label] = chosen["filename"]
        missing = _has_roles(chosen, metric_role, *definition.needs_roles)
        if missing:
            plan.runnable = False
            plan.blocked_by.append(
                f"{chosen['filename']} does not carry "
                + ", ".join(m.replace("_", " ") for m in missing))
            plan.needs.append(
                f"{', '.join(m.replace('_', ' ') for m in missing)} in "
                f"{P.LABEL.get(side.dataset_type, side.dataset_type).lower()}")

    return plan


def plan(profiles: list[dict], *, return_on_file: bool = True,
         workstream: str = "") -> list[Plan]:
    """Every definition, with whether it can run here. Ordered runnable-first."""
    defs = reg.for_workstream(workstream) if workstream else reg.DEFINITIONS
    plans = [plan_one(d, profiles, return_on_file=return_on_file) for d in defs]
    plans.sort(key=lambda p: (not p.runnable, p.definition.id))
    return plans

"""Run one comparison and say what it found, in the only five words it is allowed.

The order of work is the specification's, and the order matters:

    normalise  →  scope to the period  →  compare  →  attribute  →  classify

Comparing before scoping reports nine months of trade as a variance. Comparing before
normalising reports two systems that agree as disagreeing. Classifying before attributing calls
a rounding difference a variance. Each step feeds the next and none of them may be skipped
because the answer "looked obvious".

**Attribution is only claimed where it is real.** Against a single declared figure a difference
cannot be pinned on particular rows — the return is one number and the rows are not in it — so
a total-grain comparison returns no contributions and says why. A transaction-grain comparison
joins two populations and can name the documents on each side, so it does.

Every explanation this module writes passes `status.assert_neutral` before it leaves. That is
not decoration: the reconciliation stage is where a compliance word would first become
plausible, and once it is in the data it reaches the report and the taxpayer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import normalise as N
from . import registry as reg
from . import status as S
from . import tolerance as T
from .planner import Plan


def _sar(v: float) -> str:
    return f"SAR {abs(v):,.2f}"


@dataclass
class Contribution:
    """One row that accounts for part of a difference, and how much of it."""

    side: str
    reference: str
    amount: float
    row_number: int | None = None
    note: str = ""

    def to_dict(self) -> dict:
        return {"side": self.side, "reference": self.reference,
                "amount": round(self.amount, 2), "row_number": self.row_number,
                "note": self.note}


@dataclass
class Result:
    definition_id: str
    title: str
    workstream: str
    metric: str
    status: str
    value_a: float = 0.0
    value_b: float = 0.0
    variance: float = 0.0
    variance_pct: float = 0.0
    residual: float = 0.0
    label_a: str = ""
    label_b: str = ""
    source_a: str = ""
    source_b: str = ""
    grain: str = reg.TOTAL
    note: str = ""
    method: str = ""
    explanation: str = ""
    causes: list[dict] = field(default_factory=list)
    contributions: list[dict] = field(default_factory=list)
    tolerance: dict = field(default_factory=dict)
    period: dict = field(default_factory=dict)
    conventions: list[dict] = field(default_factory=list)
    quality_notes: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    #: The pairwise comparison that now owns this question, when one does. Published so the UI
    #: can show the dashboard's answer and not a second, differently-worded copy of it.
    superseded_by: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.definition_id, "title": self.title, "workstream": self.workstream,
            "metric": self.metric, "metric_label": reg.METRIC_LABEL.get(self.metric, self.metric),
            "status": self.status, "status_label": S.LABEL[self.status],
            "attention": S.ATTENTION[self.status],
            "value_a": round(self.value_a, 2), "value_b": round(self.value_b, 2),
            "variance": round(self.variance, 2), "variance_pct": round(self.variance_pct, 4),
            "residual": round(self.residual, 2),
            "label_a": self.label_a, "label_b": self.label_b,
            "source_a": self.source_a, "source_b": self.source_b,
            "grain": self.grain, "note": self.note, "method": self.method,
            "explanation": self.explanation, "causes": self.causes,
            "contributions": self.contributions, "tolerance": self.tolerance,
            "period": self.period, "conventions": self.conventions,
            "quality_notes": self.quality_notes,
            "blocked_by": self.blocked_by, "needs": self.needs,
            "superseded_by": self.superseded_by,
        }


def _not_run(p: Plan) -> Result:
    d = p.definition
    explanation = ("This comparison could not be run: " + "; ".join(p.blocked_by) + ". "
                   "That is a missing document rather than a difference, so no variance is "
                   "reported against it.")
    S.assert_neutral(explanation, where=d.id)
    return Result(definition_id=d.id, title=d.title, workstream=d.workstream, metric=d.metric,
                  status=S.INSUFFICIENT, label_a=d.a.describe(), label_b=d.b.describe(),
                  grain=d.grain, note=d.note, explanation=explanation,
                  superseded_by=d.superseded_by,
                  blocked_by=list(p.blocked_by), needs=list(p.needs),
                  method="not run — one or both sides are absent")


@dataclass
class Sourced:
    """One side of a comparison, resolved to a number and everything behind it."""

    label: str
    value: float
    filename: str = ""
    series: N.Series | None = None
    period: dict = field(default_factory=dict)
    rows: int = 0


def _resolve(side: reg.Side, definition: reg.Definition, plan_key: str, plan: Plan,
             profiles: dict[str, dict], rows_by_file: dict[str, list],
             declared: dict[str, float], period_from: date,
             period_to: date) -> Sourced | None:
    if side.kind == reg.RETURN_BOX:
        return Sourced(label=side.describe(), value=round(declared.get(side.box, 0.0), 2))

    filename = plan.sources.get(plan_key, "")
    profile = profiles.get(filename)
    if profile is None:
        return None
    s = N.series(profile, rows_by_file.get(filename, []), reg.METRIC_ROLE[definition.metric])
    if s is None:
        return None
    split = N.period_split(s, period_from, period_to)
    return Sourced(label=side.describe(), value=split["in_period_total"], filename=filename,
                   series=s, period=split, rows=split["in_period_count"])


def _causes(a: Sourced, b: Sourced, variance: float, tol: T.Tolerance,
            rows: int) -> tuple[list[dict], float]:
    """What deterministic analysis can account for, and what is left after it.

    Every cause here is established from the two sides themselves, never inferred. A cause that
    cannot be quantified is not recorded — "it might be timing" is a hypothesis, and hypotheses
    belong to the next stage, not this one.
    """
    causes: list[dict] = []
    residual = variance

    # --- period scope. The one cause that can account for the whole of a difference between a
    #     full-year export and a quarterly return, and the one most often mistaken for an error.
    for side, sourced in (("a", a), ("b", b)):
        out = sourced.period.get("out_of_period_total", 0.0)
        if out and abs(out) > tol.absolute:
            causes.append({
                "cause": S.PERIOD, "label": S.CAUSE_LABEL[S.PERIOD], "amount": round(out, 2),
                "side": side,
                "detail": (f"{sourced.period['out_of_period_count']} row(s) in "
                           f"{sourced.filename or sourced.label} fall outside the period under "
                           f"review, carrying {_sar(out)}. They are excluded from the figure "
                           f"compared above and are not themselves a defect.")})

    # --- sign convention. Recorded when a side had to be read against how it was written,
    #     because an auditor comparing by hand would otherwise get a different number.
    for side, sourced in (("a", a), ("b", b)):
        s = sourced.series
        if s is not None and s.convention == N.INVERTED:
            causes.append({
                "cause": S.SIGN, "label": S.CAUSE_LABEL[S.SIGN], "amount": 0.0, "side": side,
                "detail": (f"{sourced.filename or sourced.label}: {s.convention_note}. The "
                           f"figure above is the magnitude, so the two sides are comparable.")})

    # --- rounding. Only claimed where the difference is within what per-row rounding could
    #     produce and the tolerance profile actually models rounding.
    if tol.rounding_per_row and rows and abs(residual) <= tol.rounding_per_row * rows:
        causes.append({
            "cause": S.ROUNDING, "label": S.CAUSE_LABEL[S.ROUNDING],
            "amount": round(residual, 2), "side": "",
            "detail": (f"The difference is within {tol.rounding_per_row:g} per row across "
                       f"{rows} rows, which is what two systems rounding each line differently "
                       f"would produce.")})
        residual = 0.0

    return causes, round(residual, 2)


def _classify(variance: float, residual: float, tol: T.Tolerance, *,
              larger: float, rows: int, has_causes: bool, variance_full: float = 0.0) -> str:
    """Which of the five this is.

    `variance_full` is the difference before the period was scoped and the signs normalised;
    `residual` is what survives everything the engine could account for. The gap between them
    is what "partially reconciled" describes, and without carrying both there is no way to tell
    a comparison that explained half of a large difference from one that never had a large
    difference to explain.
    """
    allowance = tol.allowance(larger=larger, rows=rows)
    explained_something = has_causes and abs(variance_full) - abs(residual) > allowance

    if abs(residual) <= allowance:
        # Nothing material is left. Whether that is "reconciled" or "explained" depends on
        # whether anything had to be accounted for to get here.
        return S.EXPLAINED if explained_something else S.RECONCILED
    if explained_something:
        return S.PARTIAL
    return S.VARIANCE


def _quality_notes(profiles: dict[str, dict], plan: Plan) -> list[str]:
    """Defects in the very files this comparison rests on. A figure taken from a file with a
    blocking defect is a floor, and the result has to say so rather than present it as settled.
    """
    notes: list[str] = []
    for filename in plan.sources.values():
        p = profiles.get(filename) or {}
        for f in p.get("quality_flags") or []:
            if f["severity"] == "blocking" or f["code"] in (
                    "mixed-signs", "stated-total-does-not-foot", "repeated-reference",
                    "multiple-vat-rates"):
                notes.append(f"{filename}: {f['detail']}")
    return notes


def _transaction_contributions(a: Sourced, b: Sourced,
                               tol: T.Tolerance) -> tuple[list[Contribution], str]:
    """Join two populations on their references and name what each side holds alone.

    Deliberately a reference join and nothing cleverer yet: a match this reports is one an
    auditor can verify in their own spreadsheet in a second. Where one reference carries several
    rows the amounts are aggregated before comparison — one invoice legitimately spans several
    accounting lines, and treating that as duplication is a named failure mode.
    """
    def fold(s: N.Series | None) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in (s.points if s else []):
            key = (p.reference or "").strip().upper()
            if key:
                out[key] = round(out.get(key, 0.0) + p.value, 2)
        return out

    left, right = fold(a.series), fold(b.series)
    contributions: list[Contribution] = []

    for ref in sorted(set(left) - set(right)):
        contributions.append(Contribution(
            side="a", reference=ref, amount=left[ref],
            note=f"in {a.filename or a.label} only"))
    for ref in sorted(set(right) - set(left)):
        contributions.append(Contribution(
            side="b", reference=ref, amount=right[ref],
            note=f"in {b.filename or b.label} only"))
    for ref in sorted(set(left) & set(right)):
        delta = round(left[ref] - right[ref], 2)
        if abs(delta) > tol.absolute:
            contributions.append(Contribution(
                side="both", reference=ref, amount=delta,
                note=f"recorded as {_sar(left[ref])} and {_sar(right[ref])}"))

    method = (f"references joined after normalising case and spacing; {len(set(left) & set(right))} "
              f"matched, amounts aggregated per reference before comparison")
    return contributions, method


def run(plan: Plan, *, profiles: dict[str, dict], rows_by_file: dict[str, list],
        declared: dict[str, float], period_from: date, period_to: date) -> Result:
    """One comparison, start to finish."""
    d = plan.definition
    if not plan.runnable:
        return _not_run(plan)

    tol = T.get(d.tolerance)
    a = _resolve(d.a, d, "a", plan, profiles, rows_by_file, declared, period_from, period_to)
    b = _resolve(d.b, d, "b", plan, profiles, rows_by_file, declared, period_from, period_to)
    if a is None or b is None:
        return _not_run(Plan(definition=d, runnable=False,
                             blocked_by=["a source could not be read"],
                             needs=list(plan.needs)))

    # Both analyses, as §7 asks: the whole dataset as supplied, and the dataset scoped to the
    # period under review. The pair is what lets the engine say "period scope accounts for all
    # of it" or "for this much of it" — a single scoped comparison silently discards the
    # difference instead of explaining it, and the auditor never learns it was there.
    full_a = round(a.series.total if a.series is not None else a.value, 2)
    full_b = round(b.series.total if b.series is not None else b.value, 2)
    variance_full = round(full_a - full_b, 2)

    variance = round(a.value - b.value, 2)
    larger = max(abs(a.value), abs(b.value))
    rows = max(a.rows, b.rows)
    variance_pct = round(variance / larger, 4) if larger else 0.0

    causes, residual = _causes(a, b, variance, tol, rows)

    contributions: list[Contribution] = []
    if d.grain == reg.TRANSACTION:
        contributions, method = _transaction_contributions(a, b, tol)
    else:
        method = (f"{reg.METRIC_LABEL[d.metric]} summed over each side, scoped to the period "
                  f"under review; no qualification rule is applied to either")

    # Where the comparison is row by row, the two totals agreeing does not mean the two
    # populations do. Invoices absent from one side and a value difference on another can
    # very nearly cancel — on the seeded case they net to a twelfth of what is actually in
    # dispute — and a status read off the net figure would call that reconciled. Offsetting
    # errors concealing each other is exactly what a transaction-level comparison exists to
    # catch, so it is judged on the gross disagreement across the rows.
    gross = round(sum(abs(c.amount) for c in contributions), 2) if contributions else None
    judged = variance if gross is None else gross
    judged_residual = residual if gross is None else gross

    status = _classify(judged, judged_residual, tol, larger=larger, rows=rows,
                       has_causes=bool(causes),
                       variance_full=variance_full if gross is None else gross)

    explanation = _explain(d, a, b, variance, judged_residual, status, causes,
                           contributions, tol, larger=larger, rows=rows,
                           variance_full=variance_full)
    S.assert_neutral(explanation, where=d.id)

    return Result(
        definition_id=d.id, title=d.title, workstream=d.workstream, metric=d.metric,
        status=status, value_a=a.value, value_b=b.value, variance=variance,
        variance_pct=variance_pct, residual=judged_residual,
        label_a=a.label, label_b=b.label, source_a=a.filename, source_b=b.filename,
        grain=d.grain, note=d.note, method=method, explanation=explanation,
        superseded_by=d.superseded_by,
        causes=causes,
        contributions=[c.to_dict() for c in contributions[:200]],
        tolerance=tol.to_dict(larger=larger, rows=rows),
        period={"from": period_from.isoformat(), "to": period_to.isoformat(),
                "a": a.period, "b": b.period},
        conventions=[{"side": side, "source": s.filename or s.label,
                      "convention": s.series.convention, "note": s.series.convention_note}
                     for side, s in (("a", a), ("b", b)) if s.series is not None],
        quality_notes=_quality_notes(profiles, plan),
    )


def _explain(d: reg.Definition, a: Sourced, b: Sourced, variance: float, residual: float,
             status: str, causes: list[dict], contributions: list[Contribution],
             tol: T.Tolerance, *, larger: float, rows: int,
             variance_full: float = 0.0) -> str:
    """The engine's own account of what it did. Real digits are allowed — it computed them."""
    head = (f"{a.label} totals {_sar(a.value)} for the period; {b.label} is "
            f"{_sar(b.value)}.")

    if status == S.RECONCILED:
        allowance = tol.allowance(larger=larger, rows=rows)
        if abs(variance) <= 0.005:
            return head + " The two agree exactly."
        return (head + f" They differ by {_sar(variance)}, which is within the "
                       f"{_sar(allowance)} allowed by the '{tol.name}' tolerance for this "
                       f"comparison. The difference is reported rather than removed.")

    body = (f" The difference is {_sar(variance)}"
            f"{f' ({abs(variance) / larger:.1%} of the larger side)' if larger else ''}.")

    if causes:
        named = "; ".join(f"{c['label'].lower()} {_sar(c['amount'])}" if c["amount"]
                          else c["label"].lower() for c in causes)
        body += f" Deterministic analysis accounts for {named}."
    if status == S.EXPLAINED:
        body += " Nothing remains unaccounted for."
    elif status == S.PARTIAL:
        body += f" {_sar(residual)} remains without a deterministic cause."
    elif status == S.VARIANCE:
        body += (" No deterministic cause accounts for it, so what it represents is a question "
                 "for the investigation rather than something these figures settle.")

    if contributions:
        one_side = [c for c in contributions if c.side in ("a", "b")]
        differing = [c for c in contributions if c.side == "both"]
        gross = sum(abs(c.amount) for c in contributions)
        parts = []
        if one_side:
            parts.append(f"{len(one_side)} reference(s) appear on one side only")
        if differing:
            parts.append(f"{len(differing)} appear on both with different amounts")
        body += " " + " and ".join(parts).capitalize() + f", {_sar(gross)} across them."
        if abs(gross) > abs(variance) * 1.5:
            body += (f" The two totals differ by only {_sar(variance)} because those rows partly "
                     f"offset each other, so the totals agreeing would not have meant the "
                     f"populations did.")
    elif d.grain == reg.TOTAL:
        body += (" A difference against a single total cannot be attributed to particular rows, "
                 "so none is claimed here.")

    return head + body

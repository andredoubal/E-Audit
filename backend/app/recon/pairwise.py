"""The six comparisons, at three levels, over canonical records.

A case has three sources of truth per workstream and they can disagree in three different
pairings. Collapsing them into one "reconciliation" figure loses the only information that
matters — *which pair* disagrees — because the answer changes what the auditor does next:

    Register vs E-Invoices disagree     the taxpayer's own records are incomplete or the
                                        Authority holds documents they did not list
    E-Invoices vs Return disagree       what was cleared does not match what was declared
    Return vs Register disagree         what they recorded is not what they declared

So six comparisons — S1, S2, S3 and their purchase equivalents — each run at three levels,
because a difference invisible at one level is obvious at the next:

    Level 1  overall     taxable, VAT, gross, counts
    Level 2  treatment   the same comparison per VAT category, which is where a case whose
                         totals agree turns out to have moved money between boxes
    Level 3  transaction invoice by invoice, where both sides carry records

**A missing source is not a zero side.** Where one of the three is absent the comparison
reports that it could not be run and names what is missing. Where a *field* is absent — a file
with no gross column — the metric reports `unavailable` rather than a variance the size of the
other side.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..canonical.model import (Dataset, Record, TREATMENT_LABEL, TREATMENTS, UNCLASSIFIED)
from . import status as S
from . import tolerance as T

# ---------------------------------------------------------------- the three sources
RETURN = "vat-return"
REGISTER = "register"
EINVOICE = "e-invoices"

SOURCE_LABEL: dict[str, str] = {
    RETURN: "VAT return",
    REGISTER: "Taxpayer register",
    EINVOICE: "E-invoices",
}

# ---------------------------------------------------------------- the six pairings
@dataclass(frozen=True)
class Pairing:
    code: str                    # S1, S2, S3, P1, P2, P3
    workstream: str              # sales | purchases
    a: str
    b: str
    title: str
    question: str                # what a difference here would mean, in the auditor's terms


PAIRINGS: tuple[Pairing, ...] = (
    Pairing("S1", "sales", REGISTER, EINVOICE,
            "Sales register ↔ E-invoices",
            "Whether the taxpayer's own record of what they sold matches the invoice "
            "population held independently."),
    Pairing("S2", "sales", EINVOICE, RETURN,
            "E-invoices ↔ VAT return",
            "Whether the invoices evidenced independently match what was declared."),
    Pairing("S3", "sales", RETURN, REGISTER,
            "VAT return ↔ Sales register",
            "Whether what the taxpayer declared matches their own underlying records."),
    Pairing("P1", "purchases", REGISTER, EINVOICE,
            "Purchase register ↔ E-invoices",
            "Whether the taxpayer's record of what they bought matches the invoice population "
            "held independently."),
    Pairing("P2", "purchases", EINVOICE, RETURN,
            "E-invoices ↔ VAT return",
            "Whether the purchase invoices evidenced independently match the input VAT "
            "claimed."),
    Pairing("P3", "purchases", RETURN, REGISTER,
            "VAT return ↔ Purchase register",
            "Whether the input VAT claimed matches the taxpayer's own underlying records."),
)

BY_CODE: dict[str, Pairing] = {p.code: p for p in PAIRINGS}

# ---------------------------------------------------------------- metrics
VAT = "vat"
TAXABLE = "taxable"
GROSS = "gross"
METRIC_LABEL = {VAT: "VAT", TAXABLE: "Taxable amount", GROSS: "Gross amount"}

UNAVAILABLE = "unavailable"


@dataclass
class Side:
    """One source of a comparison, resolved. `total` of None means the field is not available."""

    source: str
    label: str
    origin: str = ""                 # the filename, or "the filed return"
    total: float | None = None
    count: int | None = None
    counted: int | None = None
    dataset: Dataset | None = None
    present: bool = True

    def to_dict(self) -> dict:
        return {"source": self.source, "label": self.label, "origin": self.origin,
                "total": self.total, "count": self.count, "counted": self.counted,
                "present": self.present}


@dataclass
class TreatmentRow:
    treatment: str
    label: str
    a_total: float | None
    b_total: float | None
    a_count: int
    b_count: int
    variance: float | None
    variance_pct: float | None
    status: str

    def to_dict(self) -> dict:
        return {"treatment": self.treatment, "label": self.label,
                "a_total": self.a_total, "b_total": self.b_total,
                "a_count": self.a_count, "b_count": self.b_count,
                "variance": self.variance, "variance_pct": self.variance_pct,
                "status": self.status, "status_label": S.LABEL[self.status]}


#: What a transaction-level comparison can conclude about one reference. Deliberately richer
#: than matched/unmatched: a date difference and a value difference need different questions
#: put to the taxpayer, and merging them loses that.
EXACT = "exact-match"
VALUE_MISMATCH = "value-mismatch"
VAT_MISMATCH = "vat-mismatch"
TREATMENT_MISMATCH = "treatment-mismatch"
DATE_MISMATCH = "date-mismatch"
PERIOD_MISMATCH = "tax-period-mismatch"
A_ONLY = "a-only"
B_ONLY = "b-only"
DUPLICATE = "duplicate"
NO_IDENTIFIER = "missing-identifier"

MATCH_LABEL: dict[str, str] = {
    EXACT: "Exact match",
    VALUE_MISMATCH: "Value mismatch",
    VAT_MISMATCH: "VAT mismatch",
    TREATMENT_MISMATCH: "VAT treatment mismatch",
    DATE_MISMATCH: "Date mismatch",
    PERIOD_MISMATCH: "Tax period mismatch",
    A_ONLY: "On the first source only",
    B_ONLY: "On the second source only",
    DUPLICATE: "Repeated identifier",
    NO_IDENTIFIER: "No identifier to match on",
}

#: Statuses that mean the two sides genuinely hold the same document.
AGREEING = (EXACT,)


@dataclass
class MatchRow:
    status: str
    reference: str
    a_records: list[str] = field(default_factory=list)
    b_records: list[str] = field(default_factory=list)
    a_amount: float | None = None
    b_amount: float | None = None
    delta: float | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {"status": self.status, "status_label": MATCH_LABEL[self.status],
                "reference": self.reference,
                "a_records": self.a_records, "b_records": self.b_records,
                "a_amount": self.a_amount, "b_amount": self.b_amount,
                "delta": self.delta, "detail": self.detail}


@dataclass
class Comparison:
    pairing: Pairing
    metric: str
    a: Side
    b: Side
    runnable: bool = True
    blocked_by: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    variance: float | None = None
    variance_pct: float | None = None
    status: str = S.INSUFFICIENT
    tolerance: dict = field(default_factory=dict)
    treatments: list[TreatmentRow] = field(default_factory=list)
    matches: list[MatchRow] = field(default_factory=list)
    match_counts: dict[str, int] = field(default_factory=dict)
    match_values: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "code": self.pairing.code, "workstream": self.pairing.workstream,
            "title": self.pairing.title, "question": self.pairing.question,
            "metric": self.metric, "metric_label": METRIC_LABEL[self.metric],
            "a": self.a.to_dict(), "b": self.b.to_dict(),
            "runnable": self.runnable, "blocked_by": self.blocked_by, "needs": self.needs,
            "variance": self.variance, "variance_pct": self.variance_pct,
            "status": self.status, "status_label": S.LABEL[self.status],
            "attention": S.ATTENTION[self.status],
            "tolerance": self.tolerance,
            "treatments": [t.to_dict() for t in self.treatments],
            "matches": [m.to_dict() for m in self.matches[:500]],
            "match_counts": self.match_counts, "match_values": self.match_values,
            "notes": self.notes,
        }


# ------------------------------------------------------------------ level 1
def _classify(variance: float | None, tol: T.Tolerance, larger: float, rows: int) -> str:
    if variance is None:
        return S.INSUFFICIENT
    return S.RECONCILED if tol.within(variance, larger=larger, rows=rows) else S.VARIANCE


def compare(pairing: Pairing, a: Side, b: Side, metric: str, *,
            tol: T.Tolerance | None = None) -> Comparison:
    """One pairing at all three levels, as far as the evidence allows."""
    tol = tol or T.DECLARED
    c = Comparison(pairing=pairing, metric=metric, a=a, b=b)

    if not a.present or not b.present:
        c.runnable = False
        for side in (a, b):
            if not side.present:
                c.blocked_by.append(f"no {side.label.lower()} is on the case")
                c.needs.append(side.label)
        c.status = S.INSUFFICIENT
        return c

    if a.total is None or b.total is None:
        c.runnable = False
        for side in (a, b):
            if side.total is None:
                c.blocked_by.append(
                    f"{side.origin or side.label} does not carry a readable "
                    f"{METRIC_LABEL[metric].lower()}")
                c.needs.append(f"{METRIC_LABEL[metric]} in {side.label.lower()}")
        c.status = S.INSUFFICIENT
        return c

    c.variance = round(a.total - b.total, 2)
    larger = max(abs(a.total), abs(b.total))
    c.variance_pct = round(c.variance / larger, 4) if larger else None
    rows = max(a.count or 0, b.count or 0)
    c.status = _classify(c.variance, tol, larger, rows)
    c.tolerance = tol.to_dict(larger=larger, rows=rows)

    # --- level 2, where both sides carry records to break down
    if a.dataset is not None and b.dataset is not None:
        c.treatments = _by_treatment(a.dataset, b.dataset, metric, tol)
    elif a.dataset is not None or b.dataset is not None:
        c.notes.append(
            "A VAT-treatment breakdown needs records on both sides. The VAT return is a set of "
            "declared totals rather than transactions, so this pairing is compared at the "
            "overall level only.")

    # --- level 3, likewise
    if a.dataset is not None and b.dataset is not None:
        c.matches = match(a.dataset, b.dataset, metric, tol)
        c.match_counts = {}
        c.match_values = {}
        for m in c.matches:
            c.match_counts[m.status] = c.match_counts.get(m.status, 0) + 1
            c.match_values[m.status] = round(
                c.match_values.get(m.status, 0.0)
                + abs(m.delta if m.delta is not None else (m.a_amount or m.b_amount or 0.0)), 2)
        # The totals agreeing does not mean the populations do: rows absent from one side and a
        # value difference on another can very nearly cancel. Judged on the gross disagreement.
        disagreeing = round(sum(v for k, v in c.match_values.items() if k not in AGREEING), 2)
        if disagreeing and not tol.within(disagreeing, larger=larger, rows=rows):
            c.status = S.VARIANCE
            if c.variance is not None and abs(disagreeing) > abs(c.variance) * 1.5:
                c.notes.append(
                    f"The two totals differ by only SAR {abs(c.variance):,.2f}, but "
                    f"SAR {disagreeing:,.2f} of records disagree — those rows partly offset each "
                    f"other, so the totals agreeing would not have meant the populations did.")

    return c


# ------------------------------------------------------------------ level 2
def _by_treatment(a: Dataset, b: Dataset, metric: str,
                  tol: T.Tolerance) -> list[TreatmentRow]:
    """The same comparison per VAT category.

    Where a case's totals agree and its categories do not, this is the only level that shows
    it — and money moved between zero-rated and standard-rated is exactly the shape of thing
    that nets to nothing overall.
    """
    ta, tb = a.by_treatment(metric), b.by_treatment(metric)
    out: list[TreatmentRow] = []
    for t in TREATMENTS:
        if t not in ta and t not in tb:
            continue
        ra, rb = ta.get(t), tb.get(t)
        a_total = ra["total"] if ra else (0.0 if metric in a.fields_available else None)
        b_total = rb["total"] if rb else (0.0 if metric in b.fields_available else None)
        variance = (round(a_total - b_total, 2)
                    if a_total is not None and b_total is not None else None)
        larger = max(abs(a_total or 0.0), abs(b_total or 0.0))
        out.append(TreatmentRow(
            treatment=t, label=TREATMENT_LABEL[t],
            a_total=a_total, b_total=b_total,
            a_count=ra["count"] if ra else 0, b_count=rb["count"] if rb else 0,
            variance=variance,
            variance_pct=(round(variance / larger, 4)
                          if variance is not None and larger else None),
            status=_classify(variance, tol, larger,
                             max(ra["count"] if ra else 0, rb["count"] if rb else 0))))
    return out


# ------------------------------------------------------------------ level 3
def match(a: Dataset, b: Dataset, metric: str, tol: T.Tolerance) -> list[MatchRow]:
    """Invoice by invoice, on the identifier both sides carry.

    Deliberately an identifier join and nothing cleverer. A match this reports is one an auditor
    can verify in their own spreadsheet in a second, and a probable match nobody can check is
    worse than an honest "on one side only". Where one reference carries several rows the
    amounts are aggregated before comparison: one invoice legitimately spans several accounting
    lines, and calling that duplication is a named failure mode.
    """
    def fold(ds: Dataset) -> tuple[dict[str, list[Record]], list[Record]]:
        keyed: dict[str, list[Record]] = {}
        unkeyed: list[Record] = []
        for r in ds.records:
            if r.invoice_key:
                keyed.setdefault(r.invoice_key, []).append(r)
            else:
                unkeyed.append(r)
        return keyed, unkeyed

    ka, ua = fold(a)
    kb, ub = fold(b)
    out: list[MatchRow] = []

    for side, unkeyed, ds in (("a", ua, a), ("b", ub, b)):
        if unkeyed:
            out.append(MatchRow(
                status=NO_IDENTIFIER, reference="",
                **{f"{side}_records": [r.record_id for r in unkeyed]},
                **{f"{side}_amount": round(sum(r.amount(metric) or 0.0 for r in unkeyed), 2)},
                detail=(f"{len(unkeyed)} record(s) in {ds.source_file} carry no invoice "
                        f"identifier, so they cannot be matched to the other source. They are "
                        f"reported rather than treated as absent.")))

    for key in sorted(set(ka) | set(kb)):
        ra, rb = ka.get(key, []), kb.get(key, [])
        shown = (ra or rb)[0].invoice_id or key
        a_amt = round(sum(r.amount(metric) or 0.0 for r in ra), 2) if ra else None
        b_amt = round(sum(r.amount(metric) or 0.0 for r in rb), 2) if rb else None

        if ra and not rb:
            out.append(MatchRow(status=A_ONLY, reference=shown,
                                a_records=[r.record_id for r in ra], a_amount=a_amt,
                                detail=f"in {a.source_file} only"))
            continue
        if rb and not ra:
            out.append(MatchRow(status=B_ONLY, reference=shown,
                                b_records=[r.record_id for r in rb], b_amount=b_amt,
                                detail=f"in {b.source_file} only"))
            continue

        delta = round((a_amt or 0.0) - (b_amt or 0.0), 2)
        ids = {"a_records": [r.record_id for r in ra], "b_records": [r.record_id for r in rb]}
        span = (f"{len(ra)} line(s) against {len(rb)}"
                if len(ra) > 1 or len(rb) > 1 else "")

        # Ordered: the strongest disagreement is the one reported, so one document produces
        # one row and a value difference is not also reported as a date difference.
        if abs(delta) > tol.absolute:
            status = VAT_MISMATCH if metric == VAT else VALUE_MISMATCH
            detail = (f"recorded as {a_amt:,.2f} and {b_amt:,.2f}"
                      + (f" ({span})" if span else ""))
        elif {r.vat_treatment for r in ra} != {r.vat_treatment for r in rb}:
            status = TREATMENT_MISMATCH
            detail = (f"treated as {', '.join(sorted({TREATMENT_LABEL[r.vat_treatment] for r in ra}))} "
                      f"and {', '.join(sorted({TREATMENT_LABEL[r.vat_treatment] for r in rb}))}")
        elif ({r.tax_period for r in ra if r.tax_period}
              != {r.tax_period for r in rb if r.tax_period}
              and any(r.tax_period for r in ra) and any(r.tax_period for r in rb)):
            status = PERIOD_MISMATCH
            detail = (f"in tax period {', '.join(sorted({r.tax_period for r in ra if r.tax_period}))} "
                      f"on one side and "
                      f"{', '.join(sorted({r.tax_period for r in rb if r.tax_period}))} on the "
                      f"other. Recorded as a timing difference, not as a defect.")
        elif ({r.transaction_date for r in ra if r.transaction_date}
              != {r.transaction_date for r in rb if r.transaction_date}
              and any(r.transaction_date for r in ra)
              and any(r.transaction_date for r in rb)):
            status = DATE_MISMATCH
            detail = "the two sources date the same document differently"
        elif len(ra) > 1 and len(rb) == 1 or len(rb) > 1 and len(ra) == 1:
            status = EXACT
            detail = (f"{span} — aggregated before comparison, because one invoice legitimately "
                      f"spans several accounting lines")
        else:
            status = EXACT
            detail = ""

        out.append(MatchRow(status=status, reference=shown, a_amount=a_amt, b_amount=b_amt,
                            delta=delta if status in (VALUE_MISMATCH, VAT_MISMATCH) else None,
                            detail=detail, **ids))

    return out

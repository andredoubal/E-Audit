"""The reconciliation dashboard for a case: three sources, six comparisons, three levels.

Assembles the whole deterministic picture and nothing else. No model is called from this file or
anything it imports, which is what makes every figure on the dashboard reproducible and testable
without credentials.

The KPI set is built from what the case actually has. A card for a dataset that is not there
would either read zero — which is a lie — or be empty, which trains an auditor to skim past the
row. So a KPI that cannot be computed is omitted and the reason is published separately, in the
same place the comparisons publish what they could not run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..canonical import build as canon
from ..canonical.model import (CREDIT_NOTE, DEBIT_NOTE, Dataset, EXEMPT, PURCHASE, SALE,
                               STANDARD, TREATMENT_LABEL, TREATMENTS, ZERO_RATED)
from ..evidence import profile as prof
from ..evidence import service as evidence_service
from ..models import AuditCase, VatReturn
from ..pipeline.rules import BOX_PURCHASE, BOX_SALES, BOX_ZERO_RATED_SALES
from . import observations as obs
from . import pairwise as P
from . import status as S
from . import tolerance as T
from .. import vat_boxes as vb

#: Which profiled dataset types stand in for each of the three sources.
_REGISTER_TYPES = {SALE: (prof.SALES_REGISTER,), PURCHASE: (prof.PURCHASE_REGISTER,)}
_EINVOICE_TYPES = (prof.EINVOICE_EXTRACT,)

#: Which return box carries the declared figure for a workstream and metric.
_BOX = {("sales", "vat"): BOX_SALES, ("purchases", "vat"): BOX_PURCHASE}


def _pick(profiles: list[dict], types: tuple[str, ...]) -> dict | None:
    """The dataset for a role. An auditor-confirmed reading beats an inferred one, then size."""
    matches = [p for p in profiles if p.get("dataset_type") in types]
    if not matches:
        return None
    rank = {"confirmed": 0, "high": 1, "medium": 2, "low": 3}
    matches.sort(key=lambda p: (rank.get(p.get("confidence", "low"), 4),
                                -int(p.get("record_count") or 0)))
    return matches[0]


def _return_boxes(db: Session, case: AuditCase) -> tuple[dict[str, float], bool]:
    ret = db.scalar(select(VatReturn).where(
        VatReturn.taxpayer_id == case.taxpayer_id,
        VatReturn.period_from == case.period_from,
        VatReturn.current_flag.is_(True)))
    if ret is None:
        return {}, False
    return {b.box_code: round(float(b.vat_amount), 2) for b in ret.boxes}, True


def _return_adjustments(db: Session, case: AuditCase) -> dict[str, float]:
    """The taxpayer's own adjustment per box. The return carries its own column for it, and a
    box whose declaration is an adjustment rather than a supply reads very differently."""
    ret = db.scalar(select(VatReturn).where(
        VatReturn.taxpayer_id == case.taxpayer_id,
        VatReturn.period_from == case.period_from,
        VatReturn.current_flag.is_(True)))
    if ret is None:
        return {}
    return {b.box_code: round(float(b.adjustment or 0), 2) for b in ret.boxes}


def _return_bases(db: Session, case: AuditCase) -> dict[str, float]:
    ret = db.scalar(select(VatReturn).where(
        VatReturn.taxpayer_id == case.taxpayer_id,
        VatReturn.period_from == case.period_from,
        VatReturn.current_flag.is_(True)))
    if ret is None:
        return {}
    return {b.box_code: round(float(b.base_amount or 0), 2) for b in ret.boxes}


@dataclass
class Sources:
    """The three sources for one workstream, canonicalised where they exist."""

    workstream: str
    register: Dataset | None = None
    einvoices: Dataset | None = None
    declared_vat: float | None = None
    declared_base: float | None = None
    return_on_file: bool = False
    #: Extracts whose side could not be established. Reported rather than pressed into
    #: service on whichever workstream happened to ask first.
    unusable_einvoices: list[dict] = field(default_factory=list)
    #: Customs declarations, split by what they declare. These carry a value in SAR and no tax
    #: at all, so they can only ever evidence a box's *base*.
    customs_import: Dataset | None = None
    customs_export: Dataset | None = None

    def side(self, which: str, metric: str) -> P.Side:
        if which == P.RETURN:
            total = self.declared_vat if metric == "vat" else self.declared_base
            return P.Side(source=P.RETURN, label=P.SOURCE_LABEL[P.RETURN],
                          origin="the filed VAT return",
                          total=total, count=None, counted=None,
                          present=self.return_on_file)
        ds = self.register if which == P.REGISTER else self.einvoices
        label = ("Sales register" if which == P.REGISTER and self.workstream == "sales" else
                 "Purchase register" if which == P.REGISTER else
                 P.SOURCE_LABEL[P.EINVOICE])
        if ds is None:
            return P.Side(source=which, label=label, present=False)
        return P.Side(source=which, label=label, origin=ds.source_file,
                      total=ds.total(metric), count=ds.count, counted=ds.counted(metric),
                      dataset=ds, present=True)


def _sources(db: Session, case: AuditCase, profiles: list[dict],
             rows_by_file: dict[str, list]) -> dict[str, Sources]:
    boxes, on_file = _return_boxes(db, case)
    bases = _return_bases(db, case)
    out: dict[str, Sources] = {}

    for workstream, direction in (("sales", SALE), ("purchases", PURCHASE)):
        s = Sources(workstream=workstream, return_on_file=on_file)
        # What the taxpayer declared on this side of the return: *every* box on it, not the
        # standard-rated one alone.
        #
        # The pairings compare a whole population against this figure — the register and the
        # e-invoice extract hold all of the taxpayer's sales, zero-rated and 5%-rated supplies
        # among them. Set against the standard-rated box by itself, every riyal declared in
        # another box came back as undeclared: on the demo case S2 reported SAR 630,000 against
        # the return when SAR 245,000 of it was declared in the Etimad, 5% and citizen boxes,
        # and the box-by-box matrix directly below said so. Four boxes hid this; fifteen make
        # it obvious.
        codes = [b.code for b in vb.for_workstream(workstream)]
        if on_file:
            declared = [boxes[c] for c in codes if c in boxes]
            based = [bases[c] for c in codes if c in bases]
            s.declared_vat = round(sum(declared), 2) if declared else None
            s.declared_base = round(sum(based), 2) if based else None

        reg = _pick(profiles, _REGISTER_TYPES[direction])
        if reg:
            s.register = canon.build(reg, rows_by_file.get(reg["filename"], []),
                                     direction=direction)

        # An e-invoice extract belongs to the side its own columns name. That has to be
        # *established*, never defaulted: an extract of sales invoices used as the purchases
        # population produces a comparison against the input box with a variance the size of
        # the whole file — a fabricated finding out of a dataset the case does not have.
        for ein in _einvoice_datasets(profiles):
            side, why = _extract_side(ein)
            if side is None:
                s.unusable_einvoices.append(
                    {"filename": ein["filename"], "why": why})
                continue
            if side != direction:
                continue
            s.einvoices = canon.build(ein, rows_by_file.get(ein["filename"], []),
                                      direction=direction)
            break
        for cd in profiles:
            if cd.get("dataset_type") != prof.CUSTOMS_RECORDS:
                continue
            ds = canon.build(cd, rows_by_file.get(cd["filename"], []), direction=direction)
            # Import or export is read from the sheet the Authority named, not guessed: an
            # export declaration counted as an import would evidence the wrong box entirely.
            name = cd["filename"].lower()
            if "export" in name or "صادر" in cd["filename"]:
                if workstream == "sales":
                    s.customs_export = ds
            elif "import" in name or "وارد" in cd["filename"]:
                if workstream == "purchases":
                    s.customs_import = ds

        out[workstream] = s
    return out


def _einvoice_datasets(profiles: list[dict]) -> list[dict]:
    return [p for p in profiles if p.get("dataset_type") in _EINVOICE_TYPES]


def _extract_side(profile: dict) -> tuple[str | None, str]:
    """Which side of a transaction an e-invoice extract describes, from its own columns.

    The taxpayer is the seller on their sales and the buyer on their purchases, so an extract
    that names a *customer* is their output side and one that names a *supplier* is their input
    side. An extract naming both, or neither, is left unassigned and reported: an auditor can
    say which it is, and a guess here moves a whole population into the wrong box.
    """
    from ..evidence import roles as R

    detected = [R.Role(role=r["role"], column=r["column"], side=r.get("side", ""),
                       confidence=r.get("confidence", "low"), why=r.get("why", ""))
                for r in profile.get("roles") or []]
    side, why = R.side_of(detected)
    if side == R.CUSTOMER:
        return SALE, why
    if side == R.SUPPLIER:
        return PURCHASE, why
    return None, (f"{profile['filename']}: {why}. It is not used for either workstream until "
                  f"the side is settled, because an extract of one side used as the other "
                  f"produces a comparison against a population the case does not have.")


# ------------------------------------------------------------------ KPIs
def _kpis(s: Sources) -> list[dict]:
    """Only what the evidence supports. An empty card teaches an auditor to skim."""
    out: list[dict] = []

    def add(key: str, label: str, value, *, unit: str = "sar", note: str = "",
            source: str = "") -> None:
        if value is None:
            return
        out.append({"key": key, "label": label, "value": value, "unit": unit,
                    "note": note, "source": source})

    add("declared_vat", f"{'Output' if s.workstream == 'sales' else 'Input'} VAT declared",
        s.declared_vat, source="VAT return")
    add("declared_base",
        f"{'Sales' if s.workstream == 'sales' else 'Purchases'} declared",
        s.declared_base, source="VAT return")

    for ds, name in ((s.register, "register"), (s.einvoices, "einvoices")):
        if ds is None:
            continue
        label = "Register" if name == "register" else "E-invoices"
        add(f"{name}_vat", f"{label} VAT", ds.total("vat"), source=ds.source_file)
        add(f"{name}_base", f"{label} taxable amount", ds.total("taxable"),
            source=ds.source_file)
        add(f"{name}_count", f"{label} records", ds.count, unit="count",
            source=ds.source_file)
        counted = ds.counted("vat")
        if counted != ds.count:
            add(f"{name}_counted", f"{label} records carrying VAT", counted, unit="count",
                note=f"{ds.count - counted} record(s) carry no readable VAT amount and are "
                     f"skipped rather than summed as zero",
                source=ds.source_file)
        total = ds.total("vat")
        if total is not None and counted:
            add(f"{name}_average", f"{label} average VAT per record",
                round(total / counted, 2), source=ds.source_file)

        notes = [r for r in ds.records if r.transaction_type in (CREDIT_NOTE, DEBIT_NOTE)]
        if notes:
            add(f"{name}_notes_count", f"{label} credit and debit notes", len(notes),
                unit="count", source=ds.source_file)
            add(f"{name}_notes_value", f"{label} credit and debit note VAT",
                round(sum(r.vat_amount or 0.0 for r in notes), 2), source=ds.source_file)

        for treatment in (ZERO_RATED, EXEMPT):
            rows = [r for r in ds.records if r.vat_treatment == treatment]
            if rows:
                add(f"{name}_{treatment}_count",
                    f"{label} {TREATMENT_LABEL[treatment].lower()} records", len(rows),
                    unit="count", source=ds.source_file)
                add(f"{name}_{treatment}_base",
                    f"{label} {TREATMENT_LABEL[treatment].lower()} taxable amount",
                    round(sum(r.taxable_amount or 0.0 for r in rows), 2),
                    source=ds.source_file)
    return out


def _unavailable(s: Sources) -> list[dict]:
    """What could not be measured, and why. Published rather than left as an absence."""
    out: list[dict] = []
    if not s.return_on_file:
        out.append({"what": "Everything declared", "why": "no VAT return is on file for this "
                                                          "period"})
    if s.register is None:
        out.append({"what": f"{'Sales' if s.workstream == 'sales' else 'Purchase'} register "
                            f"figures",
                    "why": "no register of that kind has been filed on the case"})
    if s.einvoices is None:
        out.append({"what": "E-invoice figures",
                    "why": "no e-invoice extract for this side has been loaded"})
    for u in s.unusable_einvoices:
        out.append({"what": f"E-invoice figures from {u['filename']}", "why": u["why"]})
    for ds in (s.register, s.einvoices):
        if ds is None:
            continue
        for metric in ("vat", "taxable", "gross"):
            if metric not in ds.fields_available:
                out.append({"what": f"{P.METRIC_LABEL[metric]} in {ds.source_file}",
                            "why": "the file carries no such column, so it is reported as "
                                   "unavailable rather than as zero"})
    return out


# ------------------------------------------------------------------ the whole thing
def build_for(db: Session, case_id: str) -> dict:
    case = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if case is None:
        raise ValueError("case not found")

    profiles = evidence_service.profiles(db, case_id)
    rows_by_file = evidence_service.rows_by_file(db, case_id)
    sources = _sources(db, case, profiles, rows_by_file)
    boxes, _on_file = _return_boxes(db, case)
    bases = _return_bases(db, case)
    adjustments = _return_adjustments(db, case)

    comparisons: list[P.Comparison] = []
    for pairing in P.PAIRINGS:
        s = sources[pairing.workstream]
        # VAT is the metric every pairing can carry: the return declares it, and both
        # populations state it per record. Taxable amount is compared as well wherever both
        # sides have it, because a difference in base with matching VAT is a rate question.
        for metric, tol in (("vat", T.DECLARED), ("taxable", T.DECLARED)):
            a, b = s.side(pairing.a, metric), s.side(pairing.b, metric)
            if metric == "taxable" and (a.total is None or b.total is None):
                continue
            comparisons.append(P.compare(pairing, a, b, metric, tol=tol))

    observations, exceptions = obs.derive(comparisons)

    return {
        "case_id": case_id,
        "period_from": case.period_from.isoformat(),
        "period_to": case.period_to.isoformat(),
        "workstreams": {
            ws: {
                "kpis": _kpis(sources[ws]),
                "unavailable": _unavailable(sources[ws]),
                "sources": {
                    "return_on_file": sources[ws].return_on_file,
                    "register": (sources[ws].register.to_dict()
                                 if sources[ws].register else None),
                    "einvoices": (sources[ws].einvoices.to_dict()
                                  if sources[ws].einvoices else None),
                    "customs_import": (sources[ws].customs_import.to_dict()
                                       if sources[ws].customs_import else None),
                    "customs_export": (sources[ws].customs_export.to_dict()
                                       if sources[ws].customs_export else None),
                },
                "summary": _summary([c for c in comparisons
                                     if c.pairing.workstream == ws],
                                    [e for e in exceptions if e.workstream == ws]),
                "cards": _cards([c for c in comparisons if c.pairing.workstream == ws]),
                "matrix": _matrix(sources[ws], boxes, bases, adjustments),
            }
            for ws in ("sales", "purchases")
        },
        "comparisons": [c.to_dict() for c in comparisons],
        "observations": [o.to_dict() for o in observations],
        "exceptions": [e.to_dict() for e in exceptions],
    }


def _summary(comparisons: list[P.Comparison], exceptions: list[obs.Exception_]) -> dict:
    ran = [c for c in comparisons if c.runnable]
    variances = [c for c in ran if c.status == S.VARIANCE]
    material = [e for e in exceptions if e.kind != obs.NOT_RUN and e.variance]
    # Ranked within one metric only. A taxable amount is about six and a half times the VAT on
    # it, so ranking the two together would hand "largest" to whichever exception happened to be
    # measured in the base — a bigger number about less money.
    comparable = [e for e in material if e.metric == "vat"] or material
    largest = max(comparable, key=lambda e: abs(e.variance or 0.0), default=None)
    return {
        "comparisons_total": len(comparisons),
        "comparisons_run": len(ran),
        "with_variance": len(variances),
        "exceptions": len([e for e in exceptions if e.kind != obs.NOT_RUN]),
        # Deliberately not a total. Three comparisons over the same two files disagree about the
        # same money three times, and the same disagreement is measured again in taxable amount
        # underneath its VAT; adding those reported SAR 15.8m on a case whose sales excess is
        # SAR 618k. The largest single exception is a figure that corresponds to something, and
        # what it rests on is named beside it.
        "largest_exception": round(abs(largest.variance or 0.0), 2) if largest else 0.0,
        "largest_exception_is": (f"{largest.reconciliation}, {largest.category.lower()}"
                                 if largest else ""),
        "not_summed_because": ("Exceptions across these comparisons rest on the same records, "
                               "so they are not added together. Each is stated on its own."
                               if len(material) > 1 else ""),
        "needs": sorted({n for c in comparisons for n in c.needs}),
    }


# ------------------------------------------------------------------ the comparison cards
#: The metrics a card states, in the order an auditor reads them.
_CARD_METRICS = (("taxable", "Taxable amount"), ("vat", "VAT"))

#: Which match statuses are worth their own box on a card's stat strip, and what to call them.
_STRIP = (
    ("matched", "Matched invoices", (P.EXACT,)),
    ("unmatched_a", "Unmatched (first source)", (P.A_ONLY,)),
    ("unmatched_b", "Unmatched (second source)", (P.B_ONLY,)),
    ("value", "Value or VAT differs", (P.VALUE_MISMATCH, P.VAT_MISMATCH)),
    ("timing", "Different period", (P.PERIOD_MISMATCH, P.DATE_MISMATCH)),
    ("treatment", "Treatment differs", (P.TREATMENT_MISMATCH,)),
    ("duplicate", "Duplicates", (P.DUPLICATE,)),
    ("no_id", "No identifier", (P.NO_IDENTIFIER,)),
)


def _cards(comparisons: list[P.Comparison]) -> list[dict]:
    """One card per pairing, stating every metric it could be measured in.

    The comparisons are computed per metric — VAT and taxable amount are separate runs, because
    a difference in base with matching VAT is a rate question and a different finding. An
    auditor reads them together, so they are grouped here rather than in the UI: which metrics a
    pairing carries is a property of the evidence, and the screen should not have to work it out.

    A metric row is present only where both sides carry it. An absent row is left out rather
    than shown as zero — the distinction the canonical layer exists to keep.
    """
    by_code: dict[str, list[P.Comparison]] = {}
    for c in comparisons:
        by_code.setdefault(c.pairing.code, []).append(c)

    out: list[dict] = []
    for code, group in by_code.items():
        first = group[0]
        rows: list[dict] = []
        for metric, label in _CARD_METRICS:
            c = next((x for x in group if x.metric == metric), None)
            if c is None or c.a.total is None or c.b.total is None:
                continue
            rows.append({
                "metric": metric, "label": label,
                "a": c.a.total, "b": c.b.total,
                "variance": c.variance, "variance_pct": c.variance_pct,
                "status": c.status, "status_label": S.LABEL[c.status],
            })

        # The record count is a comparison in its own right: two sources can agree on value
        # while holding a different number of documents, which is an offsetting pair rather
        # than agreement. Stated only where both sides actually count records — the VAT return
        # declares totals, not documents, so a pairing against it has no count row.
        if first.a.count is not None and first.b.count is not None:
            rows.append({
                "metric": "count", "label": "Invoice count",
                "a": first.a.count, "b": first.b.count,
                "variance": first.a.count - first.b.count,
                "variance_pct": (round((first.a.count - first.b.count) / first.b.count, 4)
                                 if first.b.count else None),
                "status": "", "status_label": "",
            })

        counts = first.match_counts or {}
        strip = [{"key": key, "label": label,
                  "count": sum(counts.get(st, 0) for st in statuses)}
                 for key, label, statuses in _STRIP
                 if sum(counts.get(st, 0) for st in statuses)]

        out.append({
            "code": code, "title": first.pairing.title, "question": first.pairing.question,
            "workstream": first.pairing.workstream,
            "a_label": first.a.label, "b_label": first.b.label,
            "a_origin": first.a.origin, "b_origin": first.b.origin,
            "runnable": first.runnable, "blocked_by": first.blocked_by,
            "status": first.status, "status_label": S.LABEL[first.status],
            "rows": rows, "strip": strip,
        })
    return out


# ------------------------------------------------------------------ the return, box by box
def _matrix(s: Sources, boxes: dict[str, float], bases: dict[str, float],
            adjustments: dict[str, float]) -> dict:
    """Every box the return declares, against whatever evidences it.

    The rows are the **return's own boxes**, not our canonical treatments. Those are two
    different vocabularies and conflating them loses exactly what an auditor is looking for: the
    return keeps 15% apart from 5%, imports cleared at customs apart from imports under reverse
    charge, and domestic zero-rated apart from exports, and a row per treatment silently merges
    each of those pairs.

    Three kinds of row come out, and the difference between them is the point:

    - **Evidenced by the records** — the register and the extract, scoped to that box's rate and
      treatment. A real comparison, with a real variance.
    - **Evidenced by customs** — the import and export declarations. Those carry a value in SAR
      and no tax at all, so the comparison is against the box's *base* and the VAT column is
      left empty rather than filled with a figure customs never stated.
    - **Declared only** — nothing on the case can evidence it. No variance is computed, and the
      reason is carried on the row. Comparing such a box against nothing and calling the result
      zero would manufacture a variance the size of the declaration.
    """
    reg, ein = s.register, s.einvoices
    direction = SALE if s.workstream == "sales" else PURCHASE

    def records_for(box) -> tuple[float | None, float | None, int | None,
                                  float | None, float | None, int | None]:
        """Register and e-invoice figures for one box: base, VAT and count on each side."""
        def side(ds):
            if ds is None:
                return None, None, None
            rows = [r for r in ds.records
                    if vb.records_box(direction, r.vat_treatment, r.vat_rate) is box]
            if not rows:
                return None, None, 0
            base = ([r.taxable_amount for r in rows if r.taxable_amount is not None]
                    if "taxable" in ds.fields_available else [])
            vat = ([r.vat_amount for r in rows if r.vat_amount is not None]
                   if "vat" in ds.fields_available else [])
            return (round(sum(base), 2) if base else None,
                    round(sum(vat), 2) if vat else None, len(rows))
        return side(reg) + side(ein)

    def diff(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else round(a - b, 2)

    rows: list[dict] = []
    for box in vb.for_workstream(s.workstream):
        d_base = bases.get(box.code) if s.return_on_file else None
        d_vat = boxes.get(box.code) if s.return_on_file else None
        d_adj = adjustments.get(box.code) if s.return_on_file else None

        r_base = r_vat = r_count = e_base = e_vat = e_count = None
        if box.evidenced_by == vb.RECORDS:
            r_base, r_vat, r_count, e_base, e_vat, e_count = records_for(box)
        elif box.evidenced_by in (vb.CUSTOMS_IMPORT, vb.CUSTOMS_EXPORT):
            # A declaration states a value in SAR and no tax. So the base is compared and the
            # VAT column is left empty rather than filled with a figure customs never gave —
            # and there is only one customs population, so it evidences the 15% box and the
            # rate-split boxes beneath it are declared without a counterpart.
            cd = (s.customs_import if box.evidenced_by == vb.CUSTOMS_IMPORT
                  else s.customs_export)
            if cd is not None and box.rate in (15, 0, None):
                r_base, r_count = cd.total("taxable"), cd.count

        rows.append({
            "code": box.code, "label": box.label, "label_ar": box.label_ar,
            "rate": box.rate, "category": box.category,
            "evidenced_by": box.evidenced_by, "declared_only": box.declared_only,
            "why_unevidenced": box.why_unevidenced,
            "declared_base": d_base, "declared_vat": d_vat, "declared_adjustment": d_adj,
            "register_base": r_base, "register_vat": r_vat, "register_count": r_count,
            "einvoice_base": e_base, "einvoice_vat": e_vat, "einvoice_count": e_count,
            # Customs states a value and no tax, so those rows are compared on the base or not
            # at all. Left on VAT they read as three empty cells — on the demo case that hid
            # SAR 240,000 of import declarations the return does not carry, which is the whole
            # reason the box is evidenced. The row says which metric its variance is in.
            "variance_metric": "taxable" if box.evidenced_by in (vb.CUSTOMS_IMPORT,
                                                                 vb.CUSTOMS_EXPORT) else "vat",
            "reg_vs_einvoice": diff(r_vat, e_vat),
            "einvoice_vs_declared": diff(e_vat, d_vat),
            "declared_vs_reg": (diff(d_base, r_base)
                                if box.evidenced_by in (vb.CUSTOMS_IMPORT, vb.CUSTOMS_EXPORT)
                                else diff(d_vat, r_vat)),
        })

    # Anything the boxes cannot hold. A record charged at a rate the return has no box for —
    # 16.5%, say — belongs to no line of the form, and without this row it simply disappears
    # from the table: the e-invoice column read SAR 2,499,000 against a dataset holding
    # 2,630,000, and nothing on the screen said where the difference went. A matrix an auditor
    # cannot foot is a matrix they cannot use, so the residue is a visible row with its own
    # explanation rather than a silent loss.
    def unallocated(ds) -> tuple[float | None, float | None, int]:
        if ds is None:
            return None, None, 0
        rows_ = [r for r in ds.records
                 if vb.records_box(direction, r.vat_treatment, r.vat_rate) is None]
        if not rows_:
            return None, None, 0
        base = ([r.taxable_amount for r in rows_ if r.taxable_amount is not None]
                if "taxable" in ds.fields_available else [])
        vat = ([r.vat_amount for r in rows_ if r.vat_amount is not None]
               if "vat" in ds.fields_available else [])
        return (round(sum(base), 2) if base else None,
                round(sum(vat), 2) if vat else None, len(rows_))

    ur_base, ur_vat, ur_count = unallocated(reg)
    ue_base, ue_vat, ue_count = unallocated(ein)
    if ur_count or ue_count:
        rows.append({
            "code": "unallocated", "label": "Records the return has no box for",
            "label_ar": "", "rate": None, "category": "", "evidenced_by": vb.RECORDS,
            "declared_only": False, "unallocated": True,
            "why_unevidenced": "",
            "declared_base": None, "declared_vat": None, "declared_adjustment": None,
            "register_base": ur_base, "register_vat": ur_vat, "register_count": ur_count,
            "einvoice_base": ue_base, "einvoice_vat": ue_vat, "einvoice_count": ue_count,
            "reg_vs_einvoice": diff(ur_vat, ue_vat),
            "einvoice_vs_declared": None, "declared_vs_reg": None,
        })

    def col(key: str, *, records_only: bool = False) -> float | None:
        """A column total. `records_only` keeps customs out of the register column's sum.

        A customs declaration and the taxpayer's own register are two different populations,
        and adding them gives a figure belonging to neither — the sales register totalled
        SAR 17,453,333 and the export declarations SAR 1,380,000, and the column footed to
        18,833,333, which is nothing. The customs rows keep their own figures on the row, and
        the total states only the register.
        """
        picked = [r for r in rows
                  if r[key] is not None
                  and not (records_only and r["evidenced_by"] in (vb.CUSTOMS_IMPORT,
                                                                  vb.CUSTOMS_EXPORT))]
        return round(sum(r[key] for r in picked), 2) if picked else None

    total = {"code": "total", "label": "Total", "label_ar": "الإجمالي",
             "rate": None, "category": "", "evidenced_by": vb.COMPUTED,
             "declared_only": False, "why_unevidenced": "", "variance_metric": "vat"}
    for key in ("declared_base", "declared_vat", "declared_adjustment",
                "einvoice_base", "einvoice_vat"):
        total[key] = col(key)
    for key in ("register_base", "register_vat"):
        total[key] = col(key, records_only=True)
    total["register_count"] = reg.count if reg else None
    total["einvoice_count"] = ein.count if ein else None
    # From the totals, never summed down the column. A box one side cannot state drops out of
    # that sum and the result then disagrees with the pairing above it.
    total["reg_vs_einvoice"] = diff(total["register_vat"], total["einvoice_vat"])
    total["einvoice_vs_declared"] = diff(total["einvoice_vat"], total["declared_vat"])
    total["declared_vs_reg"] = diff(total["declared_vat"], total["register_vat"])

    declared_only = [r for r in rows
                     if r["declared_only"] and (r["declared_base"] or r["declared_vat"])]
    unbox = round((ur_vat or 0.0) + (ue_vat or 0.0), 2)
    return {
        "rows": rows, "total": total,
        "declared_only_count": len(declared_only),
        "declared_only_value": round(sum(abs(r["declared_vat"] or 0.0)
                                         for r in declared_only), 2),
        "unallocated_count": ur_count + ue_count,
        "unallocated_value": unbox,
        "note": ("Rows marked declared-only carry a figure the return states and nothing on the "
                 "case can test. They are shown at their declared value with no variance, "
                 "because comparing them against an absent population would report the whole "
                 "declaration as a difference."
                 if declared_only else ""),
    }

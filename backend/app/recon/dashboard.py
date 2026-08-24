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
                               TREATMENT_LABEL, ZERO_RATED)
from ..evidence import profile as prof
from ..evidence import service as evidence_service
from ..models import AuditCase, VatReturn
from ..pipeline.rules import BOX_PURCHASE, BOX_SALES, BOX_ZERO_RATED_SALES
from . import observations as obs
from . import pairwise as P
from . import status as S
from . import tolerance as T

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
        box = _BOX[(workstream, "vat")]
        s.declared_vat = boxes.get(box) if on_file else None
        s.declared_base = bases.get(box) if on_file else None
        # Zero-rated sales are declared in their own box, so the declared taxable base for the
        # sales workstream is both boxes together — otherwise a register carrying zero-rated
        # lines is compared against a standard-rated-only declaration.
        if workstream == "sales" and on_file and s.declared_base is not None:
            s.declared_base = round(s.declared_base + bases.get(BOX_ZERO_RATED_SALES, 0.0), 2)

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
                },
                "summary": _summary([c for c in comparisons
                                     if c.pairing.workstream == ws],
                                    [e for e in exceptions if e.workstream == ws]),
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

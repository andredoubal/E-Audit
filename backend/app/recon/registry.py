"""Which comparisons exist, and what each one needs before it can run.

Declarative for the same reason `pipeline/rules.py` is declarative: adding a comparison should
be one entry, not an edit to an engine. A definition names its two sides, the metric, the grain
and the tolerance profile, and carries a `requires` predicate evaluated against the case's
evidence profiles.

**Nothing here is a list of what will run.** The planner asks each definition "can you run on
this case?", and the ones that say no publish *why not* and *what would unlock them*. That is
the difference between a system that works on one case and a system that works on a case it has
never seen: the comparisons follow the evidence, and the evidence follows what the taxpayer
actually sent.

The set below covers both workstreams and the pairings the specification names as examples. It
is a starting set, not a closed one — and deliberately so, because the shapes of the datasets an
auditor receives are not knowable in advance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..evidence import profile as P
from ..evidence import roles as R
from ..pipeline.rules import BOX_PURCHASE, BOX_SALES
from . import tolerance as T

SALES = "sales"
PURCHASES = "purchases"

#: What a side of a comparison is drawn from.
DATASET = "dataset"
RETURN_BOX = "return-box"

#: What is being compared. The metric decides which role is read out of each dataset.
VAT = "vat"
NET = "net"
GROSS = "gross"

METRIC_ROLE = {VAT: R.VAT_AMOUNT, NET: R.NET_AMOUNT, GROSS: R.GROSS_AMOUNT}
METRIC_LABEL = {VAT: "VAT", NET: "Net amount", GROSS: "Gross amount"}

#: How the two sides are set against each other.
TOTAL = "total"                 # two figures
TRANSACTION = "transaction"     # row by row, joined on a reference


@dataclass(frozen=True)
class Side:
    kind: str
    label: str
    dataset_type: str = ""
    box: str = ""

    def describe(self) -> str:
        return self.label


@dataclass(frozen=True)
class Definition:
    id: str
    title: str
    workstream: str
    metric: str
    a: Side
    b: Side
    grain: str = TOTAL
    tolerance: str = T.DECLARED.name
    #: What this comparison means, in the auditor's terms. Shown beside the result, because a
    #: figure with no statement of what it tests is a figure nobody can act on.
    note: str = ""
    #: Extra roles both dataset sides must carry beyond the metric's own role.
    needs_roles: tuple[str, ...] = ()
    #: The pairwise comparison (`recon/pairwise.py`) that now owns this question, if any.
    #:
    #: Four of these predate the six pairings and ask exactly what a pairing asks — the same
    #: two sources, the same metric. They are kept because they are declared, tested and read
    #: by the workstream counts, and removing a definition would change what those count. But
    #: they are not shown twice: the dashboard states the pairing, and the panel below it shows
    #: only what the six do not reach — POS takings, the ledger, credit notes, customs. Two
    #: panels reporting one difference in slightly different words is how an auditor comes to
    #: distrust both.
    superseded_by: str = ""

    def sides(self) -> tuple[Side, Side]:
        return self.a, self.b


def _dataset(kind: str, label: str) -> Side:
    return Side(kind=DATASET, label=label, dataset_type=kind)


def _box(box: str, label: str) -> Side:
    return Side(kind=RETURN_BOX, label=label, box=box)


# ------------------------------------------------------------------ the set
DEFINITIONS: tuple[Definition, ...] = (
    # ---------------------------------------------------------------- sales
    Definition(
        id="sales-register-vs-return", title="Sales register against the VAT return",
        workstream=SALES, metric=VAT,
        a=_dataset(P.SALES_REGISTER, "Sales register"),
        b=_box(BOX_SALES, "Output VAT declared"),
        superseded_by="S3",
        note="What the taxpayer's own sales listing totals, against the output VAT they "
             "declared for the period. No qualification rule acts on either side."),
    Definition(
        id="sales-register-vs-einvoices", title="Sales register against ZATCA's e-invoice records",
        workstream=SALES, metric=VAT, grain=TRANSACTION, tolerance=T.DATED.name,
        a=_dataset(P.SALES_REGISTER, "Sales register"),
        b=_dataset(P.EINVOICE_EXTRACT, "E-invoice extract"),
        needs_roles=(R.REFERENCE,),
        superseded_by="S1",
        note="Invoice by invoice, against the Authority's own record of the same period. "
             "Answers which documents each side holds that the other does not."),
    Definition(
        id="pos-vs-sales-register", title="Point-of-sale takings against the sales register",
        workstream=SALES, metric=GROSS,
        a=_dataset(P.POS_REPORT, "Point-of-sale report"),
        b=_dataset(P.SALES_REGISTER, "Sales register"),
        note="Independent evidence of takings against what was recorded as sales. A difference "
             "either way is a question about completeness of the register."),
    Definition(
        id="sales-register-vs-ledger", title="Sales register against the general ledger",
        workstream=SALES, metric=VAT, tolerance=T.PER_ROW.name,
        a=_dataset(P.SALES_REGISTER, "Sales register"),
        b=_dataset(P.GENERAL_LEDGER, "General ledger"),
        note="Whether the sales listing agrees with what was posted to the accounts. One "
             "invoice may span several ledger lines, so this is an aggregate comparison."),
    Definition(
        id="credit-notes-vs-sales-register", title="Credit notes against the sales register",
        workstream=SALES, metric=VAT,
        a=_dataset(P.CREDIT_NOTE_LISTING, "Credit and debit note listing"),
        b=_dataset(P.SALES_REGISTER, "Sales register"),
        note="Whether the notes issued are reflected in the register they adjust. Establishes "
             "the size of the adjustment, not whether it was due."),

    # ---------------------------------------------------------------- purchases
    Definition(
        id="purchase-register-vs-return", title="Purchases register against the VAT return",
        workstream=PURCHASES, metric=VAT,
        a=_dataset(P.PURCHASE_REGISTER, "Purchases register"),
        b=_box(BOX_PURCHASE, "Input VAT claimed"),
        superseded_by="P3",
        note="What the purchases listing supports, against the input VAT claimed. This "
             "compares amounts only — whether that input tax is deductible is a separate "
             "question the numbers cannot answer."),
    Definition(
        id="purchase-register-vs-einvoices",
        title="Purchases register against ZATCA's e-invoice records",
        workstream=PURCHASES, metric=VAT, grain=TRANSACTION, tolerance=T.DATED.name,
        a=_dataset(P.PURCHASE_REGISTER, "Purchases register"),
        b=_dataset(P.EINVOICE_EXTRACT, "E-invoice extract"),
        needs_roles=(R.REFERENCE,),
        superseded_by="P1",
        note="Supplier invoice by supplier invoice, against the Authority's record of the "
             "same documents."),
    Definition(
        id="purchase-register-vs-ledger", title="Purchases register against the general ledger",
        workstream=PURCHASES, metric=VAT, tolerance=T.PER_ROW.name,
        a=_dataset(P.PURCHASE_REGISTER, "Purchases register"),
        b=_dataset(P.GENERAL_LEDGER, "General ledger"),
        note="Whether the purchases listing agrees with what was posted to the accounts."),
    Definition(
        id="customs-vs-purchase-register", title="Customs records against the purchases register",
        workstream=PURCHASES, metric=VAT, tolerance=T.DATED.name,
        a=_dataset(P.CUSTOMS_RECORDS, "Customs records"),
        b=_dataset(P.PURCHASE_REGISTER, "Purchases register"),
        note="Import VAT evidenced by customs records against what the register carries. "
             "Timing differs between the two systems by design, so this is dated."),
)

BY_ID: dict[str, Definition] = {d.id: d for d in DEFINITIONS}


def for_workstream(workstream: str) -> tuple[Definition, ...]:
    return tuple(d for d in DEFINITIONS if d.workstream == workstream)

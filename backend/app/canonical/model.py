"""The canonical transaction record, and the four states a value can be in.

The four states matter more than the field list. A reconciliation that cannot tell them apart
produces confident nonsense:

    VALUE          the source carried it and it was read
    UNAVAILABLE    the source has no such column at all
    UNREADABLE     the column is there and this row's value could not be parsed
    NOT_APPLICABLE the field does not arise for this kind of record

`None` covers the last three, and `missing` says which. Nothing is ever defaulted to zero to
make a sum work — a blank VAT cell counted as nought quietly shrinks a total, and a taxpayer who
did not send a column has not declared nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

# ---------------------------------------------------------------- availability
VALUE = "value"
UNAVAILABLE = "unavailable"          # the dataset has no such column
UNREADABLE = "unreadable"            # the column exists; this row could not be parsed
NOT_APPLICABLE = "not-applicable"    # the field does not arise for this record

AVAILABILITY_LABEL: dict[str, str] = {
    VALUE: "read from the source",
    UNAVAILABLE: "not supplied",
    UNREADABLE: "could not be read",
    NOT_APPLICABLE: "does not arise",
}

# ---------------------------------------------------------------- vocabularies
SALE = "sale"
PURCHASE = "purchase"

INVOICE = "invoice"
CREDIT_NOTE = "credit-note"
DEBIT_NOTE = "debit-note"

STANDARD = "standard-rated"
ZERO_RATED = "zero-rated"
EXEMPT = "exempt"
OUT_OF_SCOPE = "out-of-scope"
UNCLASSIFIED = "unclassified"

TREATMENTS = (STANDARD, ZERO_RATED, EXEMPT, OUT_OF_SCOPE, UNCLASSIFIED)

TREATMENT_LABEL: dict[str, str] = {
    STANDARD: "Standard-rated",
    ZERO_RATED: "Zero-rated",
    EXEMPT: "Exempt",
    OUT_OF_SCOPE: "Out of scope",
    UNCLASSIFIED: "Unclassified",
}


@dataclass
class Record:
    """One transaction, however the file that carried it chose to spell things.

    Optional everywhere on purpose. A record from a bank statement carries no VAT rate and a
    record from a trial balance carries no invoice number, and both are legitimate rows.
    """

    # --- lineage. Not optional: a record that cannot be traced back is not evidence.
    source_dataset: str                       # sales-register, einvoice-extract, ...
    source_file: str
    source_row: int
    record_id: str                            # stable within a case: file#row

    # --- identity
    invoice_id: str | None = None             # the document number as written
    invoice_key: str | None = None            # normalised for matching; never displayed
    uuid: str | None = None
    transaction_id: str | None = None

    # --- when
    transaction_date: date | None = None
    tax_period: str | None = None             # YYYY-MM, derived where a date exists

    # --- who
    seller_tax_id: str | None = None
    buyer_tax_id: str | None = None
    counterparty_name: str | None = None

    # --- how much
    taxable_amount: float | None = None
    vat_rate: float | None = None
    vat_amount: float | None = None
    gross_amount: float | None = None
    currency: str | None = None

    # --- what kind
    direction: str | None = None              # sale | purchase
    transaction_type: str = INVOICE
    vat_treatment: str = UNCLASSIFIED
    treatment_basis: str = ""                 # how the treatment was decided, in words

    # --- what could not be read
    missing: dict[str, str] = field(default_factory=dict)   # field -> availability
    notes: list[str] = field(default_factory=list)

    def availability(self, name: str) -> str:
        if name in self.missing:
            return self.missing[name]
        return VALUE if getattr(self, name, None) is not None else UNAVAILABLE

    def amount(self, metric: str) -> float | None:
        """The metric this record contributes, or None if it cannot contribute one."""
        return {"vat": self.vat_amount, "taxable": self.taxable_amount,
                "gross": self.gross_amount}.get(metric)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id, "source_dataset": self.source_dataset,
            "source_file": self.source_file, "source_row": self.source_row,
            "invoice_id": self.invoice_id, "uuid": self.uuid,
            "transaction_id": self.transaction_id,
            "transaction_date": self.transaction_date.isoformat()
            if self.transaction_date else None,
            "tax_period": self.tax_period,
            "seller_tax_id": self.seller_tax_id, "buyer_tax_id": self.buyer_tax_id,
            "counterparty_name": self.counterparty_name,
            "taxable_amount": self.taxable_amount, "vat_rate": self.vat_rate,
            "vat_amount": self.vat_amount, "gross_amount": self.gross_amount,
            "currency": self.currency, "direction": self.direction,
            "transaction_type": self.transaction_type,
            "vat_treatment": self.vat_treatment,
            "treatment_label": TREATMENT_LABEL[self.vat_treatment],
            "treatment_basis": self.treatment_basis,
            "missing": self.missing, "notes": self.notes,
        }


@dataclass
class Dataset:
    """A whole file, canonicalised, with what it could and could not supply.

    `fields_available` is the honest answer to "can this analysis be done" — a comparison that
    needs a VAT rate on a file that has none must say so rather than produce a figure from
    nothing, and this is where it reads that.
    """

    source_dataset: str
    source_file: str
    direction: str | None
    records: list[Record] = field(default_factory=list)
    fields_available: set[str] = field(default_factory=set)
    unreadable_rows: dict[str, list[int]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.records)

    def total(self, metric: str) -> float | None:
        """The sum of a metric, or None where the field is not available at all.

        Returning None rather than 0.0 is the whole point: a dataset with no VAT column has not
        got VAT of zero, and a comparison against it is not a variance the size of the other
        side.
        """
        if metric not in self.fields_available:
            return None
        return round(sum(r.amount(metric) or 0.0 for r in self.records), 2)

    def counted(self, metric: str) -> int:
        """How many records actually contributed — never the same as `count` when cells are
        unreadable, and an auditor comparing by hand needs to know which number they are
        looking at."""
        return sum(1 for r in self.records if r.amount(metric) is not None)

    def by_treatment(self, metric: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for t in TREATMENTS:
            rows = [r for r in self.records if r.vat_treatment == t]
            if not rows:
                continue
            contributing = [r for r in rows if r.amount(metric) is not None]
            out[t] = {
                "treatment": t, "label": TREATMENT_LABEL[t],
                "count": len(rows),
                "counted": len(contributing),
                "total": (round(sum(r.amount(metric) or 0.0 for r in contributing), 2)
                          if metric in self.fields_available else None),
            }
        return out

    def to_dict(self) -> dict:
        return {
            "source_dataset": self.source_dataset, "source_file": self.source_file,
            "direction": self.direction, "count": self.count,
            "fields_available": sorted(self.fields_available),
            "unreadable_rows": {k: v[:25] for k, v in self.unreadable_rows.items()},
            "unreadable_counts": {k: len(v) for k, v in self.unreadable_rows.items()},
            "notes": self.notes,
        }

"""Turning a profiled spreadsheet into canonical records, with lineage on every one.

The mapping layer the specification asks for. It does not know any Excel column names: it reads
the **roles** the profiler already detected, so a file whose VAT column is called `Tax Amt`,
`ضريبة` or `Column J` maps identically as long as the profiler recognised the role — and where
it did not, the record says the field was unavailable rather than inventing it.

Three rules run through this file.

**Never default to zero.** A missing column is `UNAVAILABLE`; an unparseable cell is
`UNREADABLE`. Both leave the field `None` and both are counted. A total over a field the
dataset does not carry is `None`, not `0.00`, all the way up to the dashboard.

**Signs are read, not assumed.** Whether the file states a credit note negatively is a property
of the file. The convention is read once per column and recorded, and a wholly inverted column
is taken at its magnitude with that fact carried on the dataset — so an auditor summing the
column by hand gets the same answer for a stated reason.

**Every record can be walked back.** `source_file` and `source_row` are not optional and are not
derived later; they are set here, at the only point where the raw row is still in hand.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..agents.calculation import as_date, as_number
from ..evidence import roles as R
from . import treatment as T
from .model import (CREDIT_NOTE, DEBIT_NOTE, Dataset, INVOICE, PURCHASE, Record, SALE,
                    UNAVAILABLE, UNREADABLE)

#: Which canonical field each role feeds. Roles the profiler does not detect simply never
#: appear, which is how a new column shape becomes supported: teach the profiler the role.
_FROM_ROLE: dict[str, str] = {
    R.REFERENCE: "invoice_id",
    R.ISSUE_DATE: "transaction_date",
    R.COUNTERPARTY_NAME: "counterparty_name",
    R.NET_AMOUNT: "taxable_amount",
    R.VAT_AMOUNT: "vat_amount",
    R.GROSS_AMOUNT: "gross_amount",
    R.VAT_RATE: "vat_rate",
    R.CURRENCY: "currency",
}

_MONEY = ("taxable_amount", "vat_amount", "gross_amount")
_NOTE_HINTS = ("cn-", "cr-", "cn/", "credit")
_DEBIT_HINTS = ("dn-", "dr-", "dn/", "debit")


def _cell(row: list[Any], i: int) -> Any:
    return row[i] if 0 <= i < len(row) else None


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def normalise_key(reference: Any) -> str:
    """The form two datasets are matched on. Never displayed.

    `INV-001`, `inv 001` and `INV/001` are one invoice, so formatting is not a mismatch — but
    the auditor has to find the row in their own spreadsheet, and `INV001` is not a string that
    occurs in it. So the written form travels on `invoice_id` and this is only ever a join key.
    """
    return "".join(ch for ch in str(reference or "").upper() if ch.isalnum())


def _column_conventions(columns: list[str], rows: list[list[Any]],
                        index: dict[str, int]) -> dict[str, float]:
    """Per money column: +1 to take values as written, -1 where the whole column is inverted.

    Read once for the column rather than per row, because a convention is a property of the
    file. A column with both signs is left alone: there the signs are information — invoices
    positive, credit notes negative — and flipping them would add the notes to the total
    instead of netting them.
    """
    out: dict[str, float] = {}
    for field_name, i in index.items():
        if field_name not in _MONEY:
            continue
        values = [as_number(_cell(r, i)) for r in rows]
        values = [v for v in values if v is not None]
        if values and all(v <= 0 for v in values) and any(v < 0 for v in values):
            out[field_name] = -1.0
        else:
            out[field_name] = 1.0
    return out


def _transaction_type(reference: Any, taxable: float | None, stated: Any) -> str:
    text = str(stated or "").strip().lower()
    if "credit" in text or text in ("cn", "cr"):
        return CREDIT_NOTE
    if "debit" in text or text in ("dn", "dr"):
        return DEBIT_NOTE
    ref = str(reference or "").strip().lower()
    if any(ref.startswith(h) for h in _NOTE_HINTS):
        return CREDIT_NOTE
    if any(ref.startswith(h) for h in _DEBIT_HINTS):
        return DEBIT_NOTE
    # A negative amount, with nothing else to go on, reads as a reduction. Recorded as the weak
    # signal it is — the note on the dataset says so — rather than presented as the file's word.
    if taxable is not None and taxable < 0:
        return CREDIT_NOTE
    return INVOICE


def build(profile: dict, rows: list[list[Any]], *, direction: str | None = None) -> Dataset:
    """Canonicalise one profiled dataset."""
    columns = list(profile.get("columns") or [])
    by_role = {r["role"]: r["column"] for r in profile.get("roles") or []}
    source_file = profile.get("filename") or ""
    source_dataset = profile.get("dataset_type") or "unknown"

    # Which canonical field each column index feeds.
    index: dict[str, int] = {}
    for role, field_name in _FROM_ROLE.items():
        column = by_role.get(role)
        if column and column in columns:
            index[field_name] = columns.index(column)

    # Identity columns the role vocabulary carries a side for.
    tax_id_role = next((r for r in profile.get("roles") or []
                        if r["role"] == R.COUNTERPARTY_TAX_ID), None)
    treat_role = next((r for r in profile.get("roles") or []
                       if r["role"] == R.VAT_TREATMENT), None)
    type_role = next((r for r in profile.get("roles") or []
                      if r["role"] == R.DOCUMENT_TYPE), None)
    i_tax_id = columns.index(tax_id_role["column"]) if tax_id_role else -1
    i_treat = columns.index(treat_role["column"]) if treat_role else -1
    i_type = columns.index(type_role["column"]) if type_role else -1

    # Which side of a transaction this dataset describes. The profiler decides it from the
    # counterparty columns; an explicit direction (from the dataset type) overrides.
    side = direction
    if side is None:
        ws = profile.get("workstream")
        side = SALE if ws == "sales" else PURCHASE if ws == "purchases" else None

    signs = _column_conventions(columns, rows, index)
    inverted = [f for f, s in signs.items() if s < 0]

    ds = Dataset(source_dataset=source_dataset, source_file=source_file, direction=side)
    ds.fields_available = set(index) | (
        {"counterparty_tax_id"} if i_tax_id >= 0 else set())
    if inverted:
        ds.notes.append(
            "Stated against the economic sign in " + ", ".join(inverted)
            + " — every value in the column is negative, so magnitudes are compared and the "
              "convention is recorded rather than dropped.")

    for n, row in enumerate(rows, start=1):
        if all(_blank(v) for v in row):
            ds.unreadable_rows.setdefault("blank-row", []).append(n)
            continue

        rec = Record(source_dataset=source_dataset, source_file=source_file, source_row=n,
                     record_id=f"{source_file}#{n}", direction=side)

        for field_name, i in index.items():
            raw = _cell(row, i)
            if _blank(raw):
                rec.missing[field_name] = UNAVAILABLE
                continue
            if field_name == "transaction_date":
                parsed = as_date(raw)
                if parsed is None:
                    rec.missing[field_name] = UNREADABLE
                    ds.unreadable_rows.setdefault(field_name, []).append(n)
                else:
                    rec.transaction_date = parsed
                    rec.tax_period = f"{parsed.year:04d}-{parsed.month:02d}"
                continue
            if field_name in _MONEY or field_name == "vat_rate":
                parsed = as_number(raw)
                if parsed is None:
                    rec.missing[field_name] = UNREADABLE
                    ds.unreadable_rows.setdefault(field_name, []).append(n)
                else:
                    setattr(rec, field_name,
                            round(parsed * signs.get(field_name, 1.0), 2)
                            if field_name in _MONEY else parsed)
                continue
            setattr(rec, field_name, str(raw).strip())

        for field_name in _FROM_ROLE.values():
            if field_name not in index:
                rec.missing.setdefault(field_name, UNAVAILABLE)

        if rec.invoice_id:
            rec.invoice_key = normalise_key(rec.invoice_id)
        if i_tax_id >= 0 and not _blank(_cell(row, i_tax_id)):
            value = str(_cell(row, i_tax_id)).strip()
            # Which side the identifier belongs to follows the counterparty the file names.
            if side == SALE:
                rec.buyer_tax_id = value
            elif side == PURCHASE:
                rec.seller_tax_id = value

        rec.transaction_type = _transaction_type(
            rec.invoice_id, rec.taxable_amount, _cell(row, i_type) if i_type >= 0 else None)
        rec.vat_treatment, rec.treatment_basis = T.classify(
            stated=_cell(row, i_treat) if i_treat >= 0 else None,
            vat_rate=rec.vat_rate, taxable_amount=rec.taxable_amount,
            vat_amount=rec.vat_amount)

        ds.records.append(rec)

    # A field is only "available" on the dataset if at least one record actually carried it.
    # A column of blanks is a column that supplies nothing, and a total over it would be a
    # figure derived from an empty set presented as a fact.
    for field_name in list(ds.fields_available):
        canonical = {"counterparty_tax_id": "buyer_tax_id"}.get(field_name, field_name)
        if not any(getattr(r, canonical, None) is not None for r in ds.records):
            ds.fields_available.discard(field_name)
            ds.notes.append(f"'{field_name.replace('_', ' ')}' is present as a column but "
                            f"carries no readable value on any row.")

    ds.fields_available = {
        {"taxable_amount": "taxable", "vat_amount": "vat", "gross_amount": "gross"}.get(f, f)
        for f in ds.fields_available
    }
    return ds

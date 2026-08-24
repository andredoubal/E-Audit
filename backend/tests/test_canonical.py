"""The canonical layer: one shape, lineage on every record, and absent never meaning zero.

Everything downstream — six comparisons, three levels, exceptions, findings, the audit report —
is built from these records, so the properties tested here are the ones the whole redesign
rests on.

Synthetic fixtures throughout. None is the demo case.
"""
from __future__ import annotations

from datetime import date

from app.canonical import build as canon
from app.canonical import treatment as T
from app.canonical.model import (CREDIT_NOTE, EXEMPT, INVOICE, PURCHASE, SALE, STANDARD,
                                 UNAVAILABLE, UNCLASSIFIED, UNREADABLE, ZERO_RATED)
from app.evidence import profile as prof

SALES_COLS = ["invoice_date", "invoice_number", "customer_name", "customer_vat_number",
              "taxable_amount", "vat_rate", "vat_amount"]


def dataset(filename: str, columns: list[str], rows: list[list], **kw):
    p = prof.build({"filename": filename,
                    "content": {"format": "csv", "columns": columns, "rows": rows}}).to_dict()
    return canon.build(p, rows, **kw)


# ------------------------------------------------------------------ lineage
def test_every_record_can_be_walked_back_to_its_source_row():
    """A record that cannot be traced back is not evidence, so lineage is not optional."""
    ds = dataset("register.csv", SALES_COLS,
                 [["2025-01-14", "INV-1", "Buyer A", "300", 100000, 15, 15000],
                  ["2025-02-03", "INV-2", "Buyer B", "300", 200000, 15, 30000]])
    assert [r.source_row for r in ds.records] == [1, 2]
    assert all(r.source_file == "register.csv" for r in ds.records)
    assert [r.record_id for r in ds.records] == ["register.csv#1", "register.csv#2"]
    assert all(r.source_dataset == "sales-register" for r in ds.records)


def test_the_written_reference_survives_while_matching_uses_a_normalised_key():
    """`INV-001` and `inv 001` are one invoice, so formatting is not a mismatch — but the
    auditor has to find the row in their own spreadsheet, and `INV001` is not in it."""
    ds = dataset("r.csv", SALES_COLS,
                 [["2025-01-14", "INV-001", "Buyer A", "300", 100, 15, 15],
                  ["2025-01-15", "inv 001", "Buyer A", "300", 100, 15, 15]])
    assert [r.invoice_id for r in ds.records] == ["INV-001", "inv 001"]
    assert ds.records[0].invoice_key == ds.records[1].invoice_key == "INV001"


# ------------------------------------------------------------------ absent is never zero
def test_a_column_the_file_does_not_carry_is_unavailable_not_zero():
    """The distinction the whole reconciliation layer is written to keep: a taxpayer who did
    not send a column has not declared nothing."""
    ds = dataset("r.csv", ["invoice_date", "invoice_number", "customer_name", "vat_amount"],
                 [["2025-01-14", "INV-1", "Buyer A", 15000]])

    assert ds.total("vat") == 15000.0
    assert ds.total("taxable") is None, "no taxable column — not a taxable amount of zero"
    assert ds.total("gross") is None
    assert "taxable" not in ds.fields_available
    assert ds.records[0].availability("taxable_amount") == UNAVAILABLE


def test_a_cell_that_cannot_be_parsed_is_unreadable_and_counted():
    ds = dataset("r.csv", SALES_COLS,
                 [["2025-01-14", "INV-1", "Buyer A", "300", 100000, 15, 15000],
                  ["2025-02-03", "INV-2", "Buyer B", "300", 200000, 15, "n/a"]])
    assert ds.total("vat") == 15000.0, "the unreadable row contributes nothing, not zero"
    assert ds.count == 2
    assert ds.counted("vat") == 1, "and the difference is visible"
    assert ds.unreadable_rows["vat_amount"] == [2]
    assert ds.records[1].availability("vat_amount") == UNREADABLE


def test_a_column_of_blanks_is_not_an_available_field():
    """A total over a column nobody filled in is a figure derived from an empty set."""
    ds = dataset("r.csv", SALES_COLS,
                 [["2025-01-14", "INV-1", "Buyer A", "300", 100000, 15, None],
                  ["2025-02-03", "INV-2", "Buyer B", "300", 200000, 15, None]])
    assert "vat" not in ds.fields_available
    assert ds.total("vat") is None
    assert any("carries no readable value" in n for n in ds.notes)


# ------------------------------------------------------------------ signs
def test_a_wholly_negative_column_is_read_at_its_magnitude_and_the_convention_recorded():
    ds = dataset("p.csv",
                 ["invoice_date", "invoice_number", "supplier_name", "taxable_amount",
                  "vat_amount"],
                 [["2025-01-09", "PI-1", "Vendor A", -40000, -6000],
                  ["2025-02-22", "PI-2", "Vendor B", -12000, -1800]])
    assert ds.total("vat") == 7800.0
    assert any("against the economic sign" in n for n in ds.notes)


def test_a_mixed_sign_column_is_left_alone_because_the_signs_are_information():
    """Invoices positive and credit notes negative is the file telling you something. Taking
    magnitudes there would add the notes to the total instead of netting them."""
    ds = dataset("r.csv", SALES_COLS,
                 [["2025-01-14", "INV-1", "Buyer A", "300", 100000, 15, 15000],
                  ["2025-02-03", "CN-1", "Buyer A", "300", -20000, 15, -3000]])
    assert ds.total("vat") == 12000.0
    assert not any("against the economic sign" in n for n in ds.notes)
    assert ds.records[1].transaction_type == CREDIT_NOTE


# ------------------------------------------------------------------ VAT treatment
def test_an_explicit_treatment_column_wins_over_anything_derived():
    treatment, why = T.classify(stated="Zero rated", vat_rate=15.0)
    assert treatment == ZERO_RATED
    assert "the file states" in why


def test_the_standard_rate_and_a_zero_rate_are_read_from_the_rate_column():
    assert T.classify(vat_rate=15.0, taxable_amount=100.0)[0] == STANDARD
    assert T.classify(vat_rate=0.0, taxable_amount=100.0)[0] == ZERO_RATED


def test_a_rate_that_is_neither_is_left_uncategorised_rather_than_folded_into_standard():
    """Folding a 7%-rated line into standard would put it in a box it was never shown to
    belong to, and a breakdown is read to decide where a difference is."""
    treatment, why = T.classify(vat_rate=7.0, taxable_amount=100.0)
    assert treatment == UNCLASSIFIED
    assert "neither a standard rate nor zero" in why


def test_the_pre_2020_five_percent_rate_is_standard_rated_and_not_an_anomaly():
    """KSA charged 5% until July 2020 and the VAT return still declares it in its own box, so a
    5% line is a standard-rated supply at the rate then in force. Reading it as unclassified
    put real standard-rated money in the bucket the auditor is told nothing can be concluded
    about."""
    treatment, why = T.classify(vat_rate=5.0, taxable_amount=100.0)
    assert treatment == STANDARD
    assert "before July 2020" in why
    assert T.classify(taxable_amount=100_000.0, vat_amount=5_000.0)[0] == STANDARD


def test_a_treatment_is_derived_from_the_two_amounts_only_when_it_is_decisive():
    assert T.classify(taxable_amount=100000.0, vat_amount=15000.0)[0] == STANDARD
    assert T.classify(taxable_amount=100000.0, vat_amount=0.0)[0] == ZERO_RATED
    assert T.classify(taxable_amount=100000.0, vat_amount=7000.0)[0] == UNCLASSIFIED


def test_nothing_at_all_to_go_on_is_unclassified_and_says_so():
    treatment, why = T.classify()
    assert treatment == UNCLASSIFIED
    assert "nothing that decides" in why


def test_unclassified_is_a_real_row_in_the_breakdown_rather_than_a_bucket_that_disappears():
    ds = dataset("r.csv", SALES_COLS,
                 [["2025-01-14", "INV-1", "Buyer A", "300", 100000, 15, 15000],
                  ["2025-02-03", "INV-2", "Buyer B", "300", 100000, 7, 7000]])
    breakdown = ds.by_treatment("vat")
    assert breakdown[STANDARD]["total"] == 15000.0
    assert breakdown[UNCLASSIFIED]["total"] == 7000.0
    assert sum(b["total"] for b in breakdown.values()) == ds.total("vat")


# ------------------------------------------------------------------ record kinds
def test_a_credit_note_is_recognised_from_the_document_type_column():
    ds = dataset("n.csv",
                 ["note_date", "note_number", "note_type", "customer_name", "vat_amount"],
                 [["2025-02-10", "X-1", "Credit note", "Buyer A", -1500]])
    assert ds.records[0].transaction_type == CREDIT_NOTE


def test_direction_follows_the_counterparty_the_file_names():
    sales = dataset("s.csv", SALES_COLS,
                    [["2025-01-14", "INV-1", "Buyer A", "300", 100, 15, 15]])
    purchases = dataset("p.csv",
                        ["invoice_date", "invoice_number", "supplier_name", "taxable_amount",
                         "vat_amount"],
                        [["2025-01-09", "PI-1", "Vendor A", 100, 15]])
    assert sales.direction == SALE
    assert sales.records[0].buyer_tax_id == "300", "the taxpayer is the seller on their sales"
    assert purchases.direction == PURCHASE


def test_a_tax_period_is_derived_wherever_a_date_could_be_read():
    ds = dataset("r.csv", SALES_COLS,
                 [["2025-01-14", "INV-1", "Buyer A", "300", 100, 15, 15],
                  ["", "INV-2", "Buyer B", "300", 100, 15, 15]])
    assert ds.records[0].tax_period == "2025-01"
    assert ds.records[0].transaction_date == date(2025, 1, 14)
    assert ds.records[1].tax_period is None, "no date, no period — never guessed"


# ------------------------------------------------------------------ real-world headers
#: The column names the Authority's own sales and purchase register templates carry.
_SALES_REGISTER = ["invoice_number", "invoice_date", "customer_tax_id", "customer_name",
                   "description", "amount_excl_vat", "vat_charged", "total_incl_vat"]
_PURCHASE_REGISTER = ["invoice_number", "invoice_date", "supplier_tax_id", "supplier_name",
                      "description", "amount_excl_vat", "vat_charged", "total_incl_vat"]


def test_the_authority_s_own_register_headers_are_read_correctly():
    """The regression this exists for: every amount column read as VAT.

    `_BY_FRAGMENT` is first-match-wins, and both `amount_excl_vat` and `total_incl_vat` contain
    "vat" — so the taxable base and the gross were each matched as the VAT amount and the three
    columns were summed together. On these two rows that reported SAR 345,000 of output VAT
    against a truth of 45,000, with no taxable base at all: an eightfold overstatement that
    nothing downstream could detect, because by then the reading had been made.
    """
    rows = [["INV-1", "2025-01-14", "300000000000004", "Buyer A", "Consulting",
             100_000, 15_000, 115_000],
            ["INV-2", "2025-02-03", "300000000000004", "Buyer B", "Goods",
             200_000, 30_000, 230_000]]
    ds = dataset("sales_register.xlsx", _SALES_REGISTER, rows)

    assert ds.total("vat") == 45_000.0
    assert ds.total("taxable") == 300_000.0
    assert ds.total("gross") == 345_000.0
    assert ds.direction == SALE
    assert ds.records[0].counterparty_name == "Buyer A"
    assert ds.records[0].buyer_tax_id == "300000000000004", \
        "a tax id column is an identifier, not the counterparty's name"


def test_the_purchase_register_template_reads_as_purchases():
    rows = [["PI-1", "2025-01-09", "300000000000009", "Vendor A", "Stationery",
             40_000, 6_000, 46_000]]
    ds = dataset("purchase_register.xlsx", _PURCHASE_REGISTER, rows)
    assert ds.direction == PURCHASE
    assert ds.total("vat") == 6_000.0
    assert ds.total("taxable") == 40_000.0


def test_a_header_naming_vat_only_as_the_tax_itself_still_reads_as_vat():
    """The fix must not overshoot: "total vat" carries neither excl/incl nor a bare net or
    gross, so it is still the tax and not a gross amount."""
    ds = dataset("r.xlsx",
                 ["invoice_number", "invoice_date", "customer_name", "taxable_amount",
                  "total_vat"],
                 [["INV-1", "2025-01-14", "Buyer A", 100_000, 15_000]])
    assert ds.total("vat") == 15_000.0
    assert ds.total("taxable") == 100_000.0


# ------------------------------------------------------------------ two-row headers
def test_a_merged_two_row_header_keeps_every_column():
    """The trial balance the Authority issues, and the reason this exists.

    Its header is two rows — a group label spanning a merged pair of columns, and the pair's own
    labels beneath it. Read as one row, a merged group contributes its label to the first of its
    two columns and nothing to the second, so every `دائن` column was dropped from the file: the
    credit side of every account silently went missing, and the sub-header arrived as data.
    """
    from app.requests import extract as ex

    grid = [
        ["ميزان المراجعة", None, None, None, None, None, None, None],
        ["الرقم", "الاسم", "الرصيد الافتتاحي", None, "الحركة", None, "الرصيد النهائي", None],
        [None, None, "مدين", "دائن", "مدين", "دائن", "مدين", "دائن"],
        ["1010", "النقد", 1_450_000, 0, 3_200_000, 2_980_000, 1_670_000, 0],
    ]
    out = ex._from_grid(grid)

    assert len(out["columns"]) == 8, "every column survives, credit side included"
    assert out["columns"][2] != out["columns"][3], "the two sides of a group stay distinct"
    assert out["columns"][3] != out["columns"][5], "and so do the same side of two groups"
    assert len(out["rows"]) == 1, "the sub-header is a header, not a row of data"
    assert out["rows"][0][0] == "1010"


def test_a_first_data_row_is_not_mistaken_for_a_second_header():
    """The guard the other way. A row of values under a single-row header is data."""
    from app.requests import extract as ex

    grid = [
        ["invoice_number", "invoice_date", "amount_excl_vat", "vat_charged"],
        ["INV-1", "2025-01-14", 100_000, 15_000],
        ["INV-2", "2025-02-03", 200_000, 30_000],
    ]
    out = ex._from_grid(grid)
    assert len(out["columns"]) == 4
    assert len(out["rows"]) == 2, "both data rows survive"


def test_a_customs_declaration_takes_its_period_from_the_gregorian_date_not_the_hijri():
    """An export declaration carries both calendars side by side, and two cue orderings in
    `roles.py` are load-bearing because of it.

    Read Hijri-first-come-first-served and the file reports covering "1446-01-15 → 1446-03-19".
    Let the customs-declaration cue see the Gregorian column before the date cue does — it
    contains البيان — and the file ends up with no date at all, which silently removes it from
    every period check downstream.
    """
    from app.evidence import profile as prof

    cols = ["اسم_المستورد_المصدر", "رقم_البيان", "التاريخ_هجري", "تاريخ_البيان_ميلادي",
            "القيمة_بالريال"]
    rows = [["Acme", f"EXP-{n}", f"1446-0{n}-15", f"2025-0{n}-1{n}", 100_000 * n]
            for n in (1, 2, 3)]
    p = prof.build({"filename": "customs_exports.xlsx",
                    "content": {"format": "xlsx", "columns": cols, "rows": rows}}).to_dict()

    assert p["dataset_type"] == "customs-records"
    assert p["date_min"] == "2025-01-11" and p["date_max"] == "2025-03-13"
    roles = {r["column"]: r["role"] for r in p["roles"]}
    assert roles["التاريخ_هجري"] == "hijri_date", "recognised, and used for nothing"
    assert roles["تاريخ_البيان_ميلادي"] == "issue_date"
    assert roles["رقم_البيان"] == "customs_declaration"

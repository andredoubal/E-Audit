"""Stage 0 — reading each file for what it is, not for what it is called.

Every fixture here is synthetic and none of them is the demo case. That is the point of the
rebuild: the engine has to work on evidence it has never seen, named anything at all, and the
fastest way to prove it does not is to test it against the one file it was written beside.

The tests that matter most are the ones about restraint. A classifier that guesses confidently
is worse than the filename matching it replaces, because a filename at least behaves
predictably — so ambiguity has to come back as ambiguity, and a header whose values contradict
it has to come back with its confidence lowered rather than accepted.
"""
from __future__ import annotations

from app.evidence import profile as prof
from app.evidence import roles as R


def doc(filename: str, columns: list[str], rows: list[list], **content) -> dict:
    return {"filename": filename,
            "content": {"format": "csv", "columns": columns, "rows": rows, **content}}


SALES = (
    ["invoice_date", "invoice_number", "customer_name", "taxable_amount", "vat_amount"],
    [["2025-01-14", "INV-1", "Buyer A", 100000.00, 15000.00],
     ["2025-02-03", "INV-2", "Buyer B", 200000.00, 30000.00],
     ["2025-03-19", "INV-3", "Buyer C", 60000.00, 9000.00]],
)
PURCHASES = (
    ["invoice_date", "invoice_number", "supplier_name", "taxable_amount", "vat_amount"],
    [["2025-01-09", "PI-1", "Vendor A", 40000.00, 6000.00],
     ["2025-02-22", "PI-2", "Vendor B", 12000.00, 1800.00]],
)


# ------------------------------------------------------------------ classification
def test_a_sales_register_is_recognised_from_its_columns_not_its_name():
    """The defect this whole stage exists to remove."""
    p = prof.build(doc("Q1_data_final_v3.xlsx", *SALES))
    assert p.dataset_type == prof.SALES_REGISTER
    assert p.workstream == "sales"
    assert p.confidence == "high"
    assert "customer" in p.why, p.why


def test_a_purchase_register_named_like_a_sales_file_is_still_purchases():
    """The filename must never override what the columns say — this is the expensive way to
    be wrong, because the rows land in the output box and inflate the expected return."""
    p = prof.build(doc("sales_summary_2025.csv", *PURCHASES))
    assert p.dataset_type == prof.PURCHASE_REGISTER
    assert p.workstream == "purchases"
    assert "supplier" in p.why


def test_a_trial_balance_is_not_read_as_a_transaction_listing():
    p = prof.build(doc("extract.csv",
                       ["account_code", "account_name", "debit", "credit", "balance"],
                       [["4000", "Revenue", 0, 2500000, -2500000],
                        ["1100", "Receivables", 300000, 0, 300000]]))
    assert p.dataset_type == prof.TRIAL_BALANCE
    assert p.workstream == "both"


def test_a_general_ledger_is_distinguished_from_a_trial_balance():
    p = prof.build(doc("export.csv",
                       ["posting_date", "account_code", "description", "debit", "credit"],
                       [["2025-01-14", "4000", "Invoice INV-1", 0, 100000],
                        ["2025-01-14", "1100", "Invoice INV-1", 115000, 0]]))
    assert p.dataset_type == prof.GENERAL_LEDGER


def test_customs_records_are_recognised_by_their_declaration_reference():
    p = prof.build(doc("import_data.csv",
                       ["date", "customs_declaration_no", "supplier_name", "vat_amount"],
                       [["2025-02-01", "SAD-99001", "Overseas Co", 22000.00]]))
    assert p.dataset_type == prof.CUSTOMS_RECORDS


def test_a_pos_report_is_recognised_by_its_terminal():
    p = prof.build(doc("daily.csv", ["date", "terminal_id", "gross_amount"],
                       [["2025-01-02", "T-01", 18400.00], ["2025-01-03", "T-02", 9100.00]]))
    assert p.dataset_type == prof.POS_REPORT
    assert p.workstream == "sales"


def test_a_credit_note_listing_is_not_read_as_the_register_it_relates_to():
    p = prof.build(doc("adjustments.csv",
                       ["note_date", "note_number", "note_type", "customer_name", "vat_amount"],
                       [["2025-02-10", "CN-1", "Credit note", "Buyer A", -1500.00],
                        ["2025-02-11", "CN-2", "Credit note", "Buyer B", -900.00]]))
    assert p.dataset_type == prof.CREDIT_NOTE_LISTING


# ------------------------------------------------------------------ what it refuses to decide
def test_a_file_naming_both_sides_is_ambiguous_rather_than_resolved():
    """Precedence would pick one. Precedence would sometimes be wrong, and nobody would know."""
    p = prof.build(doc("ledger_detail.csv",
                       ["invoice_date", "customer_name", "supplier_name", "vat_amount"],
                       [["2025-01-14", "Buyer A", "", 15000.00]]))
    assert p.dataset_type == prof.UNKNOWN
    assert "ambiguous" in p.why


def test_a_listing_with_no_counterparty_column_does_not_guess_a_side():
    """A VAT amount alone cannot say whether these are sales or purchases."""
    p = prof.build(doc("data.csv", ["invoice_date", "invoice_number", "vat_amount"],
                       [["2025-01-14", "X-1", 15000.00]]))
    assert p.dataset_type == prof.UNKNOWN
    assert p.workstream == "unknown"
    assert "either" in p.why


def test_the_filename_may_break_a_tie_but_says_so_when_it_does():
    """A weak signal used as a weak signal is fine. Used silently it is not."""
    p = prof.build(doc("purchases_ledger.csv",
                       ["invoice_date", "invoice_number", "vat_amount"],
                       [["2025-01-09", "PI-1", 6000.00]]))
    assert p.dataset_type == prof.PURCHASE_REGISTER
    assert p.confidence == "low"
    assert "filename alone" in p.why


def test_an_empty_file_is_not_classified():
    p = prof.build(doc("empty.csv", ["invoice_date", "vat_amount"], []))
    assert p.dataset_type == prof.UNKNOWN
    assert any(f["code"] == "empty-dataset" for f in p.quality_flags)


# ------------------------------------------------------------------ column roles
def test_a_header_whose_values_contradict_it_is_downgraded_not_accepted():
    """`vat_amount` above a column of dates is a defect in the file, not a role to trust."""
    p = prof.build(doc("odd.csv", ["invoice_number", "customer_name", "vat_amount"],
                       [["INV-1", "Buyer A", "2025-01-14"], ["INV-2", "Buyer B", "2025-02-03"]]))
    vat = next(r for r in p.roles if r["role"] == R.VAT_AMOUNT)
    assert vat["confidence"] == "low"
    assert "dates" in vat["why"]


def test_a_role_is_inferred_from_values_when_the_header_says_nothing():
    p = prof.build(doc("nohdr.csv", ["col_a", "customer_name", "vat_amount"],
                       [["2025-01-14", "Buyer A", 15000.00],
                        ["2025-02-03", "Buyer B", 30000.00]]))
    inferred = next((r for r in p.roles if r["column"] == "col_a"), None)
    assert inferred is not None
    assert inferred["role"] == R.ISSUE_DATE
    assert inferred["confidence"] == "low", "an inference is never as good as a stated header"


def test_columns_the_engine_does_not_use_are_named_rather_than_dropped():
    """What the system is ignoring is as useful to an auditor as what it is reading."""
    p = prof.build(doc("s.csv",
                       ["invoice_date", "customer_name", "vat_amount", "salesperson_bonus_code"],
                       [["2025-01-14", "Buyer A", 15000.00, "ZZ9"]]))
    assert "salesperson_bonus_code" in p.unmapped_columns


def test_the_period_covered_is_read_from_the_authoritative_date():
    p = prof.build(doc("s.csv", *SALES))
    assert p.date_min == "2025-01-14"
    assert p.date_max == "2025-03-19"
    assert p.date_role == R.ISSUE_DATE


# ------------------------------------------------------------------ data quality
def test_malformed_dates_are_reported_with_their_rows():
    cols, rows = SALES
    bad = [list(r) for r in rows] + [["not a date", "INV-4", "Buyer D", 10.0, 1.5]]
    p = prof.build(doc("s.csv", cols, bad))
    flag = next(f for f in p.quality_flags if f["code"] == "malformed-date")
    assert flag["count"] == 1
    assert flag["rows"] == [4]


def test_a_blank_vat_amount_is_blocking_because_nothing_can_be_summed_over_it():
    cols, rows = SALES
    holed = [list(r) for r in rows]
    holed[1][4] = None
    p = prof.build(doc("s.csv", cols, holed))
    flag = next(f for f in p.quality_flags if f["code"] == "blank-vat-amount")
    assert flag["severity"] == "blocking"
    assert flag["rows"] == [2]


def test_mixed_signs_are_reported_as_a_convention_not_as_an_error():
    """Purchases represented negatively is a convention. Treating it as an error, or netting it
    away without saying so, is how two systems that agree are reported as disagreeing."""
    cols, rows = PURCHASES
    signed = [list(r) for r in rows]
    signed[0][4] = -6000.00
    p = prof.build(doc("p.csv", cols, signed))
    flag = next(f for f in p.quality_flags if f["code"] == "mixed-signs")
    assert "normalise" in flag["detail"]
    assert flag["severity"] == "advisory"


def test_a_repeated_reference_is_not_called_a_duplicate():
    """One invoice legitimately spans several accounting lines. Calling that duplication is a
    named failure mode, so the flag reports the fact and refuses the conclusion."""
    p = prof.build(doc("gl.csv",
                       ["invoice_date", "invoice_number", "customer_name", "vat_amount"],
                       [["2025-01-14", "INV-1", "Buyer A", 9000.00],
                        ["2025-01-14", "INV-1", "Buyer A", 6000.00]]))
    flag = next(f for f in p.quality_flags if f["code"] == "repeated-reference")
    assert "may be line-level accounting" in flag["detail"]
    assert "duplicat" not in flag["code"]


def test_inconsistent_vat_rates_are_reported():
    p = prof.build(doc("s.csv",
                       ["invoice_date", "customer_name", "taxable_amount", "vat_rate",
                        "vat_amount"],
                       [["2025-01-14", "Buyer A", 100.0, 15, 15.0],
                        ["2025-02-03", "Buyer B", 100.0, 5, 5.0]]))
    assert any(f["code"] == "multiple-vat-rates" for f in p.quality_flags)


def test_vat_that_does_not_follow_from_the_rate_is_reported():
    p = prof.build(doc("s.csv",
                       ["invoice_date", "customer_name", "taxable_amount", "vat_rate",
                        "vat_amount"],
                       [["2025-01-14", "Buyer A", 100000.0, 15, 15000.0],
                        ["2025-02-03", "Buyer B", 100000.0, 15, 1500.0]]))
    flag = next(f for f in p.quality_flags if f["code"] == "vat-not-consistent-with-rate")
    assert flag["rows"] == [2]


def test_a_stated_total_that_does_not_foot_is_reported():
    cols, rows = SALES
    p = prof.build(doc("s.csv", cols, rows, stated_totals={"vat_amount": 60000.00}))
    flag = next(f for f in p.quality_flags if f["code"] == "stated-total-does-not-foot")
    assert "54,000" in flag["detail"]


# ------------------------------------------------------------------ transformations
def test_a_value_the_pipeline_had_to_reformat_is_recorded_with_its_original():
    """The reconciliation must be replayable from the raw file, which it cannot be if the
    pipeline quietly repairs its inputs."""
    p = prof.build(doc("s.csv",
                       ["invoice_date", "customer_name", "vat_amount"],
                       [["14/01/2025", "Buyer A", "15,000.00"]]))
    by_col = {t["column"]: t for t in p.transformations}
    assert by_col["invoice_date"]["original"] == "14/01/2025"
    assert by_col["invoice_date"]["normalised"] == "2025-01-14"
    assert by_col["invoice_date"]["reason"]
    assert by_col["vat_amount"]["original"] == "15,000.00"
    assert by_col["vat_amount"]["transformation"] == "parsed as a number"


def test_a_clean_file_records_no_transformations():
    p = prof.build(doc("s.csv", *SALES))
    assert p.transformations == []

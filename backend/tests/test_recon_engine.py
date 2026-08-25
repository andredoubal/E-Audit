"""Stage 1 — the reconciliation framework, over the scenarios the specification names.

Every fixture is synthetic. None of them is the demo case, and that is deliberate: the fastest
way to prove a generic engine is not generic is to test it only against the file it was written
beside.

The scenarios are the awkward ones on purpose — signs, period boundaries, offsetting errors,
one invoice across several accounting lines. Each of them is a way for a comparison to report
that two systems disagree when they do not, or agree when they do not, and each is a mistake
that reaches a taxpayer if it is not caught here.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.evidence import profile as prof
from app.recon import engine, normalise as N, planner, registry as reg, status as S
from app.recon import tolerance as T

PERIOD_FROM = date(2025, 1, 1)
PERIOD_TO = date(2025, 3, 31)


def dataset(filename: str, columns: list[str], rows: list[list]) -> tuple[dict, list]:
    """A profiled dataset and its rows, the pair every comparison needs."""
    p = prof.build({"filename": filename,
                    "content": {"format": "csv", "columns": columns, "rows": rows}})
    return p.to_dict(), rows


SALES_COLS = ["invoice_date", "invoice_number", "customer_name", "taxable_amount", "vat_amount"]
PURCH_COLS = ["invoice_date", "invoice_number", "supplier_name", "taxable_amount", "vat_amount"]


def run(definition_id: str, files: dict[str, tuple[dict, list]],
        declared: dict[str, float] | None = None,
        period=(PERIOD_FROM, PERIOD_TO)) -> engine.Result:
    profiles = {name: p for name, (p, _) in files.items()}
    rows = {name: r for name, (_, r) in files.items()}
    d = reg.BY_ID[definition_id]
    plan = planner.plan_one(d, list(profiles.values()), return_on_file=declared is not None)
    return engine.run(plan, profiles=profiles, rows_by_file=rows, declared=declared or {},
                      period_from=period[0], period_to=period[1])


# ------------------------------------------------------------------ the five statuses
def test_two_sources_that_agree_are_reconciled():
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-01-14", "INV-1", "Buyer A", 100000, 15000],
                                 ["2025-02-03", "INV-2", "Buyer B", 100000, 15000]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 30000.0})
    assert r.status == S.RECONCILED
    assert r.variance == 0.0
    assert "agree exactly" in r.explanation


def test_a_difference_under_tolerance_is_reconciled_but_still_reported():
    """Never hidden. An auditor looking for a pattern across a hundred comparisons needs the
    small ones to still be there."""
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-01-14", "INV-1", "Buyer A", 100000, 15000]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 14900.0})
    assert r.status == S.RECONCILED
    assert r.variance == 100.0, "the figure survives even though the status is reconciled"
    assert "reported rather than removed" in r.explanation


def test_a_material_unexplained_difference_is_a_variance_and_not_an_allegation():
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-01-14", "INV-1", "Buyer A", 1000000, 150000]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 100000.0})
    assert r.status == S.VARIANCE
    assert r.variance == 50000.0
    assert "question for the investigation" in r.explanation
    assert S.is_neutral(r.explanation)


def test_a_missing_dataset_is_insufficient_evidence_and_never_a_variance():
    """The defect this refuses: subtracting an absent listing from a declared figure reports
    the whole box as a discrepancy."""
    r = run("purchase-register-vs-return", {}, {"standard_rate_purchase": 150000.0})
    assert r.status == S.INSUFFICIENT
    assert r.variance == 0.0
    assert "missing document rather than a difference" in r.explanation
    assert r.needs == ["Purchases register"]


# ------------------------------------------------------------------ period scope
def test_transactions_outside_the_period_are_scoped_out_and_quantified():
    """A full-year export against a quarterly return differs by nine months of trade. Reporting
    that as a variance is the most confident way to be wrong about a compliant taxpayer."""
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-02-14", "INV-1", "Buyer A", 100000, 15000],
                                 ["2025-07-02", "INV-2", "Buyer B", 400000, 60000]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 15000.0})

    assert r.value_a == 15000.0, "only the in-period row is compared"
    # Not simply "reconciled": SAR 60,000 of difference existed on the dataset as supplied and
    # period scope accounts for the whole of it. Saying so is the difference between a
    # comparison that agreed and one that was made to agree for a stated reason.
    assert r.status == S.EXPLAINED
    assert r.residual == 0.0
    cause = next(c for c in r.causes if c["cause"] == S.PERIOD)
    assert cause["amount"] == 60000.0
    assert "not themselves a defect" in cause["detail"]


def test_period_scope_can_explain_part_of_a_difference_and_leave_a_residual():
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-02-14", "INV-1", "Buyer A", 1000000, 150000],
                                 ["2025-09-02", "INV-2", "Buyer B", 400000, 60000]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 100000.0})
    assert r.status == S.PARTIAL
    assert r.residual == 50000.0
    assert "remains without a deterministic cause" in r.explanation


def test_a_row_with_no_date_stays_in_period_rather_than_being_dropped():
    """Quietly excluding it would understate the side it belongs to."""
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-02-14", "INV-1", "Buyer A", 100000, 15000],
                                 ["", "INV-2", "Buyer B", 100000, 15000]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 30000.0})
    assert r.value_a == 30000.0
    assert r.period["a"]["undated_count"] == 1


# ------------------------------------------------------------------ signs
def test_a_wholly_negative_column_is_read_as_an_inverted_convention():
    """Purchases stated negatively throughout is a convention, not a disagreement."""
    files = {"p.csv": dataset("p.csv", PURCH_COLS,
                              [["2025-01-09", "PI-1", "Vendor A", -40000, -6000],
                               ["2025-02-22", "PI-2", "Vendor B", -12000, -1800]])}
    r = run("purchase-register-vs-return", files, {"standard_rate_purchase": 7800.0})
    assert r.value_a == 7800.0, "magnitudes are compared, so the two sides agree"
    assert r.status == S.RECONCILED
    assert any(c["cause"] == S.SIGN for c in r.causes)
    assert r.conventions[0]["convention"] == N.INVERTED


def test_a_mixed_sign_column_is_summed_as_written_because_the_signs_are_information():
    """Invoices positive and credit notes negative is the file telling you something. Taking
    magnitudes there would silently add the credit notes to the total instead of netting them."""
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-01-14", "INV-1", "Buyer A", 100000, 15000],
                                 ["2025-02-03", "CN-1", "Buyer A", -20000, -3000]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 12000.0})
    assert r.value_a == 12000.0
    assert r.status == S.RECONCILED
    assert r.conventions[0]["convention"] == N.MIXED


# ------------------------------------------------------------------ rows that cannot be read
def test_an_unreadable_amount_is_skipped_and_counted_never_summed_as_zero():
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-01-14", "INV-1", "Buyer A", 100000, 15000],
                                 ["2025-02-03", "INV-2", "Buyer B", 100000, "n/a"]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 15000.0})
    assert r.value_a == 15000.0
    assert r.status == S.RECONCILED
    assert any("could not be read as a number" in q for q in r.quality_notes)


# ------------------------------------------------------------------ transaction grain
def test_one_invoice_across_several_lines_is_aggregated_not_treated_as_duplication():
    """A named failure mode: repeated references are line-level accounting until shown
    otherwise, and comparing them row by row would report both lines as disagreeing."""
    listing = dataset("reg.csv", SALES_COLS,
                      [["2025-01-14", "INV-1", "Buyer A", 60000, 9000],
                       ["2025-01-14", "INV-1", "Buyer A", 40000, 6000]])
    authority = dataset("zatca.csv", SALES_COLS + ["status"],
                        [["2025-01-14", "INV-1", "Buyer A", 100000, 15000, "cleared"]])
    r = run("sales-register-vs-einvoices",
            {"reg.csv": listing, "zatca.csv": authority})
    assert r.status == S.RECONCILED
    assert r.contributions == [], "the two lines aggregate to the Authority's single invoice"


def test_offsetting_row_errors_do_not_hide_behind_agreeing_totals():
    """The failure this exists to catch. An invoice missing from one side and a value
    difference on another can nearly cancel; a status read off the net figure would call
    that reconciled while SAR 100,000 of rows disagree."""
    listing = dataset("reg.csv", SALES_COLS,
                      [["2025-01-14", "INV-1", "Buyer A", 400000, 60000],
                       ["2025-02-03", "INV-2", "Buyer B", 100000, 15000]])
    authority = dataset("zatca.csv", SALES_COLS + ["status"],
                        [["2025-01-14", "INV-1", "Buyer A", 66667, 10000, "cleared"],
                         ["2025-02-03", "INV-2", "Buyer B", 100000, 15000, "cleared"],
                         ["2025-03-01", "INV-9", "Buyer C", 333333, 50000, "cleared"]])
    r = run("sales-register-vs-einvoices", {"reg.csv": listing, "zatca.csv": authority})

    assert abs(r.variance) == 0.0, "the totals agree exactly — that is the trap"
    assert r.status == S.VARIANCE, "but the rows do not"
    assert "partly offset each other" in r.explanation


def test_a_transaction_comparison_names_the_documents_on_each_side():
    listing = dataset("reg.csv", SALES_COLS,
                      [["2025-01-14", "INV-1", "Buyer A", 100000, 15000]])
    authority = dataset("zatca.csv", SALES_COLS + ["status"],
                        [["2025-01-14", "INV-1", "Buyer A", 100000, 15000, "cleared"],
                         ["2025-02-01", "INV-2", "Buyer B", 200000, 30000, "cleared"]])
    r = run("sales-register-vs-einvoices", {"reg.csv": listing, "zatca.csv": authority})
    missing = next(c for c in r.contributions if c["reference"] == "INV-2")
    assert missing["side"] == "b"
    assert missing["amount"] == 30000.0
    assert "zatca.csv" in missing["note"]


def test_a_total_comparison_claims_no_attribution_because_none_is_real():
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-01-14", "INV-1", "Buyer A", 1000000, 150000]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 100000.0})
    assert r.contributions == []
    assert "cannot be attributed to particular rows" in r.explanation


# ------------------------------------------------------------------ the vocabulary guard
def test_the_reconciliation_stage_cannot_say_a_taxpayer_did_anything_wrong():
    """Not a style rule. Once a compliance word is in the data it reaches the report and the
    taxpayer, and these figures cannot establish any of them."""
    for word in ("violation", "non-compliant", "fraudulent", "invalid deduction",
                 "tax evasion", "not deductible"):
        with pytest.raises(ValueError):
            S.assert_neutral(f"the register shows a {word} of the rules")
    S.assert_neutral("the register exceeds the declared figure by SAR 618,000")


def test_every_explanation_the_engine_writes_is_neutral():
    """Asserted over the real outputs, not just over the guard in isolation."""
    listing = dataset("reg.csv", SALES_COLS,
                      [["2025-01-14", "INV-1", "Buyer A", 1000000, 150000],
                       ["2025-08-02", "INV-2", "Buyer B", 100000, 15000]])
    for did in ("sales-register-vs-return", "sales-register-vs-einvoices",
                "purchase-register-vs-return"):
        r = run(did, {"reg.csv": listing}, {"standard_rate_sales": 100000.0})
        assert S.is_neutral(r.explanation), (did, r.explanation)
        for c in r.causes:
            assert S.is_neutral(c["detail"])


# ------------------------------------------------------------------ tolerances
def test_a_tolerance_is_published_with_every_result_so_it_can_be_argued_with():
    files = {"reg.csv": dataset("reg.csv", SALES_COLS,
                                [["2025-01-14", "INV-1", "Buyer A", 100000, 15000]])}
    r = run("sales-register-vs-return", files, {"standard_rate_sales": 15000.0})
    assert r.tolerance["name"] == "declared"
    assert r.tolerance["allowance"] == 150.0, "1% of the larger side"
    assert r.tolerance["note"]


def test_rounding_is_only_claimed_where_the_profile_actually_models_it():
    per_row = T.get("per-row")
    assert per_row.allowance(larger=1_000_000, rows=10_000) == 100.0
    declared = T.get("declared")
    assert declared.rounding_per_row == 0.0
    assert declared.allowance(larger=1_000_000, rows=10_000) == 10_000.0

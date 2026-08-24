"""The six comparisons at three levels.

Three sources per workstream can disagree in three pairings, and *which pair* disagrees is the
only information that changes what an auditor does next. The tests here are about keeping those
apart, and about the two levels below the headline — because a difference invisible at one level
is obvious at the next, and a case whose totals agree can have moved money between VAT boxes.

Synthetic fixtures throughout. None is the demo case.
"""
from __future__ import annotations

import pytest

from app.canonical import build as canon
from app.canonical.model import STANDARD, UNCLASSIFIED, ZERO_RATED
from app.evidence import profile as prof
from app.recon import observations as obs
from app.recon import pairwise as P
from app.recon import status as S
from app.recon import tolerance as T

SALES_COLS = ["invoice_date", "invoice_number", "customer_name", "customer_vat_number",
              "taxable_amount", "vat_rate", "vat_amount"]


def ds(filename: str, rows: list[list], columns: list[str] | None = None):
    cols = columns or SALES_COLS
    p = prof.build({"filename": filename,
                    "content": {"format": "csv", "columns": cols, "rows": rows}}).to_dict()
    return canon.build(p, rows)


def side(source: str, label: str, dataset=None, total=None, present=True, metric="vat"):
    if dataset is not None:
        return P.Side(source=source, label=label, origin=dataset.source_file,
                      total=dataset.total(metric), count=dataset.count,
                      counted=dataset.counted(metric), dataset=dataset, present=True)
    return P.Side(source=source, label=label, origin="the filed VAT return",
                  total=total, present=present)


def run(code: str, a: P.Side, b: P.Side, metric="vat", tol=None) -> P.Comparison:
    return P.compare(P.BY_CODE[code], a, b, metric, tol=tol or T.DECLARED)


# ============================================================ the six exist and are distinct
def test_there_are_six_pairings_and_each_names_what_a_difference_would_mean():
    assert len(P.PAIRINGS) == 6
    assert {p.code for p in P.PAIRINGS} == {"S1", "S2", "S3", "P1", "P2", "P3"}
    for p in P.PAIRINGS:
        assert p.question, f"{p.code} does not say what a difference there would mean"
        assert p.a != p.b


def test_the_three_sales_pairings_cover_every_pair_of_the_three_sources():
    sales = [p for p in P.PAIRINGS if p.workstream == "sales"]
    pairs = {frozenset((p.a, p.b)) for p in sales}
    assert pairs == {
        frozenset((P.REGISTER, P.EINVOICE)),
        frozenset((P.EINVOICE, P.RETURN)),
        frozenset((P.RETURN, P.REGISTER)),
    }


# ============================================================ a missing source
def test_a_missing_source_is_not_a_zero_side():
    """Subtracting an absent register from a declared figure reports the whole box as a
    discrepancy — a finding fabricated out of a missing file."""
    c = run("S3", side(P.RETURN, "VAT return", total=2_000_000.0),
            side(P.REGISTER, "Sales register", present=False))
    assert c.runnable is False
    assert c.status == S.INSUFFICIENT
    assert c.variance is None, "not 2,000,000 — there is nothing to subtract"
    assert c.needs == ["Sales register"]


def test_a_missing_field_blocks_the_metric_rather_than_producing_a_variance():
    """A file with no gross column has not got gross of zero."""
    a = ds("r.csv", [["2025-01-14", "INV-1", "B", "300", 100000, 15, 15000]])
    c = run("S1", side(P.REGISTER, "Sales register", a, metric="gross"),
            side(P.EINVOICE, "E-invoices", a, metric="gross"), metric="gross")
    assert c.runnable is False
    assert any("does not carry a readable gross amount" in b for b in c.blocked_by)


# ============================================================ level 1
def test_two_sources_that_agree_reconcile():
    a = ds("r.csv", [["2025-01-14", "INV-1", "B", "300", 100000, 15, 15000]])
    c = run("S3", side(P.RETURN, "VAT return", total=15000.0),
            side(P.REGISTER, "Sales register", a))
    assert c.status == S.RECONCILED
    assert c.variance == 0.0


def test_a_material_difference_is_a_variance_and_says_nothing_about_a_taxpayer():
    a = ds("r.csv", [["2025-01-14", "INV-1", "B", "300", 1000000, 15, 150000]])
    c = run("S3", side(P.RETURN, "VAT return", total=100000.0),
            side(P.REGISTER, "Sales register", a))
    assert c.status == S.VARIANCE
    assert c.variance == -50000.0


# ============================================================ level 2 — the point of it
def test_totals_that_agree_can_hide_a_material_difference_inside_one_vat_treatment():
    """The case level 2 exists for. Money moved between zero-rated and standard-rated nets to
    nothing overall, and the only place it shows is the category breakdown."""
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 150_000],
        ["2025-01-15", "INV-2", "C", "300", 1_000_000, 0, 0],
    ])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 500_000, 15, 75_000],
        ["2025-01-15", "INV-2", "C", "300", 1_500_000, 5, 75_000],
    ])
    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))

    assert c.variance == 0.0, "the totals agree exactly — that is the trap"
    rows = {t.treatment: t for t in c.treatments}
    assert rows[STANDARD].variance == 75_000.0
    assert rows[ZERO_RATED].variance == 0.0
    assert rows[UNCLASSIFIED].variance == -75_000.0
    assert any(t.status == S.VARIANCE for t in c.treatments)


def test_a_treatment_breakdown_needs_records_on_both_sides_and_says_so_otherwise():
    """The VAT return is a set of declared totals, not transactions."""
    a = ds("r.csv", [["2025-01-14", "INV-1", "B", "300", 100000, 15, 15000]])
    c = run("S3", side(P.RETURN, "VAT return", total=1.0),
            side(P.REGISTER, "Sales register", a))
    assert c.treatments == []
    assert any("declared totals rather than transactions" in n for n in c.notes)


# ============================================================ level 3
def test_one_invoice_across_several_lines_is_aggregated_not_called_duplication():
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 600_000, 15, 90_000],
        ["2025-01-14", "INV-1", "B", "300", 400_000, 15, 60_000],
    ])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 150_000]])
    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))

    assert c.match_counts.get(P.EXACT) == 1
    assert P.DUPLICATE not in c.match_counts
    row = next(m for m in c.matches if m.reference == "INV-1")
    assert "spans several accounting lines" in row.detail


def test_a_record_on_one_side_only_is_named_with_the_file_it_came_from():
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 100_000, 15, 15_000]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 100_000, 15, 15_000],
        ["2025-02-01", "INV-2", "C", "300", 200_000, 15, 30_000]])
    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))

    only = next(m for m in c.matches if m.status == P.B_ONLY)
    assert only.reference == "INV-2"
    assert only.b_amount == 30_000.0
    assert only.b_records == ["zatca.csv#2"], "traceable to the row"


def test_a_period_difference_is_recorded_as_timing_and_not_as_a_defect():
    register = ds("register.csv", [
        ["2025-01-31", "INV-1", "B", "300", 100_000, 15, 15_000]])
    einvoice = ds("zatca.csv", [
        ["2025-02-02", "INV-1", "B", "300", 100_000, 15, 15_000]])
    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))

    row = next(m for m in c.matches if m.reference == "INV-1")
    assert row.status == P.PERIOD_MISMATCH
    assert "not as a defect" in row.detail


def test_the_strongest_disagreement_is_the_one_reported_so_one_document_makes_one_row():
    """A value difference is not also reported as a date difference — two rows for one
    document would double the exception count and the money behind it."""
    register = ds("register.csv", [
        ["2025-01-31", "INV-1", "B", "300", 100_000, 15, 15_000]])
    einvoice = ds("zatca.csv", [
        ["2025-03-02", "INV-1", "B", "300", 200_000, 15, 30_000]])
    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))

    rows = [m for m in c.matches if m.reference == "INV-1"]
    assert len(rows) == 1
    assert rows[0].status == P.VAT_MISMATCH


def test_records_with_no_identifier_are_reported_rather_than_treated_as_absent():
    register = ds("register.csv", [
        ["2025-01-14", "", "B", "300", 100_000, 15, 15_000]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 100_000, 15, 15_000]])
    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))

    row = next(m for m in c.matches if m.status == P.NO_IDENTIFIER)
    assert row.a_records == ["register.csv#1"]
    assert "cannot be matched" in row.detail


def test_offsetting_row_errors_do_not_hide_behind_agreeing_totals():
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 400_000, 15, 60_000],
        ["2025-02-03", "INV-2", "C", "300", 100_000, 15, 15_000]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 66_667, 15, 10_000],
        ["2025-02-03", "INV-2", "C", "300", 100_000, 15, 15_000],
        ["2025-03-01", "INV-9", "D", "300", 333_333, 15, 50_000]])
    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))

    assert c.variance == 0.0, "the totals agree exactly"
    assert c.status == S.VARIANCE, "but the rows do not"
    assert any("partly offset each other" in n for n in c.notes)


# ============================================================ observations and exceptions
def test_an_observation_states_a_count_and_a_sum_and_never_a_conclusion():
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 100_000, 15, 15_000]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 100_000, 15, 15_000],
        ["2025-02-01", "INV-2", "C", "300", 200_000, 15, 30_000]])
    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))
    observations, exceptions = obs.derive([c])

    unmatched = next(o for o in observations if "could not be matched" in o.text)
    assert "1 record(s)" in unmatched.text
    assert "SAR 30,000.00" in unmatched.text
    for o in observations:
        assert S.is_neutral(o.text), o.text


def test_an_exception_carries_the_records_and_the_files_behind_it():
    """The AI layer receives structured exceptions, not every row of every spreadsheet."""
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 100_000, 15, 15_000]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 100_000, 15, 15_000],
        ["2025-02-01", "INV-2", "C", "300", 200_000, 15, 30_000]])
    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))
    _, exceptions = obs.derive([c])

    e = next(x for x in exceptions if x.kind == obs.UNMATCHED)
    assert e.id.startswith("SAL-")
    assert e.pairing == "S1"
    assert e.reconciliation == "Sales register ↔ E-invoices"
    assert e.affected_count == 1
    assert e.records == ["zatca.csv#2"]
    assert set(e.source_files) == {"register.csv", "zatca.csv"}
    assert e.observation


def test_a_comparison_that_could_not_run_becomes_an_exception_naming_what_is_missing():
    c = run("P3", side(P.RETURN, "VAT return", total=150_000.0),
            side(P.REGISTER, "Purchase register", present=False))
    observations, exceptions = obs.derive([c])
    e = exceptions[0]
    assert e.kind == obs.NOT_RUN
    assert e.variance is None, "a missing document is not a difference"
    assert "could not be compared" in observations[0].text


def test_no_observation_the_engine_writes_asserts_a_compliance_conclusion():
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 150_000],
        ["2025-01-15", "", "C", "300", 500_000, 0, 0]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 500_000, 15, 75_000],
        ["2025-03-09", "INV-7", "D", "300", 100_000, 5, 5_000]])
    comparisons = [run("S1", side(P.REGISTER, "Sales register", register),
                       side(P.EINVOICE, "E-invoices", einvoice)),
                   run("S3", side(P.RETURN, "VAT return", total=1.0),
                       side(P.REGISTER, "Sales register", register))]
    observations, exceptions = obs.derive(comparisons)
    assert observations
    for o in observations:
        assert S.is_neutral(o.text), o.text
    for e in exceptions:
        assert S.is_neutral(e.observation), e.observation


# ============================================================ one matter is counted once
def test_the_same_records_measured_in_two_metrics_are_one_exception_not_two():
    """A VAT difference and the taxable amount underneath it are one disagreement read twice.

    Kept apart they are investigated twice, reported twice and — the defect that matters —
    added together: on the demo case that turned a SAR 618,000 sales excess into a headline of
    SAR 15.8m.
    """
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 150_000]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 150_000],
        ["2025-02-02", "INV-9", "D", "300", 400_000, 15, 60_000]])

    a_vat = side(P.REGISTER, "Sales register", register)
    b_vat = side(P.EINVOICE, "E-invoices", einvoice)
    a_base = side(P.REGISTER, "Sales register", register, metric="taxable")
    b_base = side(P.EINVOICE, "E-invoices", einvoice, metric="taxable")

    _, exceptions = obs.derive([run("S1", a_vat, b_vat),
                                run("S1", a_base, b_base, metric="taxable")])

    unmatched = [e for e in exceptions if e.kind == obs.UNMATCHED]
    assert len(unmatched) == 1, "the same unmatched invoice must not become two exceptions"
    e = unmatched[0]
    assert e.metric == "vat", "VAT is the money, so it states the matter"
    assert e.variance == 60_000.0
    assert [a["metric"] for a in e.also_measured] == ["taxable"]
    assert e.also_measured[0]["variance"] == 400_000.0


def test_exceptions_resting_on_different_comparisons_keep_their_own_basis():
    """S1 and S3 disagree about different pairs of sources — folding them would hide which."""
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 150_000]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 190_000]])

    _, exceptions = obs.derive([
        run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice)),
        run("S3", side(P.RETURN, "VAT return", total=90_000.0),
            side(P.REGISTER, "Sales register", register))])

    bases = {e.basis for e in exceptions}
    assert len({b.split("|")[0] for b in bases}) == 2, "S1 and S3 must stay apart"


def test_totals_that_net_to_zero_are_not_described_as_agreeing():
    """An omission on one side offset by an overstatement on the other is not agreement, and
    the sentence must not contradict the variance badge above it."""
    register = ds("register.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 150_000],
        ["2025-01-20", "INV-2", "C", "300", 200_000, 15, 30_000]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 180_000]])

    c = run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice))
    assert c.variance == 0.0 and c.status == S.VARIANCE, "fixture: totals net, records do not"

    observations, _ = obs.derive([c])
    overall = observations[0].text
    assert "the two agree." not in overall
    assert "records within them do not" in overall
    assert S.is_neutral(overall)


def test_two_observations_reading_identically_are_not_printed_twice():
    """A sentence that names no metric says the same thing under VAT and under taxable amount."""
    register = ds("register.csv", [
        ["2025-01-14", "", "B", "300", 1_000_000, 15, 150_000]])
    einvoice = ds("zatca.csv", [
        ["2025-01-14", "INV-1", "B", "300", 1_000_000, 15, 150_000]])

    observations, _ = obs.derive([
        run("S1", side(P.REGISTER, "Sales register", register),
            side(P.EINVOICE, "E-invoices", einvoice)),
        run("S1", side(P.REGISTER, "Sales register", register, metric="taxable"),
            side(P.EINVOICE, "E-invoices", einvoice, metric="taxable"), metric="taxable")])

    texts = [o.text for o in observations]
    assert len(texts) == len(set(texts))

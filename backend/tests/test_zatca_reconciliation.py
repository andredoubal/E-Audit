"""Guards for the deterministic ZATCA matcher.

The property that matters most is the refusal: **one side is not a comparison.** With only a
taxpayer listing, or only a ZATCA extract, every record on the side that exists matches nothing
— and reporting all of them as unmatched would be a fabricated finding carrying a fabricated
amount, which is the worst thing this module could produce. That is tested first.

After that, one test per rule, plus the two ways a rule table gets quietly wrong: two rules
firing on one disagreement (so a single difference reads as two findings), and formatting
differences being reported as substance.

No database and no model — `compare()` is a pure function over two extracted files.
"""
from app.pipeline import reconciliation as zr

COLUMNS = ["invoice_number", "invoice_date", "customer_name", "customer_vat_number",
           "taxable_amount", "vat_amount"]


def rows(*specs) -> dict:
    """(ref, date, vat_no, net, vat) tuples -> an extracted-file shape."""
    return {"columns": list(COLUMNS),
            "rows": [[ref, d, "Buyer Co", vat_no, net, vat]
                     for ref, d, vat_no, net, vat in specs]}


BASE = (("INV-001", "2025-01-10", "300000000000003", 1000.0, 150.0),
        ("INV-002", "2025-01-20", "300000000000003", 2000.0, 300.0),
        ("INV-003", "2025-02-05", "300000000000003", 3000.0, 450.0))


def codes(c) -> list[str]:
    return sorted(m.code for m in c.mismatches)


# --------------------------------------------------------------- the refusal
def test_no_zatca_dataset_is_not_a_comparison():
    c = zr.compare(listing=rows(*BASE), zatca=None)
    assert c.comparable is False
    assert c.mismatches == []
    assert "both sides" in c.note
    assert c.listing_count == 3


def test_no_taxpayer_listing_is_not_a_comparison_either():
    c = zr.compare(listing=None, zatca=rows(*BASE))
    assert c.comparable is False
    assert c.mismatches == []
    assert c.zatca_count == 3


def test_an_empty_file_counts_as_no_side():
    """A header row with nothing under it is not evidence that nothing was invoiced."""
    c = zr.compare(listing={"columns": COLUMNS, "rows": []}, zatca=rows(*BASE))
    assert c.comparable is False


# --------------------------------------------------------------- agreement
def test_two_identical_populations_produce_nothing():
    c = zr.compare(listing=rows(*BASE), zatca=rows(*BASE))
    assert c.comparable is True
    assert c.mismatches == []
    assert (c.listing_count, c.zatca_count, c.matched_count) == (3, 3, 3)


def test_reference_formatting_is_not_a_mismatch():
    """'INV-001' and 'inv 001' are the same invoice. Reporting that as a difference would
    bury the real ones under noise the taxpayer cannot act on."""
    other = (("inv 001", "2025-01-10", "300000000000003", 1000.0, 150.0),
             ("INV_002", "2025-01-20", "300000000000003", 2000.0, 300.0),
             ("inv-003", "2025-02-05", "300000000000003", 3000.0, 450.0))
    c = zr.compare(listing=rows(*BASE), zatca=rows(*other))
    assert c.mismatches == []
    assert c.matched_count == 3


# --------------------------------------------------------------- one side only
def test_an_invoice_zatca_holds_and_the_listing_omits_is_blocking():
    extra = BASE + (("INV-004", "2025-03-01", "300000000000003", 8000.0, 1200.0),)
    c = zr.compare(listing=rows(*BASE), zatca=rows(*extra))

    found = c.by_code("ZR-01")
    assert len(found) == 1
    assert found[0].severity == zr.BLOCKING
    assert found[0].vat_at_stake == 1200.0, "the VAT on an omitted invoice is what is at stake"
    assert "INV-004" in found[0].detail


def test_an_invoice_the_listing_holds_and_zatca_does_not_is_advisory():
    """A different conversation: the supply is declared, the document never cleared."""
    extra = BASE + (("INV-009", "2025-03-01", "300000000000003", 8000.0, 1200.0),)
    c = zr.compare(listing=rows(*extra), zatca=rows(*BASE))

    found = c.by_code("ZR-02")
    assert len(found) == 1
    assert found[0].severity == zr.ADVISORY
    assert found[0].vat_at_stake == 0.0, \
        "an invoice already in the listing is already in the declared figure"


# --------------------------------------------------------------- matched but disagreeing
def test_a_vat_amount_that_differs_is_reported_with_the_gap():
    changed = (("INV-001", "2025-01-10", "300000000000003", 1000.0, 190.0),) + BASE[1:]
    c = zr.compare(listing=rows(*BASE), zatca=rows(*changed))

    found = c.by_code("ZR-03")
    assert len(found) == 1
    assert found[0].vat_at_stake == 40.0
    assert found[0].field == "vat_amount"


def test_a_riyal_of_difference_is_not_a_mismatch():
    changed = (("INV-001", "2025-01-10", "300000000000003", 1000.0, 150.6),) + BASE[1:]
    assert zr.compare(listing=rows(*BASE), zatca=rows(*changed)).mismatches == []


def test_a_taxable_amount_that_differs_is_its_own_finding():
    changed = (("INV-001", "2025-01-10", "300000000000003", 1400.0, 150.0),) + BASE[1:]
    c = zr.compare(listing=rows(*BASE), zatca=rows(*changed))
    assert codes(c) == ["ZR-04"]
    assert c.by_code("ZR-04")[0].vat_at_stake == 0.0, \
        "the VAT agrees — the amount at stake belongs to the VAT rule, not this one"


def test_a_date_difference_within_the_month_is_advisory():
    changed = (("INV-001", "2025-01-14", "300000000000003", 1000.0, 150.0),) + BASE[1:]
    c = zr.compare(listing=rows(*BASE), zatca=rows(*changed))
    assert codes(c) == ["ZR-05"]
    assert c.by_code("ZR-05")[0].severity == zr.ADVISORY


def test_a_date_difference_across_a_month_end_is_blocking_and_reported_once():
    """It moves the invoice between return periods — and it is one disagreement, not two."""
    changed = (("INV-001", "2025-02-02", "300000000000003", 1000.0, 150.0),) + BASE[1:]
    c = zr.compare(listing=rows(*BASE), zatca=rows(*changed))

    assert codes(c) == ["ZR-06"], "ZR-05 must not also fire on a cross-period difference"
    assert c.by_code("ZR-06")[0].severity == zr.BLOCKING


def test_a_different_counterparty_vat_number_is_reported():
    changed = (("INV-001", "2025-01-10", "300000000000009", 1000.0, 150.0),) + BASE[1:]
    c = zr.compare(listing=rows(*BASE), zatca=rows(*changed))
    assert codes(c) == ["ZR-07"]


# --------------------------------------------------------------- within one side
def test_a_repeated_invoice_number_in_the_listing_is_blocking():
    dupes = BASE + (("INV-002", "2025-01-20", "300000000000003", 2000.0, 300.0),)
    c = zr.compare(listing=rows(*dupes), zatca=rows(*BASE))

    found = c.by_code("ZR-08")
    assert len(found) == 1
    assert found[0].severity == zr.BLOCKING
    assert found[0].vat_at_stake == 300.0, "the second copy is the amount counted twice"


def test_a_repeated_number_with_different_values_names_no_amount():
    """Two supplies sharing a number is a defect, but nothing here says which is the excess."""
    dupes = BASE + (("INV-002", "2025-01-22", "300000000000003", 7000.0, 1050.0),)
    c = zr.compare(listing=rows(*dupes), zatca=rows(*BASE))

    found = c.by_code("ZR-08")[0]
    assert found.vat_at_stake == 0.0
    assert "differing" in found.detail


def test_a_repeated_number_in_zatcas_own_records_is_ours_to_look_at():
    dupes = BASE + (("INV-002", "2025-01-20", "300000000000003", 2000.0, 300.0),)
    c = zr.compare(listing=rows(*BASE), zatca=rows(*dupes))

    found = c.by_code("ZR-09")
    assert len(found) == 1
    assert found[0].severity == zr.ADVISORY, "a duplicate on our side is not a taxpayer defect"


def test_rows_with_no_invoice_number_are_unmatchable_not_agreeing():
    blank = BASE + ((None, "2025-03-02", "300000000000003", 500.0, 75.0),)
    c = zr.compare(listing=rows(*blank), zatca=rows(*BASE))

    found = c.by_code("ZR-10")
    assert len(found) == 1
    assert found[0].severity == zr.BLOCKING
    assert "1 of 4" in found[0].detail
    assert not c.by_code("ZR-02"), "an unnumbered row is not 'missing from ZATCA'"


# --------------------------------------------------------------- sequence gaps
def _numbered(*nums):
    return tuple((f"INV-{n:04d}", "2025-01-10", "300000000000003", 1000.0, 150.0) for n in nums)


def test_a_hole_in_contiguous_numbering_is_raised_as_a_question():
    listing = _numbered(1, 2, 3, 4, 6, 7, 8)
    c = zr.compare(listing=rows(*listing), zatca=rows(*listing))

    found = c.by_code("ZR-12")
    assert len(found) == 1
    assert "INV-0005" in found[0].detail
    assert found[0].severity == zr.ADVISORY
    assert "may be cancelled" in found[0].detail, "it must ask, not conclude"


def test_scattered_references_are_not_called_a_sequence():
    """Invoice numbers are only sequential when the taxpayer's system makes them so. A
    confident list of hundreds of 'missing' invoices is worse than saying nothing."""
    listing = _numbered(4, 91, 260, 1500, 7742)
    c = zr.compare(listing=rows(*listing), zatca=rows(*listing))
    assert c.by_code("ZR-12") == []


def test_unnumbered_rows_explain_the_holes_rather_than_adding_a_second_finding():
    """Three blank references and three missing numbers are one defect, not two.

    Reported separately, the taxpayer is asked to produce invoices that are sitting in the file
    they already sent.
    """
    listing = _numbered(1, 2, 3, 4, 6, 7, 8) + ((None, "2025-01-10", "3000", 1000.0, 150.0),)
    c = zr.compare(listing=rows(*listing), zatca=rows(*listing))

    assert c.by_code("ZR-10"), "the unnumbered row is still reported"
    assert c.by_code("ZR-12") == [], "and the hole it leaves is not reported a second time"


def test_a_short_run_is_not_a_numbering_scheme():
    listing = _numbered(1, 2, 4)
    assert zr.compare(listing=rows(*listing), zatca=rows(*listing)).by_code("ZR-12") == []


# --------------------------------------------------------------- the shape of the output
def test_every_rule_is_declared_once_and_carries_its_own_note():
    assert len(zr.RULE_BY_CODE) == len(zr.RULES), "two rules share a code"
    for r in zr.RULES:
        assert r.note, f"{r.code} has no explanation of what it is for"
        assert r.severity in (zr.BLOCKING, zr.ADVISORY)
        assert r.scope in (zr.PAIR, zr.UNMATCHED, zr.GROUP, zr.ROW, zr.POPULATION)
        if r.scope in (zr.UNMATCHED, zr.GROUP, zr.ROW, zr.POPULATION):
            assert r.side in (zr.LISTING, zr.ZATCA), f"{r.code} must name a side"


def test_the_serialised_comparison_groups_by_category():
    extra = BASE + (("INV-004", "2025-03-01", "300000000000003", 8000.0, 1200.0),)
    d = zr.compare(listing=rows(*BASE), zatca=rows(*extra)).to_dict()

    assert d["comparable"] is True
    omission = next(c for c in d["categories"] if c["category"] == zr.OMISSION)
    assert omission["count"] == 1 and omission["vat_at_stake"] == 1200.0
    assert d["blocking"] == 1
    assert len(d["rules"]) == len(zr.RULES), "the UI can explain every rule it may show"


def test_the_amount_at_stake_is_read_per_rule_not_summed_across_them():
    """A value difference and an omission describe different money. One total would describe
    neither, and it is exactly the kind of number that ends up in a letter."""
    extra = BASE + (("INV-004", "2025-03-01", "300000000000003", 8000.0, 1200.0),)
    changed = extra[:1] + (("INV-002", "2025-01-20", "300000000000003", 2000.0, 340.0),) \
        + extra[2:]
    c = zr.compare(listing=rows(*BASE), zatca=rows(*changed))

    assert c.vat_at_stake("ZR-01") == 1200.0
    assert c.vat_at_stake("ZR-03") == 40.0

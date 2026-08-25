"""The VAT return against the taxpayer's own invoice registers.

Three numbers per box and no rule between them: what the listing itself totals, what the return
declares, and the gap. The tests that matter here are the ones about *not* stating something:

- an absent listing is a missing document, never a difference the size of the whole box;
- an insight is written only when there is something behind it;
- only the ZATCA line claims particular invoices, because only it can.
"""
from __future__ import annotations

import io

import pytest

pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")

CASE = "CASE-2025-0481"          # the seeded case: a sales listing, a return, a ZATCA extract

SALES_CSV = (
    b"invoice_date,invoice_number,customer_name,taxable_amount,vat_amount\n"
    b"2025-01-14,INV-R1,Buyer A,100000.00,15000.00\n"
    b"2025-02-03,INV-R2,Buyer B,200000.00,30000.00\n"
    b"2025-03-19,INV-R3,Buyer C,60000.00,9000.00\n"
)


@pytest.fixture(scope="module")
def api(request):
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def own_case(api) -> str:
    """A case of this module's own — these tests file documents, which changes the evidence."""
    r = api.post("/api/cases", json={
        "period_from": "2025-01-01", "period_to": "2025-03-31",
        "creation_reason": "Register tests",
        "taxpayer": {"name": "Register Fixture Co.",
                     "vat_registration_number": "391100220099009"},
    })
    assert r.status_code == 200, r.text
    return r.json()["case_id"]


def regs(api, case: str) -> dict:
    r = api.get(f"/api/cases/{case}/registers")
    assert r.status_code == 200, r.text
    return {x["direction"]: x for x in r.json()["registers"]}


# ------------------------------------------------------------------ the arithmetic
def test_the_register_total_is_the_listings_own_vat_column(api, own_case):
    """Summed row by row, with no rule acting on it — what an auditor would get by hand."""
    api.post(f"/api/cases/{own_case}/threads", json={"subject": "Opening request"})
    r = api.post(f"/api/cases/{own_case}/documents",
                 files={"file": ("Sales_Listing.csv", io.BytesIO(SALES_CSV), "text/csv")})
    assert r.status_code == 200, r.text

    sale = regs(api, own_case)["sale"]
    assert sale["comparable"] is True
    assert sale["register_total"] == 54000.0, "15,000 + 30,000 + 9,000, and nothing else"
    assert sale["invoice_count"] == 3
    assert sale["difference"] == round(sale["register_total"] - sale["declared"], 2)


def test_every_row_of_the_register_is_available_behind_the_figure(api, own_case):
    """The figure is only useful if the auditor can open what is under it."""
    sale = regs(api, own_case)["sale"]
    assert len(sale["invoices"]) == 3
    assert round(sum(i["tax_amount"] for i in sale["invoices"]), 2) == sale["register_total"]
    for inv in sale["invoices"]:
        assert inv["uuid"], "a row the auditor cannot find in their own sheet is not evidence"
        assert inv["document"], "and it says which file it came from"


def test_the_seeded_case_sets_its_listing_against_its_own_return(api):
    sale = regs(api, CASE)["sale"]
    assert sale["comparable"] is True
    assert sale["declared"] > 0, "the seeded case has a filed return to compare against"
    assert sale["difference"] == round(sale["register_total"] - sale["declared"], 2)
    assert sale["risk"] == "under-declared"
    assert "under-declared" in sale["risk_label"]


# ------------------------------------------------------------------ what it refuses to say
def test_no_listing_is_a_missing_document_not_a_discrepancy(api):
    """The defect this exists to stop.

    Subtracting an absent listing from a declared figure reports the whole box as a
    discrepancy — SAR 150,000 "over-claimed" because nobody has uploaded the purchases
    analysis yet. That is a finding fabricated out of a missing file, and it is the same rule
    the ZATCA matcher enforces: one side is not a comparison.
    """
    purchase = regs(api, CASE)["purchase"]
    assert purchase["comparable"] is False
    assert purchase["declared"] > 0, "the return does claim input VAT"
    assert purchase["difference"] == 0.0, "but there is nothing to set against it"
    assert purchase["risk"] == "no-register"
    assert purchase["insights"] == []
    assert "missing document" in purchase["not_comparable_note"]


def test_only_the_zatca_line_claims_particular_invoices(api):
    """A difference against one declared figure cannot be pinned on particular rows.

    Invoices the Authority holds and the listing omits are the exception: those are named
    records carrying named amounts, so that line — and only that line — hands over invoices.
    """
    sale = regs(api, CASE)["sale"]
    assert sale["insights"], "the seeded case has something to say about its difference"
    for i in sale["insights"]:
        if i["invoices"]:
            assert i["key"] == "zatca-omitted", \
                f"{i['key']} claims invoices it cannot actually attribute"
            assert i["amount"] > 0
            assert i["count"] == len(i["invoices"])


def test_an_insight_with_nothing_behind_it_is_not_written(api, own_case):
    """A panel that always finds four reasons teaches an auditor to stop reading it."""
    keys = {i["key"] for i in regs(api, own_case)["sale"]["insights"]}
    assert "zatca-omitted" not in keys, "no dataset is loaded on this case"
    assert "stated-total" not in keys, "this listing carries no stated total to disagree with"


def test_a_case_with_nothing_on_it_compares_neither_box(api):
    r = api.post("/api/cases", json={
        "period_from": "2025-01-01", "period_to": "2025-03-31",
        "creation_reason": "Empty register case",
        "taxpayer": {"name": "Empty Register Co.",
                     "vat_registration_number": "391100221010010"},
    })
    empty = r.json()["case_id"]
    for reg in regs(api, empty).values():
        assert reg["comparable"] is False
        assert reg["insights"] == []


def test_an_unknown_case_is_a_404(api):
    assert api.get("/api/cases/NOPE-1/registers").status_code == 404


# ------------------------------------------------------------------ the loop back
def test_a_round_raised_from_here_says_it_was_raised_from_here(api, own_case):
    """An enquiry opened off a register insight that files itself as an opening request tells
    the auditor who lands on it the wrong story about their own case."""
    r = api.post(f"/api/cases/{own_case}/threads",
                 json={"subject": "Sales register — period not fully covered",
                       "origin": "investigation-request"})
    assert r.status_code == 200, r.text
    latest = r.json()["threads"][-1]
    assert latest["origin"] == "investigation-request"
    assert latest["subject"].startswith("Sales register")


def test_an_unrecognised_origin_is_refused(api, own_case):
    assert api.post(f"/api/cases/{own_case}/threads",
                    json={"subject": "x", "origin": "whatever"}).status_code == 422

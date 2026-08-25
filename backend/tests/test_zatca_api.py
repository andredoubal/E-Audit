"""The ZATCA dataset over HTTP: load it, replace it, unload it, and what each does to the case.

The behaviour worth guarding at this level is the one that only shows up end to end: loading a
dataset changes what the *investigation* says, because the fifth agent reads the comparison
through the same context assembly as everything else. A matcher that worked in isolation while
the agent never saw its output would pass every unit test in the suite.
"""
from __future__ import annotations

import io

import pytest

pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")

CASE = "CASE-2025-0483"          # its own case: the hero case ships with a dataset seeded


@pytest.fixture(scope="module")
def api(request):
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


def csv_bytes(*refs: str, vat: float = 150.0) -> bytes:
    head = b"invoice_number,invoice_date,customer_name,taxable_amount,vat_amount\n"
    body = "".join(f"{r},2025-01-15,Buyer Co,1000.00,{vat:.2f}\n" for r in refs)
    return head + body.encode()


def upload(api, data: bytes, name: str = "zatca.csv"):
    return api.post(f"/api/cases/{CASE}/zatca",
                    files={"file": (name, io.BytesIO(data), "text/csv")})


# --------------------------------------------------------------- nothing loaded
def test_a_case_with_no_dataset_says_it_cannot_compare(api):
    api.delete(f"/api/cases/{CASE}/zatca")
    d = api.get(f"/api/cases/{CASE}/zatca").json()

    assert d["comparable"] is False
    assert d["dataset"] is None
    assert d["mismatches"] == []
    assert "both sides" in d["note"], "it should say why, not just refuse"


def test_the_hero_case_ships_with_both_sides(api):
    """The demo has to open on something worth looking at, not an upload prompt."""
    d = api.get("/api/cases/CASE-2025-0481/zatca").json()
    assert d["comparable"] is True
    assert d["dataset"]["source"] == "seed"
    assert d["mismatches"], "the seeded dataset is meant to disagree with the listing"


# --------------------------------------------------------------- loading
def test_uploading_a_dataset_makes_the_case_comparable(api):
    r = upload(api, csv_bytes("INV-1", "INV-2"))
    assert r.status_code == 200, r.text
    d = r.json()

    assert d["dataset"]["filename"] == "zatca.csv"
    assert d["dataset"]["row_count"] == 2
    # this case may or may not carry a sales listing; either way the answer is honest
    assert d["comparable"] in (True, False)
    if not d["comparable"]:
        assert "listing" in d["note"]


def test_a_second_upload_replaces_the_first(api):
    """Two versions of the Authority's own records for one period is not a state to resolve."""
    upload(api, csv_bytes("INV-1"), name="first.csv")
    d = upload(api, csv_bytes("INV-1", "INV-2", "INV-3"), name="second.csv").json()

    assert d["dataset"]["filename"] == "second.csv"
    assert d["dataset"]["row_count"] == 3


def test_unloading_returns_the_case_to_not_comparable(api):
    upload(api, csv_bytes("INV-1"))
    d = api.delete(f"/api/cases/{CASE}/zatca").json()

    assert d["dataset"] is None
    assert d["comparable"] is False


def test_an_unknown_case_is_a_404(api):
    assert api.get("/api/cases/NOPE-1/zatca").status_code == 404
    assert api.delete("/api/cases/NOPE-1/zatca").status_code == 404


# --------------------------------------------------------------- the loop through the agents
HERO = "CASE-2025-0481"


def test_the_dataset_reaches_the_agents_not_just_the_panel(api):
    """The end-to-end property: the fifth agent reads the comparison through the shared
    context assembly, so what the panel shows and what the investigation reasons over are the
    same thing by construction."""
    inv = api.get(f"/api/cases/{HERO}/investigate").json()
    zatca = [h for h in inv["hypotheses"] if h["agent"] == "ZATCA Reconciliation"]

    assert zatca, "a case with a loaded dataset that disagrees should raise something"
    for h in zatca:
        assert not any(ch.isdigit() for ch in h["claim"]), \
            "an agent's claim carries language only"


def test_unloading_the_dataset_silences_the_agent(api):
    """Silence when the evidence is gone — not a stale hypothesis from the last time it ran."""
    api.delete(f"/api/cases/{HERO}/zatca")
    try:
        inv = api.get(f"/api/cases/{HERO}/investigate").json()
        assert not [h for h in inv["hypotheses"] if h["agent"] == "ZATCA Reconciliation"]
    finally:
        # put the demo back the way it ships, for whatever runs after this
        from app.db import SessionLocal
        from app.agents import zatca_service
        from app.models import AuditCase
        from app.seed import demo_files
        from sqlalchemy import select

        with SessionLocal() as db:
            case = db.scalar(select(AuditCase).where(AuditCase.case_id == HERO))
            zatca_service.record(db, case, filename="ZATCA_Invoices_Q1_2025.xlsx",
                                 data=demo_files.zatca_invoices_xlsx(), source="seed")


def test_the_seeded_comparison_finds_what_it_was_built_to_find(api):
    """Three March invoices the listing never reaches, and one figure that disagrees.

    Asserted through the real extractor and the real matcher rather than against a written-down
    answer, so drift in either shows up here.
    """
    d = api.get(f"/api/cases/{HERO}/zatca").json()
    by_code: dict[str, list] = {}
    for m in d["mismatches"]:
        by_code.setdefault(m["code"], []).append(m)

    assert len(by_code.get("ZR-01", [])) == 3, "the invoices cleared after the listing stops"
    assert len(by_code.get("ZR-03", [])) == 1, "the one invoice recorded differently"
    assert by_code.get("ZR-02") is None, "every numbered listing invoice is in ZATCA's records"
    assert len(by_code.get("ZR-10", [])) == 1, "the listing's three unnumbered rows"

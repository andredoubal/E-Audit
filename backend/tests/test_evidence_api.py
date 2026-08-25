"""The evidence stage over HTTP: what is on the case, and the auditor's right to overrule it.

The override is the part worth testing hardest. A classifier that cannot be corrected is worse
than the filename matching it replaced — a filename at least behaves predictably — so the
correction has to reach every consumer, survive a reload, keep what the profiler had said
beside it, and be reversible.
"""
from __future__ import annotations

import io

import pytest

pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")

PURCHASES = (
    b"invoice_date,invoice_number,supplier_name,taxable_amount,vat_amount\n"
    b"2025-01-09,PI-1,Vendor A,40000.00,6000.00\n"
    b"2025-02-22,PI-2,Vendor B,12000.00,1800.00\n"
)
AMBIGUOUS = (
    b"txn_date,ref,amount_a,amount_b\n"
    b"2025-01-09,A1,100,15\n"
)


@pytest.fixture(scope="module")
def api(request):
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def case(api) -> str:
    """This module files documents, so it works a case of its own."""
    r = api.post("/api/cases", json={
        "period_from": "2025-01-01", "period_to": "2025-03-31",
        "creation_reason": "Evidence API tests",
        "taxpayer": {"name": "Evidence API Co.",
                     "vat_registration_number": "391100221212012"},
    })
    assert r.status_code == 200, r.text
    cid = r.json()["case_id"]
    api.post(f"/api/cases/{cid}/threads", json={"subject": "Opening request"})
    return cid


def evidence(api, case: str) -> dict:
    r = api.get(f"/api/cases/{case}/evidence")
    assert r.status_code == 200, r.text
    return r.json()


def upload(api, case: str, name: str, data: bytes):
    r = api.post(f"/api/cases/{case}/documents",
                 files={"file": (name, io.BytesIO(data), "text/csv")})
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ reading the case
def test_a_case_with_nothing_on_it_has_nothing_to_profile(api, case):
    d = evidence(api, case)
    assert d["datasets"] == []
    assert d["available_types"] == []
    assert d["by_workstream"] == {"sales": [], "purchases": []}


def test_a_file_is_classified_from_its_contents_over_http(api, case):
    """The filename says nothing about purchases; the supplier column says everything."""
    upload(api, case, "attachment_2.csv", PURCHASES)
    d = evidence(api, case)

    p = next(x for x in d["datasets"] if x["filename"] == "attachment_2.csv")
    assert p["dataset_type"] == "purchase-register"
    assert p["workstream"] == "purchases"
    assert p["confidence"] == "high"
    assert p["record_count"] == 2
    assert p["date_min"] == "2025-01-09" and p["date_max"] == "2025-02-22"
    assert "purchase-register" in d["available_types"]
    assert "attachment_2.csv" in d["by_workstream"]["purchases"]
    assert "attachment_2.csv" not in d["by_workstream"]["sales"]


def test_a_file_it_cannot_read_is_surfaced_for_attention_rather_than_guessed(api, case):
    upload(api, case, "attachment_3.csv", AMBIGUOUS)
    d = evidence(api, case)

    p = next(x for x in d["datasets"] if x["filename"] == "attachment_3.csv")
    assert p["dataset_type"] == "unknown"
    assert p["why"], "an unreadable file still has to say why"
    assert "attachment_3.csv" in d["needs_attention"]["unclassified"]


def test_the_type_vocabulary_is_published_so_a_correction_has_something_to_choose_from(api, case):
    keys = {t["key"] for t in evidence(api, case)["known_types"]}
    assert {"sales-register", "purchase-register", "trial-balance", "general-ledger"} <= keys
    assert "unknown" not in keys, "'not classified' is a state, not something to choose"


# ------------------------------------------------------------------ the override
def test_the_auditor_can_overrule_the_classifier(api, case):
    r = api.put(f"/api/cases/{case}/evidence/override", json={
        "filename": "attachment_3.csv", "dataset_type": "trial-balance",
        "note": "It is the TB — the headers came out of the export tool unlabelled."})
    assert r.status_code == 200, r.text

    p = next(x for x in r.json()["datasets"] if x["filename"] == "attachment_3.csv")
    assert p["dataset_type"] == "trial-balance"
    assert p["workstream"] == "both", "the workstream follows the type unless it is given"
    assert p["confidence"] == "confirmed", "a person looked, which beats any column heuristic"
    assert p["overridden"] is True
    assert "export tool" in p["why"]


def test_the_override_survives_a_reload_and_keeps_the_original_reading_beside_it(api, case):
    p = next(x for x in evidence(api, case)["datasets"]
             if x["filename"] == "attachment_3.csv")
    assert p["dataset_type"] == "trial-balance"
    assert p["read_as"]["dataset_type"] == "unknown", \
        "an override nobody can compare against the original reading is not reviewable"


def test_an_override_moves_the_file_between_workstreams(api, case):
    api.put(f"/api/cases/{case}/evidence/override", json={
        "filename": "attachment_2.csv", "dataset_type": "sales-register",
        "note": "Mis-headed by the taxpayer's system; these are customers."})
    d = evidence(api, case)
    assert "attachment_2.csv" in d["by_workstream"]["sales"]
    assert "attachment_2.csv" not in d["by_workstream"]["purchases"]


def test_clearing_an_override_restores_what_the_profiler_read(api, case):
    """A ruling you cannot take back is one an auditor will not make."""
    api.put(f"/api/cases/{case}/evidence/override",
            json={"filename": "attachment_2.csv", "dataset_type": "", "workstream": ""})
    p = next(x for x in evidence(api, case)["datasets"]
             if x["filename"] == "attachment_2.csv")
    assert p["dataset_type"] == "purchase-register"
    assert p["overridden"] is False
    assert p["confidence"] == "high"


def test_an_unknown_dataset_type_is_refused(api, case):
    r = api.put(f"/api/cases/{case}/evidence/override",
                json={"filename": "attachment_2.csv", "dataset_type": "vibes"})
    assert r.status_code == 422


def test_an_override_for_a_file_not_on_the_case_is_a_404(api, case):
    r = api.put(f"/api/cases/{case}/evidence/override",
                json={"filename": "never_uploaded.csv", "dataset_type": "sales-register"})
    assert r.status_code == 404


def test_an_unknown_case_is_a_404(api):
    assert api.get("/api/cases/NOPE-1/evidence").status_code == 404


# ------------------------------------------------------------------ quality reaches the case
def test_a_blocking_quality_defect_is_raised_to_the_case_level(api, case):
    """A file whose VAT column cannot be read is not a file you can reconcile from, and that
    has to be visible without opening each dataset."""
    upload(api, case, "attachment_4.csv",
           b"invoice_date,invoice_number,customer_name,vat_amount\n"
           b"2025-01-14,INV-1,Buyer A,\n"
           b"2025-01-15,INV-2,Buyer B,\n")
    d = evidence(api, case)
    blocking = d["needs_attention"]["blocking_quality"]
    assert any(f["filename"] == "attachment_4.csv" for f in blocking), blocking

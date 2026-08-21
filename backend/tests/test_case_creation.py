"""Manual case creation — the only way a case exists in this PoC, since there is no live
risk-engine integration. `POST /cases` is exercised through the real HTTP layer, the same
way the rest of the acceptance suite is, because a check that only holds in Python but
returns 422 on the wire has not actually passed.

This is also the regression that matters most for `reporting/audit_report.py`: a case
created this way must show real taxpayer contact details, a real creation reason, and real
audit-team names, while every seeded/demo case must keep showing `[not held]` exactly as
before.
"""
from __future__ import annotations

import pytest

pytest.importorskip("httpx", reason="the API acceptance walk needs httpx for TestClient")


@pytest.fixture(scope="module")
def api(request):
    request.getfixturevalue("seeded")          # session-scoped seed, shared with the rest
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


def _body(**overrides) -> dict:
    body = {
        "period_from": "2025-01-01",
        "period_to": "2025-03-31",
        "creation_date": "2026-01-15",
        "creation_reason": "Internal referral",
        "audit_manager": "Fahad Al-Otaibi",
        "audit_supervisor": "Noura Al-Harbi",
        "audit_officer": "Khalid Al-Ghamdi",
        "taxpayer": {
            "name": "Najd Test Trading Co.",
            "vat_registration_number": "399988877700003",
            "ind_sector": "Wholesale trade",
            "economic_activities": [
                {"isic": "4690", "description": "Non-specialised wholesale trade", "primary": True}
            ],
            "contact_phone": "+966501234567",
            "contact_email": "finance@najd-test.example",
            "contact_address": "Al-Waha District, Riyadh, Saudi Arabia",
            "audited_before": True,
            "audited_before_note": "Closed 2023 desk audit, no finding.",
        },
    }
    body.update(overrides)
    return body


def test_create_case_with_a_fresh_taxpayer(api):
    r = api.post("/api/cases", json=_body())
    assert r.status_code == 200, r.text
    case_id = r.json()["case_id"]
    assert case_id.startswith("CASE-2026-")   # creation_date's year, not the period's

    got = api.get(f"/api/cases/{case_id}")
    assert got.status_code == 200
    assert got.json()["taxpayer"]["name"] == "Najd Test Trading Co."
    assert got.json()["taxpayer"]["vat_no"] == "399988877700003"
    assert got.json()["status"] == "referred"


def test_case_id_auto_generation_does_not_collide(api):
    r1 = api.post("/api/cases", json=_body(taxpayer={
        **_body()["taxpayer"], "vat_registration_number": "399988877700011"}))
    r2 = api.post("/api/cases", json=_body(taxpayer={
        **_body()["taxpayer"], "vat_registration_number": "399988877700022"}))
    id1, id2 = r1.json()["case_id"], r2.json()["case_id"]
    assert id1 != id2
    # sequential within the same creation year
    seq1, seq2 = int(id1.rsplit("-", 1)[1]), int(id2.rsplit("-", 1)[1])
    assert seq2 == seq1 + 1


def test_reusing_an_existing_vat_number_updates_the_taxpayer_not_duplicates_it(api):
    vat = "399988877700033"
    r1 = api.post("/api/cases", json=_body(taxpayer={**_body()["taxpayer"], "vat_registration_number": vat}))
    assert r1.status_code == 200
    updated = {**_body()["taxpayer"], "vat_registration_number": vat, "name": "Najd Test Trading Co. (renamed)"}
    r2 = api.post("/api/cases", json=_body(taxpayer=updated))
    assert r2.status_code == 200
    assert r1.json()["case_id"] != r2.json()["case_id"]   # two cases

    from sqlalchemy import select, func
    from app.db import SessionLocal
    from app.models import Taxpayer

    db = SessionLocal()
    try:
        n = db.scalar(select(func.count()).select_from(Taxpayer)
                      .where(Taxpayer.vat_registration_number == vat))
        assert n == 1   # one taxpayer row, not two
        tp = db.scalar(select(Taxpayer).where(Taxpayer.vat_registration_number == vat))
        assert tp.name == "Najd Test Trading Co. (renamed)"   # the second call's values won
    finally:
        db.close()


def test_missing_required_fields_is_rejected(api):
    bad = _body(taxpayer={**_body()["taxpayer"], "name": "", "vat_registration_number": "399988877700099"})
    r = api.post("/api/cases", json=bad)
    assert r.status_code == 422

    bad_period = _body(period_from="2025-06-30", period_to="2025-01-01",
                       taxpayer={**_body()["taxpayer"], "vat_registration_number": "399988877700088"})
    r2 = api.post("/api/cases", json=bad_period)
    assert r2.status_code == 422


def test_a_manually_created_case_shows_real_values_in_the_audit_report(api):
    r = api.post("/api/cases", json=_body(taxpayer={
        **_body()["taxpayer"], "vat_registration_number": "399988877700044"}))
    case_id = r.json()["case_id"]

    recon = api.get(f"/api/cases/{case_id}/reconcile").json()
    inv = api.get(f"/api/cases/{case_id}/investigate").json()
    report = api.get(f"/api/cases/{case_id}/audit-report").json()

    fields = {f["label"]: f for s in report["sections"] for f in s["fields"]}
    assert fields["Taxpayer contact details"]["held"] is True
    assert "finance@najd-test.example" in fields["Taxpayer contact details"]["value"]
    assert fields["Case Creation Reason"]["value"] == "Internal referral"
    assert fields["Audit Manager"]["value"] == "Fahad Al-Otaibi"
    assert fields["Audit Supervisor"]["value"] == "Noura Al-Harbi"
    assert fields["Audit Officer"]["value"] == "Khalid Al-Ghamdi"


def test_a_seeded_case_still_shows_not_held_and_risk_engine(api):
    """The regression that matters most: nothing above should touch an untouched demo case."""
    report = api.get("/api/cases/CASE-2025-0481/audit-report").json()
    fields = {f["label"]: f for s in report["sections"] for f in s["fields"]}
    assert fields["Taxpayer contact details"]["held"] is False
    assert fields["Taxpayer contact details"]["value"] == "[not held]"
    assert fields["Audit Manager"]["held"] is False
    assert fields["Audit Manager"]["value"] == "[not held]"
    # the pre-existing fallback for a case with no stated reason — unchanged behaviour
    assert fields["Case Creation Reason"]["value"] == "Risk Engine"

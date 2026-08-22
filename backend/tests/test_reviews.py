"""Approve or challenge what the application concluded.

Every check here is defensible and every one of them can be wrong. The property that makes the
feature worth having rather than decorative: **a challenge changes something.** A challenged gap
stops being chased, because an auditor who has recorded that the "missing" column is present
under a different header must not then watch the Authority write to the taxpayer asking for it.

The gap itself is never deleted. The file has to show both what the checker found and why a
person overrode it.
"""
from __future__ import annotations

import io

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

KIND = "completeness-item"


@pytest.fixture(scope="module")
def api(request):
    pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def own_case(api) -> str:
    """A case of this module's own: a review changes what the chase asks for, so working the
    shared seeded case would rewrite a letter other tests assert against."""
    from email.message import EmailMessage

    from app.seed.demo_files import sales_analysis_xlsx

    case = api.post("/api/cases", json={
        "period_from": "2025-01-01", "period_to": "2025-03-31",
        "creation_reason": "Review tests",
        "taxpayer": {"name": "Review Co.", "vat_registration_number": "391100220077001"},
    }).json()["case_id"]

    m = EmailMessage()
    m["Subject"] = "Information request — VAT Q1 2025"
    m["From"] = "vat.audit@zatca.gov.sa"
    m["To"] = "finance@taxpayer.example"
    m["Date"] = "Mon, 14 Apr 2025 09:12:00 +0300"
    m.set_content("Please provide a detailed sales analysis and the trial balance.")
    api.post(f"/api/cases/{case}/threads/email",
             files={"file": ("request.eml", m.as_bytes(), "message/rfc822")})
    api.post(f"/api/cases/{case}/documents",
             files={"file": ("Sales_Analysis_Q1_2025.xlsx", sales_analysis_xlsx(),
                             "application/vnd.openxmlformats-officedocument"
                             ".spreadsheetml.sheet")})
    return case


def rows(api, case: str) -> list[dict]:
    r = api.get(f"/api/cases/{case}/requests")
    assert r.status_code == 200, r.text
    return r.json()["assessment"]["items"]


def outstanding_row(api, case: str) -> dict:
    row = next((i for i in rows(api, case) if i["state"] != "received"), None)
    if row is None:
        pytest.skip("this case produced no outstanding row to review")
    return row


def review(api, case: str, key: str, verdict: str, note: str = ""):
    return api.put(f"/api/cases/{case}/reviews",
                   json={"item_kind": KIND, "item_key": key, "verdict": verdict, "note": note})


# ------------------------------------------------------------------------ the basics
def test_a_row_starts_unreviewed_and_carries_a_stable_key(api, own_case):
    row = outstanding_row(api, own_case)
    assert row["review"] is None
    assert row["key"] and "::" in row["key"], \
        "keyed by what it is, not by a row id that changes on every recomputation"
    assert row["chased"] is True


def test_approving_is_recorded(api, own_case):
    row = outstanding_row(api, own_case)
    assert review(api, own_case, row["key"], "approved").status_code == 200

    after = next(i for i in rows(api, own_case) if i["key"] == row["key"])
    assert after["review"]["verdict"] == "approved"
    assert after["chased"] is True, "agreeing with a gap does not make it go away"


def test_a_challenge_needs_a_reason(api, own_case):
    """"The auditor disagreed" with nothing after it is not something anyone can act on later,
    least of all the auditor coming back to it in a month."""
    row = outstanding_row(api, own_case)
    assert review(api, own_case, row["key"], "challenged").status_code == 422


def test_a_challenged_row_keeps_its_state_and_stops_being_chased(api, own_case):
    """The point of the feature. The check still found what it found; a person has said it is
    wrong; the file shows both, and the letter stops asking."""
    row = outstanding_row(api, own_case)
    before = row["state"]
    assert review(api, own_case, row["key"], "challenged",
                  "The column is there, headed 'VAT no.'").status_code == 200

    after = next(i for i in rows(api, own_case) if i["key"] == row["key"])
    assert after["state"] == before, "the finding is not rewritten"
    assert after["review"]["verdict"] == "challenged"
    assert after["review"]["note"], "with the reason beside it"
    assert after["chased"] is False


def test_the_chase_letter_stops_asking_for_a_challenged_item(api, own_case):
    """The letter this feature exists to stop: the Authority writing to a taxpayer for a
    document its own auditor has said was already supplied."""
    challenged = next((i for i in rows(api, own_case)
                       if (i["review"] or {}).get("verdict") == "challenged"), None)
    if challenged is None:
        pytest.skip("nothing challenged on this case")

    r = api.get(f"/api/cases/{own_case}/followup")
    if r.status_code == 409:
        return          # nothing left to chase at all, which is the stronger version of this
    assert challenged["label"] not in r.json()["text"]


def test_withdrawing_a_review_puts_the_row_back(api, own_case):
    challenged = next(i for i in rows(api, own_case)
                      if (i["review"] or {}).get("verdict") == "challenged")
    assert review(api, own_case, challenged["key"], "").status_code == 200

    after = next(i for i in rows(api, own_case) if i["key"] == challenged["key"])
    assert after["review"] is None and after["chased"] is True


def test_the_summary_counts_what_was_reviewed(api, own_case):
    row = outstanding_row(api, own_case)
    review(api, own_case, row["key"], "challenged", "Not right.")
    summary = api.get(f"/api/cases/{own_case}/requests").json()["assessment"]["summary"]
    assert summary["challenged"] >= 1


# --------------------------------------------------------------------------- refusals
def test_an_unknown_kind_is_refused(api, own_case):
    r = api.put(f"/api/cases/{own_case}/reviews",
                json={"item_kind": "something-else", "item_key": "x", "verdict": "approved"})
    assert r.status_code == 422


def test_an_unknown_verdict_is_refused(api, own_case):
    row = outstanding_row(api, own_case)
    assert review(api, own_case, row["key"], "maybe").status_code == 422


def test_an_unknown_case_is_a_404(api):
    r = api.put("/api/cases/NOPE-1/reviews",
                json={"item_kind": KIND, "item_key": "x", "verdict": "approved"})
    assert r.status_code == 404


def test_reviews_are_listed_per_kind(api, own_case):
    r = api.get(f"/api/cases/{own_case}/reviews/{KIND}")
    assert r.status_code == 200
    assert isinstance(r.json()["reviews"], dict)
    assert api.get(f"/api/cases/{own_case}/reviews/zatca-mismatch").json()["reviews"] == {}, \
        "one kind's reviews do not leak into another's"

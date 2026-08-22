"""The report is written from what the auditor accepted, not from what the engine confirmed.

This is the distinction the whole design rests on, so it is tested at the boundary that
matters: the rendered report itself. An adjudicated hypothesis is a proposal that survived
testing. It becomes a finding when a person says so — and until then the report must say that
no finding was established, which is a correct report of an unfinished audit rather than a
broken one.

The trace tests guard the other half: a report sentence has to lead back to the hypothesis,
the evidence and the decision behind it. A report that states a conclusion no one can follow
back to its source is not something an auditor can defend.
"""
from __future__ import annotations

import pytest

pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")

CASE = "CASE-2025-0481"


@pytest.fixture(scope="module")
def api(request):
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


def _fields(api, case_id=CASE) -> dict:
    r = api.get(f"/api/cases/{case_id}/audit-report")
    assert r.status_code == 200, r.text
    return {f["label"]: f for s in r.json()["sections"] for f in s["fields"]}


def _some_hypothesis_with_an_outcome(api, case_id=CASE) -> str:
    inv = api.get(f"/api/cases/{case_id}/investigation").json()
    return next(h["hypothesis_id"] for h in inv["hypotheses"] if h["outcome_code"])


def test_a_case_with_nothing_accepted_reports_no_finding(api):
    """Not an error state — an accurate report of an audit whose conclusion is not yet drawn.

    Deliberately a case of its own: the suite shares one seeded database, and a test that
    asserts "nothing has been accepted" is only meaningful on a case no other test has ruled
    on.
    """
    # Found rather than hardcoded: the point is a case the engine has something to say about
    # and the auditor has not yet ruled on, and which case that is depends on the seed.
    untouched = ""
    for row in api.get("/api/cases").json():
        cid = row["case_id"]
        if cid == CASE:
            continue
        eng = api.get(f"/api/cases/{cid}/investigate").json()
        if not any(a["status"] == "confirmed" for a in eng["adjudications"]):
            continue
        stored = api.get(f"/api/cases/{cid}/investigation").json()
        if any(h["decision"] for h in stored["hypotheses"]):
            continue
        untouched = cid
        break
    assert untouched, "no seeded case has confirmed hypotheses and no auditor decisions"

    found = _fields(api, untouched)["Audit Findings"]
    assert "No finding was established" in found["value"], \
        "the engine confirmed hypotheses here, but none is a finding until the auditor says so"
    assert found["trace"] == []


def test_accepting_a_hypothesis_puts_it_in_the_report(api):
    hid = _some_hypothesis_with_an_outcome(api)
    r = api.post(f"/api/cases/{CASE}/hypotheses/{hid}/decision",
                 json={"decision": "accepted", "comment": "Reviewed against the listing."})
    assert r.status_code == 200, r.text

    found = _fields(api)["Audit Findings"]
    assert "No finding was established" not in found["value"]
    assert found["trace"], "an accepted finding must carry a trace"
    entry = next(t for t in found["trace"] if t["hypothesis_id"] == hid)
    assert entry["source"] == "agent-proposed-auditor-confirmed"
    assert entry["agent"], "the trace names which agent proposed it"
    assert entry["decided_at"], "and when the auditor confirmed it"


def test_a_rejected_hypothesis_stays_out_of_the_report(api):
    """Rejecting is not the same as never having been raised: it stays on the case file."""
    inv = api.get(f"/api/cases/{CASE}/investigation").json()
    decided = {h["hypothesis_id"] for h in inv["hypotheses"] if h["decision"]}
    hid = next(h["hypothesis_id"] for h in inv["hypotheses"]
               if h["outcome_code"] and h["hypothesis_id"] not in decided)

    api.post(f"/api/cases/{CASE}/hypotheses/{hid}/decision",
             json={"decision": "rejected", "comment": "Explained by timing."})

    found = _fields(api)["Audit Findings"]
    assert all(t["hypothesis_id"] != hid for t in found["trace"]), \
        "a rejected hypothesis must not reach the report"

    # but it is still on the investigation, with the auditor's reason recorded
    after = api.get(f"/api/cases/{CASE}/investigation").json()
    kept = next(h for h in after["hypotheses"] if h["hypothesis_id"] == hid)
    assert kept["decision"]["decision"] == "rejected"
    assert kept["decision"]["comment"] == "Explained by timing."


def test_the_trace_leads_back_to_the_evidence_that_was_tested(api):
    """Report statement -> hypothesis -> the document and rows the adjudicator actually read."""
    found = _fields(api)["Audit Findings"]
    entry = next(t for t in found["trace"] if t["carries_amount"])

    assert entry["statement"], "the trace names the sentence it explains"
    assert entry["why"], "and why the hypothesis was raised in the first place"
    assert entry["explanation"], "and the engine's account of the verdict"
    assert entry["basis"], "and the evidence basis the amount is counted against"
    assert entry["evidence"]["document"], "and the document behind it"
    assert entry["evidence"]["rows"], "and how much of it was tested"
    # the regulatory leg: the provision the statement rests on, never silently absent
    reg = entry["regulatory"]
    assert reg["state"] in ("found", "needs-validation", "not-found")
    if reg["state"] != "not-found":
        assert reg["label"].startswith("Article "), "a citation names its article"
        assert reg["establishes"], "and what that article establishes"
        assert reg["text"], "and carries the article's own words, so it can be checked"
        assert entry["reads_as"].startswith(entry["statement"].lstrip("- ")[:30]), \
            "the finding reads as evidence, then basis, then consequence"


def test_an_auditor_authored_finding_reaches_the_report_in_the_auditors_own_words(api):
    """The agents cover what they have tests for. Anything else must still be recordable —
    and must not be dressed in the Authority's standard phrasing as though an agent found it."""
    statement = "Export evidence was not held for a supply treated as zero-rated."
    r = api.post(f"/api/cases/{CASE}/auditor-findings",
                 json={"statement": statement, "amount": 4200.0,
                       "note": "Seen during the line review."})
    assert r.status_code == 200, r.text

    found = _fields(api)["Audit Findings"]
    assert statement in found["value"]
    entry = next(t for t in found["trace"] if t["statement"].endswith(statement)
                 or statement in t["statement"])
    assert entry["source"] == "auditor-authored"
    assert entry["agent"] == "Auditor"
    assert entry["hypothesis_id"] == "", "there is no agent hypothesis behind it"


def test_the_word_and_printable_exports_still_render(api):
    """The export path is unchanged by the trace: `render.py` ignores it."""
    doc = api.get(f"/api/cases/{CASE}/audit-report.doc")
    assert doc.status_code == 200
    assert doc.headers["content-type"].startswith("application/msword")
    assert "attachment" in doc.headers.get("content-disposition", "")
    assert b"<html" in doc.content.lower()

    html = api.get(f"/api/cases/{CASE}/audit-report.html")
    assert html.status_code == 200
    assert b"Audit report" in html.content


def test_exposure_still_counts_one_excess_once(api):
    """Several outcomes can describe one excess. Accepting more than one must not multiply it.

    This is the arithmetic `findings.exposure` exists to protect, re-checked here because the
    report now assembles its findings from a different source than the engine's own list.
    """
    inv = api.get(f"/api/cases/{CASE}/investigation").json()
    # every hypothesis resting on the same evidence basis as the one already accepted
    accepted = [h for h in inv["hypotheses"]
                if h["decision"] and h["decision"]["decision"] == "accepted"]
    assert accepted, "the earlier test should have left one accepted"
    basis = (accepted[0]["detail"] or {}).get("basis")
    siblings = [h for h in inv["hypotheses"]
                if h["outcome_code"] and (h["detail"] or {}).get("basis") == basis
                and not h["decision"]]
    if not siblings:
        pytest.skip("this case has no second reading of the same evidence")

    before = _fields(api)["Assessment"]["value"]
    for h in siblings:
        api.post(f"/api/cases/{CASE}/hypotheses/{h['hypothesis_id']}/decision",
                 json={"decision": "accepted", "comment": "Same excess, another reading."})
    after = _fields(api)["Assessment"]["value"]

    def _total(text: str) -> str:
        return next((ln for ln in text.split("\n") if "Total proposed adjustment" in ln), "")

    assert _total(before) == _total(after), \
        "accepting an alternative characterisation of the same evidence must not add money"

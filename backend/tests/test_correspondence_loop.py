"""The loop: an investigation that needs evidence asks for it, and resumes when it arrives.

An investigation that cannot settle a hypothesis on what it holds is not finished, and must not
present itself as finished. It should say what it needs. These tests walk that: request
information from a hypothesis, watch the thread open carrying the hypothesis id, upload the
answer against it, and confirm the investigation offers to re-test *that* hypothesis rather
than simply re-running everything.

The thread rule under test throughout: one open at a time, closed ones kept. A document filed
against the wrong enquiry is a completeness check answering the wrong question, so the
association has to be unambiguous — while the history still has to survive.
"""
from __future__ import annotations

import io

import pytest

pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")

CASE = "CASE-2025-0486"          # its own case: threads are per-case state other tests mutate


@pytest.fixture(scope="module")
def api(request):
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


def _hypothesis(api) -> str:
    inv = api.get(f"/api/cases/{CASE}/investigation").json()
    assert inv["hypotheses"], "this case should raise something to ask about"
    return inv["hypotheses"][0]["hypothesis_id"]


def test_requesting_information_opens_a_thread_that_remembers_why(api):
    hid = _hypothesis(api)
    r = api.post(f"/api/cases/{CASE}/hypotheses/{hid}/request-info",
                 json={"note": "The trial balance for the period."})
    assert r.status_code == 200, r.text
    body = r.json()

    thread = body["thread"]["threads"][-1]
    assert thread["status"] == "open"
    assert thread["origin"] == "investigation-request"
    assert thread["origin_hypothesis_id"] == hid, \
        "the thread has to remember which hypothesis it exists to answer"

    # the draft went out as a message, marked as drafted rather than written by a person
    assert thread["messages"], "the request should be on the trail, not just generated"
    msg = thread["messages"][0]
    assert msg["direction"] == "outbound"
    assert msg["drafted_by"] in ("ai-drafted", "auditor")
    assert msg["body"].strip()


def test_the_letter_asks_rather_than_concludes(api):
    """The one letter most likely to be read as an accusation. It must not read as one."""
    inv = api.get(f"/api/cases/{CASE}/investigation").json()
    hid = next(h["hypothesis_id"] for h in inv["hypotheses"]
               if h["status"] == "pending-info")
    thread = api.get(f"/api/cases/{CASE}/threads").json()["threads"][-1]
    body = thread["messages"][0]["body"].lower()

    assert any(w in body for w in ("request", "please provide", "further information"))
    # no verdict language: nothing has been concluded at the point this goes out
    for banned in ("assessment is raised", "you have understated", "penalty"):
        assert banned not in body, f"a request for information must not say “{banned}”"
    assert hid  # the hypothesis is genuinely parked, not silently resolved


def test_the_hypothesis_is_parked_not_settled(api):
    """`pending-info` stops an unanswered question being read as a settled verdict."""
    inv = api.get(f"/api/cases/{CASE}/investigation").json()
    parked = [h for h in inv["hypotheses"] if h["status"] == "pending-info"]
    assert parked, "requesting information should park the hypothesis"
    assert parked[0]["needs_info_note"] == "The trial balance for the period."


def test_nothing_is_retestable_until_something_arrives(api):
    state = api.get(f"/api/cases/{CASE}/threads").json()
    assert state["retestable"] == [], \
        "a question that has not been answered is not evidence to re-test against"


def test_a_document_on_the_thread_makes_the_hypothesis_retestable(api):
    csv = (b"invoice_date,invoice_number,customer_name,taxable_amount,vat_amount\n"
           b"2025-01-15,INV-1,Acme,1000.00,150.00\n")
    r = api.post(f"/api/cases/{CASE}/documents",
                 files={"file": ("trial_balance.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code in (200, 409), r.text
    if r.status_code == 409:
        pytest.skip("this case has no issued request to upload against")

    state = api.get(f"/api/cases/{CASE}/threads").json()
    assert state["retestable"], "the answer arrived — the hypothesis should be re-testable"
    entry = state["retestable"][0]
    assert "trial_balance.csv" in entry["documents"]
    assert entry["note"], "and it should still say what was asked for"

    # the document is filed against the enquiry that asked for it, not merely against the case
    thread = state["threads"][-1]
    assert any(d["filename"] == "trial_balance.csv" for d in thread["documents"])


def test_re_running_the_investigation_settles_the_parked_hypothesis(api):
    """The loop closes: new evidence, re-adjudicated, and no longer waiting on anyone."""
    before = api.get(f"/api/cases/{CASE}/investigation").json()
    parked = [h["hypothesis_id"] for h in before["hypotheses"] if h["status"] == "pending-info"]
    if not parked:
        pytest.skip("nothing is parked on this case")

    after = api.post(f"/api/cases/{CASE}/investigation/run",
                     json={"trigger": "new-evidence"}).json()
    still = [h["hypothesis_id"] for h in after["hypotheses"] if h["status"] == "pending-info"]
    assert not set(parked) & set(still), \
        "a re-run against the new evidence should settle the question, not leave it pending"
    assert len(after["hypotheses"]) == len(before["hypotheses"]), \
        "and it should merge into the same rows rather than duplicating them"


def test_one_thread_is_open_at_a_time_and_the_rest_are_kept(api):
    """History without ambiguity: many closed enquiries, exactly one accepting documents."""
    api.post(f"/api/cases/{CASE}/threads", json={"subject": "A second enquiry"})
    state = api.get(f"/api/cases/{CASE}/threads").json()

    open_threads = [t for t in state["threads"] if t["status"] == "open"]
    assert len(open_threads) == 1, "exactly one thread may accept documents"
    assert len(state["threads"]) >= 2, "and the earlier enquiry is kept, not discarded"
    assert state["open_thread_id"] == open_threads[0]["id"]

    # the closed one keeps everything that happened on it
    closed = next(t for t in state["threads"] if t["status"] == "closed")
    assert closed["closed_at"]
    assert closed["messages"] or closed["documents"]


def test_a_taxpayer_reply_is_recorded_in_their_own_words(api):
    """Their account of their records is evidence of what they say, not of what is true."""
    reply = "The difference relates to credit notes issued in April, after the period end."
    r = api.post(f"/api/cases/{CASE}/threads/reply", json={"body": reply})
    assert r.status_code == 200, r.text

    thread = r.json()["threads"][-1]
    msg = thread["messages"][-1]
    assert msg["direction"] == "inbound"
    assert msg["drafted_by"] == "taxpayer"
    assert msg["body"] == reply, "kept verbatim — not summarised, not rewritten"

    assert api.post(f"/api/cases/{CASE}/threads/reply", json={"body": "   "}).status_code == 422


def test_requesting_information_for_an_unknown_hypothesis_is_a_404(api):
    r = api.post(f"/api/cases/{CASE}/hypotheses/NOPE-99/request-info", json={"note": "x"})
    assert r.status_code == 404


def test_the_auditors_note_reads_as_a_sentence_in_the_letter():
    """An auditor types a sentence; the letter puts it mid-sentence. It has to still read.

    "The trial balance as at 31 March 2025." dropped after "Please provide" gives
    "Please provide The trial balance as at 31 March 2025..", which is the sort of thing that
    makes a letter from a tax authority look unread before it was sent.
    """
    from app.agents.correspondence import _as_clause

    assert _as_clause("The trial balance as at 31 March 2025.") == \
        "the trial balance as at 31 March 2025"
    assert _as_clause("  the general ledger  ") == "the general ledger"
    # an acronym or a proper noun keeps its capitals
    assert _as_clause("VAT return copies for Q1.") == "VAT return copies for Q1"
    assert _as_clause("Sales_Analysis_Q1.xlsx") == "Sales_Analysis_Q1.xlsx"
    assert _as_clause("   ") == ""


def test_the_drafted_letter_reads_cleanly_with_an_auditors_note(api):
    """End to end: the note the auditor typed appears in the letter as running prose."""
    inv = api.get(f"/api/cases/{CASE}/investigation").json()
    candidates = [h for h in inv["hypotheses"] if h["status"] != "pending-info"]
    if not candidates:
        pytest.skip("everything on this case is already parked")

    api.post(f"/api/cases/{CASE}/hypotheses/{candidates[0]['hypothesis_id']}/request-info",
             json={"note": "The trial balance as at 31 March 2025."})
    thread = api.get(f"/api/cases/{CASE}/threads").json()["threads"][-1]
    body = thread["messages"][0]["body"]

    assert "provide The trial balance" not in body, "the note must not be dropped in raw"
    assert ".." not in body, "and must not leave a doubled full stop"


def test_a_reply_claiming_an_attachment_with_no_file_behind_it_is_flagged(api):
    """The silent failure: in the trail, a stripped attachment reads like an answered request.

    Both sides then wait — the auditor for a file the taxpayer believes they sent — and the round
    costs weeks. All the check claims is that the words and the files disagree.
    """
    api.post(f"/api/cases/{CASE}/threads", json={"subject": "Trial balance follow-up"})
    api.post(f"/api/cases/{CASE}/threads/reply",
             json={"body": "Please find attached the trial balance for the period."})

    state = api.get(f"/api/cases/{CASE}/threads").json()
    open_id = state["open_thread_id"]
    flagged = [m for m in state["missing_attachments"] if m["thread_id"] == open_id]
    assert flagged, "a reply that says 'attached' with nothing filed should not pass silently"

    # and it stops being said the moment a file arrives on that enquiry
    csv = b"account_code,account_name,debit,credit\n1000,Sales,0,500\n"
    r = api.post(f"/api/cases/{CASE}/documents",
                 files={"file": ("tb.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code == 200, r.text
    after = api.get(f"/api/cases/{CASE}/threads").json()["missing_attachments"]
    assert not [m for m in after if m["thread_id"] == open_id]


def test_an_outbound_letter_mentioning_attachments_is_not_flagged(api):
    """Our own letters say "please attach". Flagging those would make the check worthless."""
    state = api.get(f"/api/cases/{CASE}/threads").json()
    outbound_only = [t for t in state["threads"]
                     if t["messages"] and all(m["direction"] == "outbound" for m in t["messages"])
                     and not t["documents"]]
    flagged = {m["thread_id"] for m in state["missing_attachments"]}
    for t in outbound_only:
        assert t["id"] not in flagged, "only what the taxpayer claims to have sent counts"

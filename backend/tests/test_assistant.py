"""The case assistant, and the forwarded email.

The property the assistant lives or dies by: **it cannot do anything the application could not
already do from a button.** Every reply comes from a fixed set of actions run by a deterministic
executor, so a question that does not map to one is answered in words rather than by inventing a
capability — and no figure in any reply is written by a model.

The email tests cover the step that actually costs a round when it is done by hand: an auditor
forwards the taxpayer's reply, and the spreadsheets attached to it are filed as documents
without anyone having to find and upload them a second time.
"""
from __future__ import annotations

import io
from email.message import EmailMessage

import pytest

pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")

CASE = "CASE-2025-0481"          # the seeded case: a round, a document and real gaps
BARE = "CASE-2025-0484"          # a case with nothing on it


@pytest.fixture(scope="module")
def api(request):
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def own_case(api) -> str:
    """A case of this module's own, for the tests that add documents or record runs.

    Asking questions on a shared case only appends conversation rows, which nothing else reads.
    Filing an email or re-running the investigation changes the evidence, and a case file that
    other tests assert against is exactly the wrong place to do that.
    """
    r = api.post("/api/cases", json={
        "period_from": "2025-01-01", "period_to": "2025-03-31",
        "creation_reason": "Assistant tests",
        "taxpayer": {"name": "Assistant Fixture Co.",
                     "vat_registration_number": "391100220033003"},
    })
    assert r.status_code == 200, r.text
    return r.json()["case_id"]


def ask(api, case: str, question: str, action: str = ""):
    r = api.post(f"/api/cases/{case}/assistant",
                 json={"question": question, "action": action})
    assert r.status_code == 200, r.text
    return r.json()["messages"][-1]


# --------------------------------------------------------------- routing
def test_a_question_maps_to_one_of_the_things_it_can_actually_do():
    from app.agents.assistant import route

    assert route("what is still missing?") == "outstanding"
    assert route("draft the chase please") == "draft_chase"
    assert route("re-run the investigation") == "run_investigation"
    assert route("what has been established?") == "findings"
    assert route("compare with ZATCA") == "zatca"
    assert route("where are we on this case") == "status"


def test_anything_outside_the_set_is_answered_in_words_not_invented():
    """An assistant that quietly does something adjacent to what was asked is worse than one
    that says what it can do."""
    from app.agents.assistant import route

    assert route("book me a field visit next Tuesday") == "explain"
    assert route("") == "explain"


def test_the_action_set_is_closed_and_published(api):
    d = api.get(f"/api/cases/{CASE}/assistant").json()
    keys = {a["key"] for a in d["actions"]}
    assert keys == {"explain", "status", "outstanding", "draft_chase", "run_investigation",
                    "findings", "zatca", "revise_assessment"}
    for a in d["actions"]:
        assert a["hint"], f"{a['key']} does not say what it does"


# --------------------------------------------------------------- the answers
def test_it_answers_from_the_case_with_no_api_key(api):
    """Every deployment of this demo runs without credentials. The assistant is not an
    exception — it reads engine output, so it degrades to nothing."""
    m = ask(api, CASE, "what is still missing?")
    assert m["role"] == "assistant"
    assert m["action"] == "outstanding"
    assert "outstanding" in m["content"].lower()
    assert m["source"] in ("deterministic", "claude")


def test_the_status_answer_names_real_counts(api):
    m = ask(api, CASE, "where are we on this case")
    assert m["action"] == "status"
    assert "document" in m["content"]


def test_asking_for_findings_on_an_undecided_case_says_so(api):
    """The engine confirming a hypothesis is not the audit establishing a finding, and the
    assistant must not blur that — it is the distinction the whole decision model rests on."""
    m = ask(api, CASE, "what has been established?")
    assert m["action"] == "findings"
    assert "no finding" in m["content"].lower() or "accepted" in m["content"].lower()


def test_the_zatca_answer_reads_the_comparison(api):
    m = ask(api, CASE, "compare with ZATCA's records")
    assert m["action"] == "zatca"
    assert "invoice" in m["content"].lower()


def test_a_case_with_no_dataset_is_told_it_cannot_compare(api):
    m = ask(api, BARE, "compare with ZATCA's records")
    assert m["action"] == "zatca"
    assert "both sides" in m["content"] or "dataset" in m["content"]


def test_a_chase_is_refused_when_there_is_nothing_to_chase(api):
    m = ask(api, BARE, "draft the chase")
    assert m["action"] == "draft_chase"
    assert "nothing outstanding" in m["content"].lower()


# --------------------------------------------------------------- the record
def test_an_action_that_changed_something_says_what_it_changed(api, own_case):
    """A reader of the transcript has to be able to tell an answer from an action."""
    m = ask(api, own_case, "re-run the investigation")
    assert m["action"] == "run_investigation"
    assert m["did"], "a turn that recorded a run should say so"


def test_the_conversation_is_kept_and_is_one_per_case(api):
    before = len(api.get(f"/api/cases/{CASE}/assistant").json()["messages"])
    ask(api, CASE, "where are we")
    after = api.get(f"/api/cases/{CASE}/assistant").json()["messages"]

    assert len(after) == before + 2, "the question and the answer both belong on the record"
    assert after[-2]["role"] == "auditor"
    # a different case has its own conversation
    other = api.get(f"/api/cases/{BARE}/assistant").json()["messages"]
    assert len(other) != len(after) or not other


def test_clearing_empties_this_case_only(api):
    ask(api, BARE, "where are we")
    assert api.delete(f"/api/cases/{BARE}/assistant").json()["messages"] == []
    assert api.get(f"/api/cases/{CASE}/assistant").json()["messages"], \
        "clearing one case must not touch another"


def test_an_empty_question_is_refused(api):
    assert api.post(f"/api/cases/{CASE}/assistant",
                    json={"question": "  "}).status_code == 422


def test_an_unknown_case_is_a_404(api):
    assert api.get("/api/cases/NOPE-1/assistant").status_code == 404


# --------------------------------------------------------------- the forwarded email
def eml(*, sender: str, body: str, attachments=()) -> bytes:
    m = EmailMessage()
    m["Subject"] = "Re: Information request — VAT Q1 2025"
    m["From"] = sender
    m["To"] = "auditor@zatca.gov.sa"
    m["Date"] = "Mon, 14 Apr 2025 09:12:00 +0300"
    m.set_content(body)
    for name, payload in attachments:
        m.add_attachment(payload, maintype="application", subtype="octet-stream",
                         filename=name)
    return m.as_bytes()


CSV = (b"invoice_date,invoice_number,customer_name,taxable_amount,vat_amount\n"
       b"2025-03-04,INV-9001,Buyer Co,1000.00,150.00\n")


def test_a_forwarded_reply_joins_the_chain_as_the_taxpayers_words(api, own_case):
    data = eml(sender="finance@taxpayer.example",
               body="Please find the remaining analysis attached.")
    r = api.post(f"/api/cases/{own_case}/threads/email",
                 files={"file": ("reply.eml", io.BytesIO(data), "message/rfc822")})
    assert r.status_code == 200, r.text

    thread = r.json()["threads"][-1]
    msg = thread["messages"][-1]
    assert msg["direction"] == "inbound"
    assert msg["drafted_by"] == "taxpayer"
    assert "remaining analysis" in msg["body"]


def test_the_attachments_are_filed_as_documents_without_a_second_upload(api, own_case):
    """The step that costs a round when it is done by hand."""
    data = eml(sender="finance@taxpayer.example",
               body="The credit note listing is attached.",
               attachments=[("Credit_Notes_Q1.csv", CSV)])
    r = api.post(f"/api/cases/{own_case}/threads/email",
                 files={"file": ("with-attachment.eml", io.BytesIO(data), "message/rfc822")})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["filed"] == ["Credit_Notes_Q1.csv"]
    thread = body["threads"][-1]
    assert any(d["filename"] == "Credit_Notes_Q1.csv" for d in thread["documents"])
    assert any(d["rows"] == 1 for d in thread["documents"]), \
        "the attachment goes through the same extractor as any upload"


def test_our_own_sent_mail_is_not_recorded_as_the_taxpayers(api, own_case):
    """A letter the Authority wrote and a taxpayer's reply are different evidence about a case,
    and the trail is worthless if it flattens them."""
    data = eml(sender="auditor@zatca.gov.sa", body="Further to our request, please respond.")
    r = api.post(f"/api/cases/{own_case}/threads/email",
                 files={"file": ("sent.eml", io.BytesIO(data), "message/rfc822")})
    msg = r.json()["threads"][-1]["messages"][-1]

    assert msg["direction"] == "outbound"
    assert msg["drafted_by"] == "auditor"


def test_a_signature_image_is_not_filed_as_evidence(api, own_case):
    data = eml(sender="finance@taxpayer.example", body="See below.",
               attachments=[("image001.png", b"\x89PNG\r\n\x1a\n")])
    r = api.post(f"/api/cases/{own_case}/threads/email",
                 files={"file": ("sig.eml", io.BytesIO(data), "message/rfc822")})
    body = r.json()

    assert body["filed"] == []
    assert "image001.png" in body["skipped"]
    assert body["note"], "and it says why, rather than dropping it silently"


def test_an_unreadable_file_is_refused_rather_than_filed_empty(api, own_case):
    r = api.post(f"/api/cases/{own_case}/threads/email",
                 files={"file": ("junk.eml", io.BytesIO(b"\x00\x01not an email"),
                                 "message/rfc822")})
    assert r.status_code == 422


def test_an_outlook_msg_says_what_it_needs_rather_than_half_reading_it():
    """An email whose body was silently dropped is worse than one that was refused."""
    from app.requests import email_file

    parsed = email_file.parse("reply.msg", b"not really an OLE file")
    assert not parsed.ok
    assert parsed.note

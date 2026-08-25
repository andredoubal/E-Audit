"""The request spec, recovered from a chain of files rather than from a pasted message.

Pasting an email gave the parser a body and nothing else — no sender, no date, no attachments.
Three things follow from filing the messages as files instead, and each has a test here because
each is a way the pasted version was quietly wrong:

* **direction** — only ZATCA's own messages define the request. The taxpayer writing "please
  find the sales analysis attached" matches the same cue as the auditor asking for it, and a
  parser with no sender to look at could not tell the difference;
* **order** — a chain arrives from a file picker in whatever order it feels like, and a trail
  saying the chase went out before the request misrepresents the correspondence;
* **merge** — the opening request and the chase are both the request. Read only one and the spec
  is missing whatever the other asked for.

The unit tests run the merge over plain objects, because the merge is the part with the rules in
it. The HTTP tests then check that the endpoint does what the merge says over real `.eml` bytes.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from email.message import EmailMessage

import pytest

from app.requests import chain

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

CASE = "CASE-2025-0481"


# --------------------------------------------------------------------------- the merge
@dataclass
class M:
    seq: int
    direction: str
    body: str
    subject: str = ""
    sent_at: str = ""


REQUEST = """Dear Sir/Madam,

Further to our review of your VAT position for Q1 2025, please provide the following
within 20 working days:

1. A detailed sales analysis for the period, with the following columns: invoice date,
   invoice number, customer name, customer VAT number, taxable amount and VAT amount.
2. The trial balance as at 31 March 2025.

Yours faithfully,
Zakat, Tax and Customs Authority"""

CHASE = """Dear Sir,

Thank you for the sales analysis. The following are still outstanding:

1. The trial balance as at 31 March 2025.
2. A credit and debit note listing for the period.

Yours faithfully,
Zakat, Tax and Customs Authority"""

REPLY = """Dear Sir,

Please find attached the detailed sales analysis for the quarter. The trial balance will
follow next week.

Kind regards,
Finance"""


def keys(parsed) -> set[str]:
    return {i.key for i in parsed.items}


def test_the_chase_adds_to_the_request_rather_than_replacing_it():
    """Read only the last message and the spec loses everything the first one asked for."""
    parsed, _, _ = chain.from_messages([
        M(1, "outbound", REQUEST, sent_at="2025-04-14"),
        M(2, "outbound", CHASE, sent_at="2025-05-07"),
    ])
    assert "sales-analysis" in keys(parsed), "asked for in the opening request only"
    assert "credit-note-listing" in keys(parsed), "asked for in the chase only"
    assert "trial-balance" in keys(parsed), "asked for in both"


def test_an_item_asked_for_twice_is_one_item():
    parsed, _, _ = chain.from_messages([
        M(1, "outbound", REQUEST, sent_at="2025-04-14"),
        M(2, "outbound", CHASE, sent_at="2025-05-07"),
    ])
    assert len([i for i in parsed.items if i.key == "trial-balance"]) == 1


def test_the_taxpayers_own_words_never_become_a_request_item():
    """The reply matches the sales-analysis cue as squarely as the request does. Letting it
    through would have the taxpayer asking themselves for something, and then being chased for
    it."""
    parsed, per_message, _ = chain.from_messages([M(1, "inbound", REPLY, sent_at="2025-04-22")])

    assert parsed.items == []
    assert per_message[0]["direction"] == "inbound"
    assert per_message[0]["note"], "and it says why it was not read, rather than going silent"


def test_a_reply_between_two_requests_does_not_disturb_the_merge():
    parsed, per_message, _ = chain.from_messages([
        M(1, "outbound", REQUEST, sent_at="2025-04-14"),
        M(2, "inbound", REPLY, sent_at="2025-04-22"),
        M(3, "outbound", CHASE, sent_at="2025-05-07"),
    ])
    assert keys(parsed) == {"sales-analysis", "trial-balance", "credit-note-listing"}
    assert [m["direction"] for m in per_message] == ["outbound", "inbound", "outbound"]


def test_the_chain_is_read_in_sent_order_not_the_order_it_was_handed_over():
    """A file picker hands the messages over in whatever order it likes."""
    _, per_message, _ = chain.from_messages([
        M(9, "outbound", CHASE, sent_at="2025-05-07"),
        M(3, "outbound", REQUEST, sent_at="2025-04-14"),
    ])
    assert [m["seq"] for m in per_message] == [3, 9]


def test_the_cue_shown_is_the_message_that_first_asked():
    """The auditor checking the reading is looking for the ask they wrote, and the first one is
    the one they will look for."""
    parsed, _, _ = chain.from_messages([
        M(1, "outbound", REQUEST, sent_at="2025-04-14"),
        M(2, "outbound", CHASE, sent_at="2025-05-07"),
    ])
    tb = next(i for i in parsed.items if i.key == "trial-balance")
    assert "trial balance" in tb.cue.lower()


def test_columns_named_anywhere_in_the_chain_survive():
    """Taking only the last message's list would silently drop the six columns in the first."""
    later = """Dear Sir,

Please also include the description column in the sales analysis: invoice number, description.

Yours faithfully,
Zakat, Tax and Customs Authority"""
    parsed, _, _ = chain.from_messages([
        M(1, "outbound", REQUEST, sent_at="2025-04-14"),
        M(2, "outbound", later, sent_at="2025-05-07"),
    ])
    cols = [c.lower() for c in
            next(i for i in parsed.items if i.key == "sales-analysis").required_columns]
    assert "customer_vat_number" in cols, "from the opening request"
    assert "description" in cols, "added by the later message"


def test_two_periods_are_reported_rather_than_silently_resolved():
    """Either a typo or a widened scope, and a parser cannot know which."""
    other = "Please also provide the trial balance for Q3 2025."
    parsed, _, note = chain.from_messages([
        M(1, "outbound", REQUEST, sent_at="2025-04-14"),
        M(2, "outbound", other, sent_at="2025-05-07"),
    ])
    assert parsed.period_from and parsed.period_from.month == 1, "the first stated period stands"
    assert note and "confirm" in note


def test_the_later_deadline_replaces_the_earlier_one():
    """A chase granting ten more working days replaces the date; it does not add to it."""
    parsed, _, _ = chain.from_messages([
        M(1, "outbound", REQUEST, sent_at="2025-04-14"),
        M(2, "outbound", "Please respond within 10 working days.", sent_at="2025-05-07"),
    ])
    assert "10" in parsed.due_phrase


def test_an_empty_chain_proposes_nothing():
    parsed, per_message, _ = chain.from_messages([])
    assert parsed.items == [] and per_message == []


# ----------------------------------------------------------------------------- over HTTP
# Skipped inside the fixture rather than at module level: the merge tests above are pure Python
# and there is no reason for a missing HTTP client to take them down with it.

@pytest.fixture(scope="module")
def api(request):
    pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


def new_case(api, name: str, vat: str) -> str:
    r = api.post("/api/cases", json={
        "period_from": "2025-01-01", "period_to": "2025-03-31",
        "creation_reason": "Email chain tests",
        "taxpayer": {"name": name, "vat_registration_number": vat},
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["case_id"]


@pytest.fixture(scope="module")
def own_case(api) -> str:
    """A case of this module's own: filing emails changes the evidence, and a shared case that
    other tests read would then depend on the order the files landed in."""
    return new_case(api, "Email Chain Fixture Co.", "391100220033101")


def eml(*, sender: str, subject: str, body: str, date: str, attachments=()) -> bytes:
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = sender
    m["To"] = "finance@taxpayer.example"
    m["Date"] = date
    m.set_content(body)
    for name, payload in attachments:
        m.add_attachment(payload, maintype="application", subtype="octet-stream", filename=name)
    return m.as_bytes()


CSV = (b"invoice_date,invoice_number,customer_name,taxable_amount,vat_amount\n"
       b"2025-03-04,INV-9001,Buyer Co,1000.00,150.00\n")

ZATCA = "vat.audit@zatca.gov.sa"
TAXPAYER = "finance@taxpayer.example"


def upload(api, case: str, files: list[tuple[str, bytes]]):
    return api.post(f"/api/cases/{case}/threads/emails", files=[
        ("files", (name, io.BytesIO(data), "message/rfc822")) for name, data in files])


def test_a_whole_chain_goes_in_as_one_drop(api, own_case):
    r = upload(api, own_case, [
        ("01-request.eml", eml(sender=ZATCA, subject="Information request", body=REQUEST,
                               date="Mon, 14 Apr 2025 09:12:00 +0300")),
        ("02-reply.eml", eml(sender=TAXPAYER, subject="RE: Information request", body=REPLY,
                             date="Tue, 22 Apr 2025 16:40:00 +0300",
                             attachments=[("Sales_Q1.csv", CSV)])),
        ("03-chase.eml", eml(sender=ZATCA, subject="RE: Information request", body=CHASE,
                             date="Wed, 07 May 2025 10:05:00 +0300")),
    ])
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["read"] == 3 and body["unreadable"] == 0
    assert body["filed"] == ["Sales_Q1.csv"], "the attachment came with the message"
    messages = body["threads"][-1]["messages"]
    assert [m["direction"] for m in messages] == ["outbound", "inbound", "outbound"]


def test_the_drop_order_does_not_decide_the_chain_order(api):
    """Filed by the Date header, so the request precedes the chase however they were picked."""
    case = new_case(api, "Out Of Order Co.", "391100220033102")

    got = upload(api, case, [
        ("chase.eml", eml(sender=ZATCA, subject="Chase", body=CHASE,
                          date="Wed, 07 May 2025 10:05:00 +0300")),
        ("request.eml", eml(sender=ZATCA, subject="Request", body=REQUEST,
                            date="Mon, 14 Apr 2025 09:12:00 +0300")),
    ])
    assert got.status_code == 200, got.text
    subjects = [m["subject"] for m in got.json()["threads"][-1]["messages"]]
    assert subjects == ["Request", "Chase"]


def test_the_trail_carries_when_each_message_was_sent_not_when_it_was_filed(api):
    """A chain forwarded today carries messages sent months ago. Stamping the trail with the
    upload date would put the opening request and the chase on the same day."""
    case = new_case(api, "Sent Date Co.", "391100220033105")
    got = upload(api, case, [
        ("request.eml", eml(sender=ZATCA, subject="Request", body=REQUEST,
                            date="Mon, 14 Apr 2025 09:12:00 +0300")),
        ("chase.eml", eml(sender=ZATCA, subject="Chase", body=CHASE,
                          date="Wed, 07 May 2025 10:05:00 +0300")),
    ])
    assert got.status_code == 200, got.text
    sent = [m["sent_at"] for m in got.json()["threads"][-1]["messages"]]
    assert sent == ["2025-04-14", "2025-05-07"]


def test_a_message_with_no_date_header_leaves_the_sent_date_empty(api):
    """Rather than borrowing the filing date and presenting a guess as a fact."""
    case = new_case(api, "No Date Co.", "391100220033106")
    m = EmailMessage()
    m["Subject"] = "Request"
    m["From"] = ZATCA
    m["To"] = TAXPAYER
    m.set_content(REQUEST)
    got = upload(api, case, [("undated.eml", m.as_bytes())])

    assert got.status_code == 200, got.text
    assert got.json()["threads"][-1]["messages"][-1]["sent_at"] == ""


def test_one_unreadable_file_does_not_lose_the_rest_of_the_drop(api):
    case = new_case(api, "Partial Drop Co.", "391100220033103")

    got = upload(api, case, [
        ("good.eml", eml(sender=ZATCA, subject="Request", body=REQUEST,
                         date="Mon, 14 Apr 2025 09:12:00 +0300")),
        ("junk.eml", b"\x00\x01not an email"),
    ])
    assert got.status_code == 200, got.text
    body = got.json()

    assert body["read"] == 1 and body["unreadable"] == 1
    bad = next(x for x in body["results"] if not x["ok"])
    assert bad["filename"] == "junk.eml" and bad["note"], "named, with a reason"


def test_a_drop_with_nothing_readable_in_it_is_refused(api):
    case = new_case(api, "All Junk Co.", "391100220033104")
    got = upload(api, case, [("junk.eml", b"\x00\x01not an email")])
    assert got.status_code == 422


def test_the_spec_is_read_from_the_filed_chain(api, own_case):
    """The endpoint the auditor presses after dropping the files in."""
    r = api.post(f"/api/cases/{own_case}/request-email/from-chain")
    assert r.status_code == 200, r.text
    body = r.json()

    got = {i["key"] for i in body["items"]}
    assert {"sales-analysis", "trial-balance", "credit-note-listing"} <= got
    assert body["outbound_read"] == 2
    assert body["inbound_skipped"] == 1, "the taxpayer's reply was read for the record only"
    assert body["needs_confirmation"] is True, "it is still a proposal"
    assert body["catalog"], "and the auditor can add anything it missed"


def test_reading_a_chain_that_does_not_exist_says_so(api):
    r = api.post("/api/cases/CASE-2025-0484/request-email/from-chain")
    assert r.status_code == 422
    assert "chain" in r.json()["detail"] or "round" in r.json()["detail"]

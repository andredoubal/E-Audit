"""The audit report as a document a person signs: what it asserts, and what they can write.

Two properties are under test, and the first is the one that matters.

**The report and the letter say the same thing, and both say only what the auditor accepted.**
The verdict letter was drafted from `investigate_case` — the engine's own verdicts — while the
report was drafted from the auditor's decisions. On the seeded case that put a banner reading
"no finding has been confirmed yet" directly above a letter to the taxpayer asserting eight
findings and most of a million riyals of tax. An outbound letter stating as the Authority's
position something no person signed off is the single worst thing this application could do, so
there is a test here for each half of it.

**An edit reaches the document, not just the screen.** The Word file and the printable page are
what actually leave the building. An edit visible only in the browser would mean the auditor
sends the version they had already corrected, so the overlay is applied in the one place all
three renderings pass through and the tests check the download, not only the JSON.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")



@pytest.fixture(scope="module")
def api(request):
    pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


def _case_with_a_listing(api, name: str, vat: str) -> str:
    """A case carrying the demo sales listing, so it has real evidence to reason over.

    A document is filed against an enquiry, so the enquiry has to exist first — filing the
    request email opens it, which is how an auditor gets there too.
    """
    from email.message import EmailMessage

    from app.seed.demo_files import sales_analysis_xlsx

    r = api.post("/api/cases", json={
        "period_from": "2025-01-01", "period_to": "2025-03-31",
        "creation_reason": "Report editing tests",
        "taxpayer": {"name": name, "vat_registration_number": vat},
    })
    assert r.status_code in (200, 201), r.text
    case = r.json()["case_id"]

    m = EmailMessage()
    m["Subject"] = "Information request — VAT Q1 2025"
    m["From"] = "vat.audit@zatca.gov.sa"
    m["To"] = "finance@taxpayer.example"
    m["Date"] = "Mon, 14 Apr 2025 09:12:00 +0300"
    m.set_content("Please provide a detailed sales analysis for the period.")
    api.post(f"/api/cases/{case}/threads/email",
             files={"file": ("request.eml", m.as_bytes(), "message/rfc822")})

    up = api.post(f"/api/cases/{case}/documents",
                  files={"file": ("Sales_Analysis_Q1_2025.xlsx", sales_analysis_xlsx(),
                                  "application/vnd.openxmlformats-officedocument"
                                  ".spreadsheetml.sheet")})
    assert up.status_code == 200, up.text
    return case


@pytest.fixture(scope="module")
def undecided_case(api) -> str:
    """A case with real evidence and nothing accepted — its own, deliberately.

    These assertions used to run against the shared seeded case, which another module accepts
    hypotheses on. That is not a flaky test: a case whose decisions another file is changing
    cannot answer "what does the letter say when nothing has been decided".
    """
    return _case_with_a_listing(api, "Nothing Accepted Co.", "391100220055002")


@pytest.fixture(scope="module")
def own_case(api) -> str:
    """The case this module edits and accepts a finding on.

    Editing writes rows and accepting a hypothesis changes what the report asserts, so working
    the shared seeded case here would leave every other module reading a report this one had
    rewritten.
    """
    return _case_with_a_listing(api, "Report Edit Co.", "391100220055001")


def report(api, case: str) -> dict:
    r = api.get(f"/api/cases/{case}/audit-report")
    assert r.status_code == 200, r.text
    return r.json()


def fields(doc: dict) -> dict:
    return {f["label"]: f for s in doc["sections"] for f in s["fields"]}


def letters(api, case: str) -> dict:
    r = api.get(f"/api/cases/{case}/emails")
    assert r.status_code == 200, r.text
    return {e["kind"]: e for e in r.json()["emails"]}


# --------------------------------------------- the report and the letter tell the same story
def test_the_letter_asserts_nothing_the_auditor_has_not_accepted(api, undecided_case):
    """The bug this file exists for: the report said no finding was confirmed while the letter
    below it stated eight of them, with amounts, addressed to the taxpayer."""
    api.post(f"/api/cases/{undecided_case}/investigation/run", json={"trigger": "initial"})
    counts = api.get(f"/api/cases/{undecided_case}/investigation").json()["counts"]
    assert counts["total"] > 0 and counts["accepted"] == 0

    text = letters(api, undecided_case)["verdict"]["text"]
    # The computed difference is a fact and the letter may report it. What it may not do, with
    # nothing accepted, is turn that fact into a position — which is exactly what it did: "the
    # Authority will proceed on the basis set out above", over eight findings nobody had ruled
    # on.
    assert "established on review" not in text
    assert "will proceed on the basis" not in text
    assert "not yet concluded" in text and "no adjustment is proposed" in text
    assert "you accepted" not in letters(api, undecided_case)["verdict"]["trigger"]


def test_the_verdict_is_offered_even_when_there_is_nothing_to_assert(api, undecided_case):
    """It used to vanish. An auditor cannot tell an application with no letter for them from one
    that failed to produce it — and "no adjustment is proposed" is a real outcome letter."""
    v = letters(api, undecided_case)["verdict"]
    assert v["text"].strip(), "there is always a draft to read and edit"
    assert "outstanding" in v["trigger"] or "no finding accepted" in v["trigger"], \
        "and the trigger says why it has nothing to assert"


def test_accepting_a_finding_puts_it_in_both_the_report_and_the_letter(api, own_case):
    api.post(f"/api/cases/{own_case}/investigation/run", json={"trigger": "initial"})
    state = api.get(f"/api/cases/{own_case}/investigation").json()
    supported = [h for h in state["hypotheses"]
                 if h["status"] == "supported" and h.get("outcome_code")]
    if not supported:
        pytest.skip("this case produced no supported hypothesis with a vocabulary entry")

    h = supported[0]
    r = api.post(f"/api/cases/{own_case}/hypotheses/{h['hypothesis_id']}/decision",
                 json={"decision": "accepted", "comment": "Accepted on review."})
    assert r.status_code == 200, r.text

    statement = fields(report(api, own_case))["Audit Findings"]["value"]
    assert "No finding was established" not in statement
    assert letters(api, own_case)["verdict"]["trigger"].endswith("you accepted")


def test_every_finding_line_can_be_traced_back(api, own_case):
    trace = fields(report(api, own_case))["Audit Findings"]["trace"]
    assert trace, "a statement nobody can follow back to its source cannot be defended"
    for t in trace:
        assert t["statement"] and not t["statement"].startswith("- "), \
            "the inspector shows the sentence, not the document's list bullet"
        assert t["hypothesis_id"] or t["source"] == "auditor-authored"


# ------------------------------------------------------------------------------- the editing
def test_a_field_the_template_leaves_to_the_auditor_can_be_written(api, own_case):
    """`[for the auditor to complete]` is an instruction. A report that names the gap and then
    offers no way to close it is a form you cannot fill in."""
    before = fields(report(api, own_case))["Rulings"]
    assert before["held"] is False and before["editable"] is True

    r = api.put(f"/api/cases/{own_case}/audit-report/fields",
                json={"key": before["key"], "value": "No ruling has been issued.",
                      "original": before["value"]})
    assert r.status_code == 200, r.text

    after = fields(r.json())["Rulings"]
    assert after["value"] == "No ruling has been issued."
    assert after["edited"] is True and after["held"] is True


def test_the_completeness_tally_moves_with_the_edit(api, own_case):
    """Otherwise the header keeps reporting a field as outstanding after it was answered."""
    doc = report(api, own_case)
    open_before = doc["completeness"]["outstanding"]

    key = fields(doc)["Penalties imposed"]["key"]
    after = api.put(f"/api/cases/{own_case}/audit-report/fields",
                    json={"key": key, "value": "None."}).json()
    assert after["completeness"]["outstanding"] == open_before - 1
    assert after["edited_fields"] >= 1


def test_overriding_an_engine_value_keeps_what_it_replaced(api, own_case):
    """An override nobody can detect is not an override. The original travels with the field so
    the auditor can see what the tool said and put it back."""
    original = fields(report(api, own_case))["Audit objectives"]
    assert original["held"] is True, "this one is written by the engine"

    edited = api.put(f"/api/cases/{own_case}/audit-report/fields",
                     json={"key": original["key"], "value": "Rewritten by the auditor.",
                           "original": original["value"]}).json()
    f = fields(edited)["Audit objectives"]
    assert f["value"] == "Rewritten by the auditor."
    assert f["original"] == original["value"]


def test_a_second_edit_does_not_overwrite_the_engines_original(api, own_case):
    """Or "restore" would put back the auditor's previous draft rather than the engine's text."""
    engine = fields(report(api, own_case))["Audit objectives"]["original"]
    key = fields(report(api, own_case))["Audit objectives"]["key"]

    api.put(f"/api/cases/{own_case}/audit-report/fields",
            json={"key": key, "value": "Second pass.", "original": "Rewritten by the auditor."})
    assert fields(report(api, own_case))["Audit objectives"]["original"] == engine


def test_clearing_a_field_reverts_it_to_the_engines_value(api, own_case):
    """What an auditor expects from emptying a box — not a blank line in the report."""
    doc = report(api, own_case)
    engine = fields(doc)["Audit objectives"]["original"]
    key = fields(doc)["Audit objectives"]["key"]

    reverted = api.put(f"/api/cases/{own_case}/audit-report/fields",
                       json={"key": key, "value": ""}).json()
    f = fields(reverted)["Audit objectives"]
    assert f["value"] == engine and f["edited"] is False


def test_an_edit_reaches_the_word_download_and_the_printable_page(api, own_case):
    """The document is what leaves the building. An edit visible only on screen would mean the
    auditor sends the version they had already corrected."""
    for suffix in ("doc", "html"):
        body = api.get(f"/api/cases/{own_case}/audit-report.{suffix}").text
        assert "No ruling has been issued." in body
        assert "Written by the auditor" in body, "and the document says whose words they are"


def test_the_provenance_footer_narrows_once_a_person_has_written_in_it(api, own_case):
    """"Every figure here was computed by the engine" stops being true the moment a field is
    overridden, and a standing claim that is sometimes false is worse than a narrower one."""
    body = api.get(f"/api/cases/{own_case}/audit-report.html").text
    assert "Every figure the audit engine contributed" in body
    assert "written by the auditor" in body


def test_a_field_key_has_to_name_a_section(api, own_case):
    r = api.put(f"/api/cases/{own_case}/audit-report/fields",
                json={"key": "Rulings", "value": "x"})
    assert r.status_code == 422, "a bare label could write one section's value into another's"


# -------------------------------------------------------------------------------- the letter
def test_the_letter_can_be_rewritten_and_is_kept(api, own_case):
    """Every draft has said "a draft for you to edit and send" while offering no way to edit it.
    A letter is the one artefact here that leaves the building in the Authority's name."""
    before = letters(api, own_case)["verdict"]
    mine = before["text"] + "\n\nAgreed at the closing meeting of 12 August."

    r = api.put(f"/api/cases/{own_case}/letters/verdict",
                json={"body": mine, "generated": before["text"]})
    assert r.status_code == 200, r.text

    after = {e["kind"]: e for e in r.json()["emails"]}["verdict"]
    assert after["text"] == mine and after["edited"] is True
    assert after["generated"] == before["text"], "so the engine's draft can be restored"
    assert letters(api, own_case)["verdict"]["text"] == mine, "and it survives a reload"


def test_an_edited_letter_stops_claiming_the_verifier_checked_it(api, own_case):
    """The badge describes what the checker saw, and the checker never saw the auditor's words."""
    assert letters(api, own_case)["verdict"]["source"] == "auditor"
    assert letters(api, own_case)["verdict"]["violations"] == []


def test_clearing_the_letter_restores_the_generated_draft(api, own_case):
    generated = letters(api, own_case)["verdict"]["generated"]
    r = api.put(f"/api/cases/{own_case}/letters/verdict", json={"body": ""})
    after = {e["kind"]: e for e in r.json()["emails"]}["verdict"]

    assert after["edited"] is False
    assert after["text"] == generated


def test_an_unknown_letter_kind_is_refused(api, own_case):
    r = api.put(f"/api/cases/{own_case}/letters/assessment", json={"body": "x"})
    assert r.status_code == 422

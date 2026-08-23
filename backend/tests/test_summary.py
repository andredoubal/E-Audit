"""The investigation summary, and the auditor's assessment of it.

Two properties carry the whole redesign, and both are the kind that only a test notices:

**One card per basis.** A listing above the return reads four ways off one test over one file.
Four cards would state the same money four times — which is the exact defect `exposure()` was
written to stop the letter committing — so the summary must group by basis and name the other
readings underneath.

**An observation is not a determination.** The card keeps what was *measured* apart from what it
*would report as*, and the assessment says plainly that nothing is concluded until the auditor
confirms it. A summary that presented a discrepancy as a finding would be putting a conclusion
under the Authority's letterhead that nobody reached.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

CASE = "CASE-2025-0481"


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
    """This module's own case: saving an assessment and confirming matters changes what the
    report and the verdict letter say, which other modules assert against on the seeded case."""
    from email.message import EmailMessage

    from app.seed.demo_files import sales_analysis_xlsx

    case = api.post("/api/cases", json={
        "period_from": "2025-01-01", "period_to": "2025-03-31",
        "creation_reason": "Summary tests",
        "taxpayer": {"name": "Summary Co.", "vat_registration_number": "391100220077004"},
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


def summary(api, case: str) -> dict:
    r = api.get(f"/api/cases/{case}/investigation/summary")
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------- the cards
def test_the_summary_is_fewer_cards_than_hypotheses(api):
    """The point of the redesign. Twelve hypotheses is a list to scroll; the matters they
    describe are a handful, because several of them are one matter said differently."""
    s = summary(api, CASE)
    live = [h for h in api.get(f"/api/cases/{CASE}/investigation").json()["hypotheses"]
            if not h["stale"]]
    assert s["cards"], "the seeded case has findings; the summary must show them"
    assert len(s["cards"]) < len(live)


def test_one_card_per_basis_with_the_other_readings_named(api):
    """A card that carried one reading and dropped the rest would lose what the auditor has to
    defend; four cards would count one excess four times."""
    s = summary(api, CASE)
    keys = [c["key"] for c in s["cards"]]
    assert len(keys) == len(set(keys)), "a basis appears once"

    grouped = [c for c in s["cards"] if len(c["hypothesis_ids"]) > 1]
    assert grouped, "the seeded case has one excess that reads several ways"
    for c in grouped:
        assert c["alternatives"], "the other readings are named, not discarded"
        assert c["reading"] not in c["alternatives"], "the headline is not repeated beneath itself"


def test_the_headline_reading_is_the_one_that_carries_an_adjustment(api):
    """Where one file supports both an excess and a documentation defect, the excess is the
    finding — the same order `exposure()` uses when it excludes documentation risk on evidence
    already producing an adjustment."""
    from app import outcomes

    s = summary(api, CASE)
    for c in s["cards"]:
        if not c["outcome_code"] or len(c["hypothesis_ids"]) < 2:
            continue
        head = outcomes.BY_CODE.get(c["outcome_code"])
        if head and head.effect == outcomes.DOCUMENTATION:
            # Acceptable only when nothing in that group carries an adjustment.
            alts = [outcomes.BY_CODE[o].effect for o in outcomes.BY_CODE
                    if outcomes.BY_CODE[o].statement in c["alternatives"]]
            assert outcomes.INCREASES_OUTPUT not in alts and outcomes.DISALLOWS_INPUT not in alts


def test_observed_and_meaning_are_separate_fields(api):
    """The whole epistemic argument, in the data model: a measurement and a reading of it are
    two things, and collapsing them presents a discrepancy as a tax violation."""
    s = summary(api, CASE)
    for c in s["cards"]:
        assert c["observed"], f"{c['key']} says nothing about what was measured"
        assert c["kind"] in ("observation", "unresolved", "data-quality")
        assert c["observed"] != c["reading"]


def test_a_card_carries_no_decision_until_the_auditor_makes_one(api, own_case):
    s = summary(api, own_case)
    assert s["cards"], "this case produces matters"
    assert all(not c["decision"] for c in s["cards"])


def test_amounts_are_not_summed_across_readings_of_one_matter(api):
    """The defect this replaced: SAR 1,854,000 reported against a real excess of SAR 618,000."""
    s = summary(api, CASE)
    for c in s["cards"]:
        if len(c["hypothesis_ids"]) < 2:
            continue
        live = {h["hypothesis_id"]: abs(h["amount"]) for h in
                api.get(f"/api/cases/{CASE}/investigation").json()["hypotheses"]}
        parts = [live[h] for h in c["hypothesis_ids"] if h in live]
        assert c["amount"] == max(parts), "one matter, one amount"


def test_record_defects_appear_only_when_a_dataset_was_compared(api, own_case):
    """One side is not a comparison. With no ZATCA extract the matcher does not run, so there
    is no identifier or numbering defect to report — and reporting one anyway would be a
    finding about a file nobody supplied."""
    s = summary(api, own_case)
    assert not [c for c in s["cards"] if c["kind"] == "data-quality"]

    seeded = summary(api, CASE)
    assert [c for c in seeded["cards"] if c["kind"] == "data-quality"], \
        "the seeded case has a ZATCA dataset loaded"
    for c in seeded["cards"]:
        if c["kind"] == "data-quality":
            assert c["amount"] == 0, "a records defect claims no money"
            assert not c["hypothesis_ids"], "it is the matcher's, not an agent's"


def test_refuted_hypotheses_are_counted_but_not_carded(api):
    """A refuted hypothesis is part of the file and is not a matter to put to anyone."""
    s = summary(api, CASE)
    state = api.get(f"/api/cases/{CASE}/investigation").json()
    refuted = [h for h in state["hypotheses"] if h["status"] == "refuted" and not h["stale"]]
    assert s["totals"]["not_supported"] == len(refuted)
    carded = {h for c in s["cards"] for h in c["hypothesis_ids"]}
    assert not ({h["hypothesis_id"] for h in refuted} & carded)


# ----------------------------------------------------------------- the assessment
def test_the_assessment_is_drafted_before_the_auditor_writes(api, own_case):
    """With no credentials this is the deterministic draft, and it is complete prose rather
    than a stub — degrading costs polish, never correctness."""
    d = api.get(f"/api/cases/{own_case}/assessment").json()
    assert d["text"].strip()
    assert d["edited"] is False
    assert d["text"] == d["draft"]


def test_the_draft_says_nothing_is_concluded_until_the_auditor_confirms(api, own_case):
    d = api.get(f"/api/cases/{own_case}/assessment").json()
    assert "not concluded" in d["text"].lower() or "no adjustment is proposed" in d["text"].lower()


def test_every_figure_in_the_draft_is_one_the_engine_computed(api, own_case):
    """The core invariant, checked on this surface too: the draft may repeat a figure from the
    facts block and may not introduce one. Applies to the deterministic text as much as to a
    model's, because a fallback that invented a number would be no better."""
    from app.llm.verify import verify_correspondence

    d = api.get(f"/api/cases/{own_case}/assessment").json()
    v = verify_correspondence(d["text"], d["facts"])
    assert v["ok"], v["violations"]


def test_the_auditor_owns_it_and_the_draft_is_kept(api, own_case):
    mine = "Treated as a timing difference. Nothing is proposed for this period."
    d = api.put(f"/api/cases/{own_case}/assessment", json={"text": mine}).json()
    assert d["text"] == mine
    assert d["edited"] is True
    assert d["written_by"] == "auditor"
    assert d["original"] and d["original"] != mine, "what was replaced is recoverable"

    again = api.get(f"/api/cases/{own_case}/assessment").json()
    assert again["text"] == mine, "it persists"


def test_clearing_the_assessment_restores_the_engines_draft(api, own_case):
    """Same rule as the report fields and the letters: a blank assessment is not a position."""
    d = api.put(f"/api/cases/{own_case}/assessment", json={"text": ""}).json()
    assert d["edited"] is False
    assert d["text"] == d["draft"]
    assert d["text"].strip()


def test_a_revision_with_no_model_changes_nothing_and_says_so(api, own_case):
    """The honest failure. Storing the text unchanged and reporting a revision would tell the
    auditor their instruction was carried out when it was not."""
    d = api.post(f"/api/cases/{own_case}/assessment/revise",
                 json={"instruction": "Treat the difference as a timing matter."}).json()
    assert d["revised"] is False
    assert d["text"] == api.get(f"/api/cases/{own_case}/assessment").json()["text"]


def test_a_revision_needs_an_instruction(api, own_case):
    assert api.post(f"/api/cases/{own_case}/assessment/revise",
                    json={"instruction": "   "}).status_code == 422


def test_confirming_a_matter_is_what_reaches_the_report(api, own_case):
    """The decision controls moved off every hypothesis and into one place. What must not have
    moved is the consequence: only what the auditor confirms is a finding."""
    s = summary(api, own_case)
    card = next((c for c in s["cards"] if c["hypothesis_ids"]), None)
    assert card, "this case produces a matter to rule on"
    hid = card["hypothesis_ids"][0]

    before = api.get(f"/api/cases/{own_case}/audit-report").json()
    api.post(f"/api/cases/{own_case}/hypotheses/{hid}/decision",
             json={"decision": "accepted", "comment": "confirmed on the listing"})

    after_cards = summary(api, own_case)["cards"]
    assert any(c["decision"] == "accepted" for c in after_cards), \
        "the summary shows what the auditor ruled"
    after = api.get(f"/api/cases/{own_case}/audit-report").json()
    assert after != before, "confirming it changed the report"


def test_a_ruling_can_be_taken_back(api, own_case):
    """The design gives every settled matter an "undo".

    A decision an auditor cannot reverse is one they hesitate to make, and hesitating over a
    first pass is the opposite of what the assessment section is for. What goes is the
    auditor's position; the hypothesis and its verdict are untouched.
    """
    # An undecided matter of its own: an earlier test in this module confirms one, and a
    # ruling withdrawn here must not be read off that one.
    card = next(c for c in summary(api, own_case)["cards"]
                if c["hypothesis_ids"] and not c["decision"])
    hid = card["hypothesis_ids"][0]

    def mine(cards):
        return next(c for c in cards if c["key"] == card["key"])

    r = api.post(f"/api/cases/{own_case}/hypotheses/{hid}/decision",
                 json={"decision": "accepted", "comment": "on the listing"})
    assert r.status_code == 200, r.text
    assert mine(summary(api, own_case)["cards"])["decision"] == "accepted"

    r = api.delete(f"/api/cases/{own_case}/hypotheses/{hid}/decision")
    assert r.status_code == 200, r.text
    assert mine(summary(api, own_case)["cards"])["decision"] == ""

    state = api.get(f"/api/cases/{own_case}/investigation").json()
    h = next(h for h in state["hypotheses"] if h["hypothesis_id"] == hid)
    assert h["decision"] is None
    assert h["status"], "the verdict itself survives — only the ruling was withdrawn"


def test_undoing_a_decision_that_was_never_made_is_not_an_error(api, own_case):
    """Idempotent, because the button is in the UI and a double-click is not a fault."""
    hid = next(c for c in summary(api, own_case)["cards"]
               if c["hypothesis_ids"])["hypothesis_ids"][0]
    assert api.delete(f"/api/cases/{own_case}/hypotheses/{hid}/decision").status_code == 200
    assert api.delete(f"/api/cases/{own_case}/hypotheses/{hid}/decision").status_code == 200

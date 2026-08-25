"""The investigation's memory: does a verdict survive, and does a re-run merge or duplicate?

`test_agents.py` proves the pipeline reaches the right verdict. These tests prove the layer
above it: that the verdict is still there on the next request, that running again lands on the
same row rather than a second one, that a verdict which moves says so, and that an auditor's
decision is not quietly invalidated when the evidence shifts underneath it.

The confidence tests are deliberately about the *shape* of the scoring, not about any one
case's score. A test asserting "CASE-2025-0481's CA-01 scores 62" would break every time a
weight is retuned and would be testing the constants rather than the method.
"""
from __future__ import annotations

import pytest

from app.agents import confidence as conf


# ------------------------------------------------------------------ confidence, in isolation
def test_bands_are_ordered_and_cover_the_range():
    assert conf.band_for(100) == conf.BAND_STRONG
    assert conf.band_for(75) == conf.BAND_STRONG
    assert conf.band_for(74) == conf.BAND_MODERATE
    assert conf.band_for(50) == conf.BAND_MODERATE
    assert conf.band_for(49) == conf.BAND_LIMITED
    assert conf.band_for(25) == conf.BAND_LIMITED
    assert conf.band_for(24) == conf.BAND_INSUFFICIENT
    assert conf.band_for(0) == conf.BAND_INSUFFICIENT


def test_every_signal_is_published_with_its_weight():
    """The band is only defensible if the auditor can see what produced it."""
    a = conf.assess(detail={"rows_matched": 5}, status="supported")
    keys = {s["key"] for s in a.to_dict()["signals"]}
    assert keys == set(conf.LABELS)
    assert abs(sum(s["weight"] for s in a.to_dict()["signals"]) - 1.0) < 1e-9
    # every signal carries a human-readable reason, not just a number
    assert all(s["note"] for s in a.to_dict()["signals"])


def test_more_evidence_and_support_raises_the_score():
    weak = conf.assess(detail={"rows_matched": 1}, status="supported", blocking_gaps=4,
                       corroborating_sources=0, regulatory_state="not-found")
    strong = conf.assess(detail={"rows_matched": 40}, status="supported", blocking_gaps=0,
                         corroborating_sources=2, regulatory_state="found",
                         independently_validated=True)
    assert strong.score > weak.score
    assert strong.band == conf.BAND_STRONG


def test_contradictory_evidence_costs_confidence():
    clean = conf.assess(detail={"rows_matched": 10}, status="supported")
    contested = conf.assess(detail={"rows_matched": 10}, status="supported",
                            contradictions=["a recorded figure could not be reproduced"])
    assert contested.score < clean.score


def test_a_refuted_hypothesis_reports_no_confidence_band():
    """A band beside a refuted verdict would be read as a score against the claim."""
    a = conf.assess(detail={"rows_matched": 30}, status="refuted", blocking_gaps=0,
                    corroborating_sources=2, regulatory_state="found",
                    independently_validated=True)
    assert a.band == conf.BAND_INSUFFICIENT


def test_the_weakest_signal_names_what_would_help():
    a = conf.assess(detail={"rows_matched": 30}, status="supported", blocking_gaps=0,
                    corroborating_sources=2, regulatory_state="not-found",
                    independently_validated=True)
    assert a.to_dict()["weakest"] == "regulatory_support"
    assert "regulatory" in a.to_dict()["improve"]


def test_missing_regulatory_support_is_scored_as_absent_not_assumed():
    """Until the corpus lands every hypothesis reads not-found; it must cost, not be waived."""
    absent = conf.assess(detail={"rows_matched": 10}, status="supported",
                         regulatory_state="not-found")
    found = conf.assess(detail={"rows_matched": 10}, status="supported",
                        regulatory_state="found")
    assert found.score - absent.score == pytest.approx(conf.W_REGULATORY * 100, abs=1)


# ------------------------------------------------------------------ persistence, over HTTP
pytest.importorskip("httpx", reason="the API walk needs httpx for TestClient")

CASE = "CASE-2025-0481"


@pytest.fixture(scope="module")
def api(request):
    request.getfixturevalue("seeded")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


def test_reading_the_investigation_runs_it_once_and_keeps_it(api):
    first = api.get(f"/api/cases/{CASE}/investigation")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["runs"], "a first read should have produced a run"
    assert body["hypotheses"], "the seeded case should raise hypotheses"

    # reading again must not start a second run — the investigation is remembered, not redone
    again = api.get(f"/api/cases/{CASE}/investigation").json()
    assert len(again["runs"]) == len(body["runs"])


def test_every_hypothesis_carries_a_band_and_its_signals(api):
    body = api.get(f"/api/cases/{CASE}/investigation").json()
    for h in body["hypotheses"]:
        assert h["confidence"]["band"], h["hypothesis_id"]
        assert h["confidence"]["signals"], h["hypothesis_id"]
        # confidence and money are separate facts and must both be present, never merged
        assert "amount" in h


def test_running_again_merges_by_natural_key_rather_than_duplicating(api):
    before = api.get(f"/api/cases/{CASE}/investigation").json()
    ids_before = [h["hypothesis_id"] for h in before["hypotheses"]]

    rerun = api.post(f"/api/cases/{CASE}/investigation/run", json={"trigger": "auditor-requested"})
    assert rerun.status_code == 200, rerun.text
    after = rerun.json()

    ids_after = [h["hypothesis_id"] for h in after["hypotheses"]]
    assert sorted(ids_after) == sorted(ids_before), "a re-run must not create second copies"
    assert len(set(ids_after)) == len(ids_after), "hypothesis ids must stay unique per case"
    assert len(after["runs"]) == len(before["runs"]) + 1, "the run itself should be recorded"


def test_a_decision_persists_and_only_accepted_counts_as_confirmed(api):
    body = api.get(f"/api/cases/{CASE}/investigation").json()
    hid = body["hypotheses"][0]["hypothesis_id"]

    r = api.post(f"/api/cases/{CASE}/hypotheses/{hid}/decision",
                 json={"decision": "accepted", "comment": "Evidence reviewed."})
    assert r.status_code == 200, r.text

    reread = api.get(f"/api/cases/{CASE}/investigation").json()
    got = next(h for h in reread["hypotheses"] if h["hypothesis_id"] == hid)
    assert got["decision"]["decision"] == "accepted"
    assert got["decision"]["comment"] == "Evidence reviewed."
    assert reread["counts"]["accepted"] >= 1

    # a rejection is kept too — what was ruled out is part of the file
    other = next(h for h in reread["hypotheses"] if h["hypothesis_id"] != hid)
    api.post(f"/api/cases/{CASE}/hypotheses/{other['hypothesis_id']}/decision",
             json={"decision": "rejected", "comment": "Not persuasive."})
    third = api.get(f"/api/cases/{CASE}/investigation").json()
    kept = next(h for h in third["hypotheses"]
                if h["hypothesis_id"] == other["hypothesis_id"])
    assert kept["decision"]["decision"] == "rejected"


def test_an_unknown_decision_is_rejected(api):
    body = api.get(f"/api/cases/{CASE}/investigation").json()
    hid = body["hypotheses"][0]["hypothesis_id"]
    r = api.post(f"/api/cases/{CASE}/hypotheses/{hid}/decision", json={"decision": "maybe"})
    assert r.status_code == 422


def test_deciding_on_a_hypothesis_that_is_not_on_the_case_is_a_404(api):
    r = api.post(f"/api/cases/{CASE}/hypotheses/NOPE-99/decision",
                 json={"decision": "accepted"})
    assert r.status_code == 404


def test_an_auditor_can_record_a_finding_the_agents_had_no_test_for(api):
    r = api.post(f"/api/cases/{CASE}/auditor-findings",
                 json={"statement": "Supply treated as zero-rated without export evidence.",
                       "amount": 12500.0, "note": "Seen during the line review."})
    assert r.status_code == 200, r.text
    assert r.json()["basis"].startswith("auditor|")

    listed = api.get(f"/api/cases/{CASE}/auditor-findings").json()
    assert any(f["statement"].startswith("Supply treated as zero-rated") for f in listed)

    blank = api.post(f"/api/cases/{CASE}/auditor-findings", json={"statement": "   "})
    assert blank.status_code == 422


def test_the_stateless_investigate_endpoint_still_works(api):
    """The persisted view is additive: the original read-only path must be untouched."""
    r = api.get(f"/api/cases/{CASE}/investigate")
    assert r.status_code == 200
    assert "hypotheses" in r.json() and "adjudications" in r.json()


# ------------------------------------------------- the part that only matters on the second run
def test_status_widens_the_adjudicators_three_verdicts_without_contradicting_them():
    """`partially-supported` is `confirmed` read against the gap it was meant to explain."""
    from types import SimpleNamespace
    from app.agents.investigation_service import status_for
    from app.models.investigation import (
        STATUS_INCONCLUSIVE, STATUS_PARTIAL, STATUS_REFUTED, STATUS_SUPPORTED)

    recon = {"unexplained": 100_000.0, "materiality": 5_000.0}
    adj = lambda status, amount: SimpleNamespace(status=status, amount=amount)

    assert status_for(adj("refuted", 0), recon) == STATUS_REFUTED
    assert status_for(adj("insufficient-evidence", 0), recon) == STATUS_INCONCLUSIVE
    # accounts for the whole difference -> supported
    assert status_for(adj("confirmed", 100_000.0), recon) == STATUS_SUPPORTED
    # within materiality of it -> still supported
    assert status_for(adj("confirmed", 96_000.0), recon) == STATUS_SUPPORTED
    # true, but nowhere near the whole story -> partially supported, not "the answer"
    assert status_for(adj("confirmed", 10_000.0), recon) == STATUS_PARTIAL
    # confirmed but carries no money (recurrence, magnitude) -> corroborating context
    assert status_for(adj("confirmed", 0.0), recon) == STATUS_SUPPORTED


def test_a_verdict_that_moves_keeps_the_previous_one_and_flags_the_decision(api, seeded):
    """The failure this table exists to prevent: an acceptance surviving the evidence changing.

    Forces a flip by rewriting the stored verdict, then re-running. The re-run re-adjudicates
    from the real case data, lands on the original verdict again, and must therefore record
    that the status moved *and* mark the auditor's decision for re-confirmation.
    """
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import AuditorDecision, PersistedHypothesis

    body = api.get(f"/api/cases/{CASE}/investigation").json()
    target = next(h for h in body["hypotheses"] if h["status"] != "refuted")
    hid = target["hypothesis_id"]

    api.post(f"/api/cases/{CASE}/hypotheses/{hid}/decision",
             json={"decision": "accepted", "comment": "Accepted on the first run."})

    db = SessionLocal()
    try:
        row = db.scalar(select(PersistedHypothesis).where(
            PersistedHypothesis.case_id == CASE, PersistedHypothesis.hypothesis_id == hid))
        row.status = "refuted"          # pretend the earlier run had refuted it
        db.commit()
    finally:
        db.close()

    after = api.post(f"/api/cases/{CASE}/investigation/run",
                     json={"trigger": "new-evidence"}).json()
    moved = next(h for h in after["hypotheses"] if h["hypothesis_id"] == hid)

    assert moved["superseded_status"] == "refuted", "the previous verdict must be kept"
    assert moved["status"] != "refuted", "the new verdict should have replaced it"
    assert moved["superseded_at_run"], "the run that changed it should be named"
    assert moved["decision"]["needs_reconfirmation"] is True, \
        "an acceptance made before the verdict moved must be flagged, not silently kept"
    assert after["counts"]["needs_reconfirmation"] >= 1

    # deciding again clears the flag — the auditor has now looked at the new verdict
    api.post(f"/api/cases/{CASE}/hypotheses/{hid}/decision",
             json={"decision": "accepted", "comment": "Re-confirmed against the new run."})
    cleared = next(h for h in api.get(f"/api/cases/{CASE}/investigation").json()["hypotheses"]
                   if h["hypothesis_id"] == hid)
    assert cleared["decision"]["needs_reconfirmation"] is False


def test_a_hypothesis_the_roster_stops_proposing_is_kept_and_marked_stale(api, seeded):
    """What was investigated stays on the file even when its preconditions no longer hold."""
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import PersistedHypothesis

    db = SessionLocal()
    try:
        db.add(PersistedHypothesis(
            case_id=CASE, hypothesis_id="ZZ-99", agent="Retired Agent",
            claim="A question that was asked once and no longer applies.",
            status="refuted", first_seen_run=1, last_seen_run=1))
        db.commit()
    finally:
        db.close()

    after = api.post(f"/api/cases/{CASE}/investigation/run", json={"trigger": "auditor-requested"}).json()
    ghost = next((h for h in after["hypotheses"] if h["hypothesis_id"] == "ZZ-99"), None)
    assert ghost is not None, "a hypothesis must not vanish because it stopped being proposed"
    assert ghost["stale"] is True
    assert ghost["status"] == "refuted", "its last verdict is preserved as it stood"


def test_evidence_strength_reads_whatever_key_the_test_reported_rows_under():
    """Each adjudicator test names its row count differently; scoring must not miss them.

    Reading only `rows_matched` scored a `listing-vs-declared` verdict over 22 summed rows as
    having no row-level evidence at all, which is both wrong and exactly the kind of quiet
    misreport a confidence signal must not make.
    """
    for key in ("rows_matched", "rows_failing", "rows_unsupported", "rows_outside",
                "rows", "rows_tested"):
        a = conf.assess(detail={key: 22}, status="supported")
        ev = next(s for s in a.to_dict()["signals"] if s["key"] == "evidence_strength")
        assert ev["value"] > 0.5, f"{key} was not read as row-level evidence"
        assert "22" in ev["note"]

    unknown = conf.assess(detail={"something_else": 9}, status="supported")
    ev = next(s for s in unknown.to_dict()["signals"] if s["key"] == "evidence_strength")
    assert ev["value"] == 0.5 and "no row-level evidence" in ev["note"]

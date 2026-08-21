"""Guards for the live regulatory-answer path — mirrors test_llm_path.py's SDK-stubbing
pattern. Proves that a compliant [[LAW:...]]-citing draft reaches the stream verbatim, that a
draft citing an ungrounded unit_id is retried and then degraded, and that a missing key
degrades immediately to the deterministic citation-list fallback."""
from __future__ import annotations

import pytest

from app.llm import service as svc
from tests.test_llm_path import live, stub_client  # reuse the SDK stub + live fixture

GROUNDING = {
    "query": "What evidence is needed to adjust output tax?",
    "cited_units": [
        {"unit_id": "TEST-IR-A49-P01", "citation_label": "Article 49, Paragraph 1",
         "content_type": "IMPLEMENTING_REGULATION", "status": "ACTIVE",
         "authority": "ZATCA", "effective_from": "2020-01-01", "effective_to": None,
         "text": "A taxable person may adjust output tax where a tax invoice is cancelled.",
         "parent": None, "score": 0.9},
    ],
}


def test_compliant_draft_reaches_the_stream(live, monkeypatch):
    good = "Per [[LAW:TEST-IR-A49-P01]], a credit or debit note is required."
    monkeypatch.setattr(svc, "_client", stub_client(prose=good))
    frames = "".join(svc.llm.stream_regulatory_answer(GROUNDING))
    assert "[[LAW:TEST-IR-A49-P01]]" in frames
    assert frames.rstrip().endswith("event: done\ndata: claude")


def test_ungrounded_citation_is_never_shown_and_falls_back(live, monkeypatch):
    bad = "Per [[LAW:MADE-UP-ARTICLE]], this is required."
    monkeypatch.setattr(svc, "_client", stub_client(prose=[bad, bad]))
    frames = "".join(svc.llm.stream_regulatory_answer(GROUNDING))
    assert "event: fallback" in frames
    assert "MADE-UP-ARTICLE" not in frames
    assert "Article 49, Paragraph 1" in frames  # the deterministic fallback citation list
    assert frames.rstrip().endswith("event: done\ndata: blocked-unverified")


def test_corrective_retry_can_rescue_a_bad_first_draft(live, monkeypatch):
    bad = "Per [[LAW:MADE-UP-ARTICLE]], this is required."
    good = "Per [[LAW:TEST-IR-A49-P01]], a credit or debit note is required."
    monkeypatch.setattr(svc, "_client", stub_client(prose=[bad, good]))
    frames = "".join(svc.llm.stream_regulatory_answer(GROUNDING))
    assert "[[LAW:TEST-IR-A49-P01]]" in frames
    assert frames.rstrip().endswith("event: done\ndata: claude")


def test_refusal_falls_back(live, monkeypatch):
    monkeypatch.setattr(svc, "_client",
                        stub_client(prose="anything", stop_reason="refusal"))
    frames = "".join(svc.llm.stream_regulatory_answer(GROUNDING))
    assert frames.rstrip().endswith("event: done\ndata: blocked-refusal")


def test_no_credentials_degrades_immediately(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_PROFILE", raising=False)
    frames = "".join(svc.llm.stream_regulatory_answer(GROUNDING))
    assert "Article 49, Paragraph 1" in frames
    assert frames.rstrip().endswith("event: done\ndata: deterministic-fallback")


def test_no_matching_units_gives_an_honest_empty_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    frames = "".join(svc.llm.stream_regulatory_answer({"query": "x", "cited_units": []}))
    assert "No matching regulatory text" in frames

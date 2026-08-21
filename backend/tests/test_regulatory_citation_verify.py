"""verify_citation: cite-or-drop. Mirrors test_verify.py's structure."""
from __future__ import annotations

from app.llm.verify import fb_regulatory_answer, verify_citation

GROUNDING = {
    "query": "What evidence is needed to adjust output tax?",
    "cited_units": [
        {"unit_id": "TEST-IR-A49-P01", "citation_label": "Article 49, Paragraph 1",
         "content_type": "IMPLEMENTING_REGULATION", "status": "ACTIVE",
         "text": "A taxable person may adjust output tax where a tax invoice is cancelled."},
        {"unit_id": "TEST-IR-GUIDE-1", "citation_label": "ZATCA Example 3",
         "content_type": "AUDITOR_METHOD", "status": "ACTIVE",
         "text": "In practice, auditors first check for a matching credit note."},
    ],
}


def test_grounded_law_citation_passes():
    r = verify_citation("Per [[LAW:TEST-IR-A49-P01]], a credit note is required.", GROUNDING)
    assert r["ok"] is True
    assert r["violations"] == []


def test_ungrounded_citation_is_rejected():
    r = verify_citation("Per [[LAW:TEST-IR-A99-NOPE]], this is required.", GROUNDING)
    assert r["ok"] is False
    assert "TEST-IR-A99-NOPE" in r["violations"][0]


def test_non_binding_content_cited_as_law_is_rejected():
    """The content-type guard: AUDITOR_METHOD may never be [[LAW:...]] — a real unit_id is not
    enough if the content behind it isn't binding legal text."""
    r = verify_citation("Per [[LAW:TEST-IR-GUIDE-1]], this is required.", GROUNDING)
    assert r["ok"] is False
    assert "TEST-IR-GUIDE-1" in r["violations"][0]


def test_non_binding_content_cited_as_ref_passes():
    r = verify_citation("See [[REF:TEST-IR-GUIDE-1]] for our usual approach.", GROUNDING)
    assert r["ok"] is True


def test_ungrounded_ref_is_also_rejected():
    r = verify_citation("See [[REF:MADE-UP-ID]] for context.", GROUNDING)
    assert r["ok"] is False


def test_text_with_no_citations_passes_trivially():
    assert verify_citation("General commentary with no citation tokens at all.", GROUNDING)["ok"]


def test_fallback_is_never_empty():
    assert fb_regulatory_answer(GROUNDING).strip()
    assert fb_regulatory_answer({"cited_units": []}).strip()


def test_fallback_only_states_what_grounding_actually_contains():
    text = fb_regulatory_answer(GROUNDING)
    assert "Article 49, Paragraph 1" in text
    assert "ZATCA Example 3" in text

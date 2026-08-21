"""Hybrid retrieval — mirrors test_precedent.py's rigor: reproducibility and sort order are
the properties an auditor actually depends on."""
from __future__ import annotations

from app.regulatory.embeddings import HashingEmbeddingProvider

from app.regulatory.retrieval import W_EXACT, W_LEXICAL, W_VECTOR, hybrid_retrieve
from app.regulatory.agent import answer_query


def test_the_ranked_list_is_stable_across_runs(reg_seeded):
    provider = HashingEmbeddingProvider()
    a = hybrid_retrieve(reg_seeded, "What does Article 49 say about adjustments?",
                        regulation_code="TEST-IR", provider=provider)
    b = hybrid_retrieve(reg_seeded, "What does Article 49 say about adjustments?",
                        regulation_code="TEST-IR", provider=provider)
    assert [c.unit_id for c in a] == [c.unit_id for c in b]
    assert [c.fused for c in a] == [c.fused for c in b]


def test_matches_are_sorted_by_fused_score_descending(reg_seeded):
    provider = HashingEmbeddingProvider()
    candidates = hybrid_retrieve(reg_seeded, "adjustment credit note tax invoice",
                                 regulation_code="TEST-IR", provider=provider)
    assert candidates
    assert all(a.fused >= b.fused for a, b in zip(candidates, candidates[1:]))


def test_exact_article_reference_wins(reg_seeded):
    provider = HashingEmbeddingProvider()
    candidates = hybrid_retrieve(reg_seeded, "What does Article 49 say about adjustments?",
                                 regulation_code="TEST-IR", provider=provider)
    top_ids = {c.unit_id for c in candidates[:1]}
    assert "TEST-IR-A49" in top_ids


def test_weights_sum_to_one():
    assert abs((W_EXACT + W_VECTOR + W_LEXICAL) - 1.0) < 1e-9


def test_small_to_big_expansion_includes_parent_article(reg_seeded):
    # Query the paragraph's own content (not "Article 49" or "paragraph 1", which are not
    # literal words inside the paragraph's text) so lexical overlap actually favours it.
    grounding, _trace_id = answer_query(
        reg_seeded, "credit or debit note evidencing an altered consideration",
        regulation_code="TEST-IR", provider=HashingEmbeddingProvider())
    hit = next((u for u in grounding["cited_units"] if u["unit_id"] == "TEST-IR-A49-P01"), None)
    assert hit is not None
    assert hit["parent"] is not None
    assert hit["parent"]["unit_id"] == "TEST-IR-A49"


def test_no_query_terms_returns_no_lexical_matches(reg_seeded):
    from app.regulatory.retrieval import lexical_search

    assert lexical_search(reg_seeded, "", regulation_code="TEST-IR") == {}


def test_arabic_exact_match_recognises_digit_and_spelled_out_ordinal_forms(seeded):
    from datetime import date
    from pathlib import Path

    from app.regulatory.embeddings import HashingEmbeddingProvider
    from app.regulatory.extract import PlainTextExtractor
    from app.regulatory.ingest import ingest_arabic_document
    from app.regulatory.retrieval import exact_match

    fixture = Path(__file__).parent / "fixtures" / "regulatory" / "fake_vat_ir_excerpt_ar.txt"
    ingest_arabic_document(
        seeded, source_path=fixture, regulation_code="TEST-IR-AR",
        content_type="IMPLEMENTING_REGULATION", effective_from=date(2016, 11, 14),
        authority="ZATCA", extractor=PlainTextExtractor(), provider=HashingEmbeddingProvider(),
        needs_bidi_reconstruction=False,
    )
    seeded.commit()

    assert exact_match(seeded, "المادة 49 عن ماذا؟", "TEST-IR-AR") == {"TEST-IR-AR-A49"}
    assert exact_match(seeded, "ماذا تقول المادة التاسعة والأربعون؟",
                       "TEST-IR-AR") == {"TEST-IR-AR-A49"}

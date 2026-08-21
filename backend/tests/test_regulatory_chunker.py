"""Chunker correctness — no database needed, pure functions over the synthetic fixture text.

This is the highest-risk piece of the ingestion pipeline (see chunker.py's docstring), so it
gets the most direct coverage: boundary detection, parent linking, idempotency, and
cross-reference detection.
"""
from __future__ import annotations

from pathlib import Path

from app.regulatory.chunker import chunk, find_article_references, make_unit_id

FIXTURE = Path(__file__).parent / "fixtures" / "regulatory" / "fake_vat_ir_excerpt.txt"


def _units():
    return chunk(FIXTURE.read_text(encoding="utf-8"), regulation_code="TEST-IR")


def _by_id(units, unit_id):
    return next(u for u in units if u["unit_id"] == unit_id)


def test_unit_ids_match_the_expected_shape():
    ids = {u["unit_id"] for u in _units()}
    assert "TEST-IR-A49" in ids
    assert "TEST-IR-A49-P01" in ids
    assert "TEST-IR-A49-P01-Sa" in ids
    assert "TEST-IR-A49-P01-Sb" in ids
    assert "TEST-IR-A49-P02" in ids


def test_make_unit_id_is_the_single_source_of_the_id_format():
    assert make_unit_id("TEST-IR", "49") == "TEST-IR-A49"
    assert make_unit_id("TEST-IR", "49", "7") == "TEST-IR-A49-P07"
    assert make_unit_id("TEST-IR", "49", "7", "a") == "TEST-IR-A49-P07-Sa"


def test_levels_are_assigned_correctly():
    units = _units()
    assert _by_id(units, "TEST-IR-A49")["level"] == "article"
    assert _by_id(units, "TEST-IR-A49-P01")["level"] == "paragraph"
    assert _by_id(units, "TEST-IR-A49-P01-Sa")["level"] == "subparagraph"


def test_parent_links_form_a_correct_chain():
    units = _units()
    p01 = _by_id(units, "TEST-IR-A49-P01")
    assert p01["parent_id"] == "TEST-IR-A49"
    sa = _by_id(units, "TEST-IR-A49-P01-Sa")
    assert sa["parent_id"] == "TEST-IR-A49-P01"


def test_chapter_metadata_is_attached_to_the_article_not_a_separate_node():
    units = _units()
    a49 = _by_id(units, "TEST-IR-A49")
    assert a49["chapter_no"] == "Three"
    assert "Adjustments" in a49["chapter_title"]
    assert not any(u["level"] == "chapter" for u in units)


def test_a_condition_stays_with_its_own_subparagraph_not_bled_into_the_next():
    units = _units()
    sa = _by_id(units, "TEST-IR-A49-P01-Sa")
    sb = _by_id(units, "TEST-IR-A49-P01-Sb")
    assert "credit or debit note" in sa["text"]
    assert "credit or debit note" not in sb["text"]
    assert "original tax invoice number" in sb["text"]
    assert "original tax invoice number" not in sa["text"]


def test_citation_labels_are_human_readable():
    units = _units()
    assert _by_id(units, "TEST-IR-A49")["citation_label"] == "Article 49"
    assert _by_id(units, "TEST-IR-A49-P01")["citation_label"] == "Article 49, Paragraph 1"
    assert (_by_id(units, "TEST-IR-A49-P01-Sa")["citation_label"]
            == "Article 49, Paragraph 1(a)")


def test_chunking_is_idempotent():
    a = chunk(FIXTURE.read_text(encoding="utf-8"), regulation_code="TEST-IR")
    b = chunk(FIXTURE.read_text(encoding="utf-8"), regulation_code="TEST-IR")
    assert [u["unit_id"] for u in a] == [u["unit_id"] for u in b]
    assert [u["text"] for u in a] == [u["text"] for u in b]


def test_cross_reference_detection_finds_article_51_from_article_49():
    units = _units()
    a49 = _by_id(units, "TEST-IR-A49")
    assert find_article_references(a49["text"], exclude_article="49") == {"51"}


def test_cross_reference_detection_excludes_self_reference():
    """Article 51's own text mentions "Article 49" (a real cross-reference) but never cites
    itself — exclude_article guards against a unit linking to its own parent article number."""
    units = _units()
    a51 = _by_id(units, "TEST-IR-A51")
    refs = find_article_references(a51["text"], exclude_article="51")
    assert refs == {"49"}
    assert "51" not in find_article_references(a51["text"], exclude_article="51")


def test_a_numbered_line_before_any_article_is_not_treated_as_a_paragraph():
    """Regression guard: PARAGRAPH_RE matching a stray numbered line outside any article
    (e.g. a page number or a preamble list) must not be attached to a phantom article."""
    text = "1. Not a real paragraph — no Article header precedes it.\n\nArticle 1: Real\n1. Real one."
    units = chunk(text, regulation_code="X")
    assert len(units) == 2  # the article + its one real paragraph
    assert all(u["article_no"] == "1" for u in units)

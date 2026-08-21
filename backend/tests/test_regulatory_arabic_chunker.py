"""Arabic article-level chunking — a small hand-written fixture, structurally like the real
ZATCA Implementing Regulations (feminine article ordinals, masculine chapter ordinals, a
"(مكرر)" amendment article, a cross-article reference) but not real legal text.

The real-PDF validation (81 of ~81-82 articles recovered, 0 unparsed-ordinal warnings, correct
chapter titles) lives in the ingestion QA report, not here — these tests are the fast,
hermetic, portable ones that run in `pytest backend/tests` with no external file."""
from __future__ import annotations

from pathlib import Path

from app.regulatory.arabic_chunker import chunk_arabic, find_arabic_article_references

FIXTURE = Path(__file__).parent / "fixtures" / "regulatory" / "fake_vat_ir_excerpt_ar.txt"


def _units():
    units, warnings = chunk_arabic(FIXTURE.read_text(encoding="utf-8"),
                                   regulation_code="TEST-IR-AR")
    assert warnings == []
    return units


def _by_id(units, unit_id):
    return next(u for u in units if u["unit_id"] == unit_id)


def test_feminine_article_ordinals_parse_to_the_right_number():
    units = _units()
    ids = {u["unit_id"] for u in units}
    assert "TEST-IR-AR-A49" in ids
    assert "TEST-IR-AR-A51" in ids


def test_masculine_chapter_ordinal_parses_and_is_attached_to_every_article():
    units = _units()
    assert all(u["chapter_no"] == "3" for u in units)
    assert all("التعديلات" in u["chapter_title"] for u in units)


def test_repeated_marker_article_gets_its_own_unit_id_not_merged_into_the_base_article():
    units = _units()
    a32 = _by_id(units, "TEST-IR-AR-A32R")
    assert a32["article_no"] == "32R"
    assert a32["citation_label"] == "Article 32 (repeated)"
    assert not any(u["unit_id"] == "TEST-IR-AR-A32" for u in units)  # no bare 32 in this fixture


def test_citation_labels_are_readable():
    units = _units()
    assert _by_id(units, "TEST-IR-AR-A49")["citation_label"] == "Article 49"


def test_article_text_contains_its_own_body_not_the_next_articles():
    units = _units()
    a49 = _by_id(units, "TEST-IR-AR-A49")
    assert "تعديل ضريبة المخرجات" in a49["text"]
    assert "الحدود الزمنية للتعديلات" not in a49["text"]  # that's Article 51's title


def test_cross_reference_from_article_49_to_article_51_is_found():
    units = _units()
    a49 = _by_id(units, "TEST-IR-AR-A49")
    assert find_arabic_article_references(a49["text"], exclude_article="49") == {"51"}


def test_toc_dot_leader_lines_are_never_treated_as_headers():
    """A table-of-contents entry ("4 ....... المادة X: ...") must never spawn a unit — real
    body headers do, and only the dot leader tells them apart."""
    toc_like = "4 ....................................................... المادة السادسة: عنوان\n"
    units, warnings = chunk_arabic(toc_like, regulation_code="X")
    assert units == []
    assert warnings == []


def test_chunking_is_idempotent():
    text = FIXTURE.read_text(encoding="utf-8")
    a, _ = chunk_arabic(text, regulation_code="TEST-IR-AR")
    b, _ = chunk_arabic(text, regulation_code="TEST-IR-AR")
    assert [u["unit_id"] for u in a] == [u["unit_id"] for u in b]
    assert [u["text"] for u in a] == [u["text"] for u in b]


def test_an_unparseable_ordinal_is_reported_not_silently_dropped():
    bad = "المادة نص غير صالح تمامًا للتحويل: عنوان\n"
    units, warnings = chunk_arabic(bad, regulation_code="X")
    assert units == []
    assert len(warnings) == 1
    assert "unparsed article ordinal" in warnings[0]

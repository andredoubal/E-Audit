"""Ingestion persists what the chunker found, embeds every unit exactly once, and resolves
cross-references only against targets that actually exist as rows."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.models import LegalRelationship, LegalUnit, LegalUnitEmbedding
from app.regulatory.extract import PlainTextExtractor
from app.regulatory.ingest import ingest_document
from app.regulatory.embeddings import HashingEmbeddingProvider

FIXTURE = Path(__file__).parent / "fixtures" / "regulatory" / "fake_vat_ir_excerpt.txt"


def test_every_chunk_becomes_a_legal_unit_row(reg_seeded):
    units = reg_seeded.scalars(
        select(LegalUnit).where(LegalUnit.regulation_code == "TEST-IR")).all()
    ids = {u.unit_id for u in units}
    assert "TEST-IR-A49" in ids
    assert "TEST-IR-A49-P01-Sa" in ids


def test_every_unit_is_embedded_exactly_once(reg_seeded):
    units = reg_seeded.scalars(
        select(LegalUnit).where(LegalUnit.regulation_code == "TEST-IR")).all()
    for u in units:
        rows = reg_seeded.scalars(
            select(LegalUnitEmbedding).where(LegalUnitEmbedding.unit_id == u.unit_id)).all()
        assert len(rows) == 1, f"{u.unit_id} has {len(rows)} embedding rows"


def test_a_real_cross_reference_becomes_a_relationship_row(reg_seeded):
    rel = reg_seeded.scalar(select(LegalRelationship).where(
        LegalRelationship.from_id == "TEST-IR-A49-P02",
        LegalRelationship.to_id == "TEST-IR-A51",
    ))
    assert rel is not None
    assert rel.relationship_type == "REFERENCES"


def test_reingesting_the_same_document_does_not_duplicate_rows(reg_seeded):
    before_units = reg_seeded.scalar(select(LegalUnit)) and len(
        reg_seeded.scalars(select(LegalUnit)).all())
    before_emb = len(reg_seeded.scalars(select(LegalUnitEmbedding)).all())
    before_rel = len(reg_seeded.scalars(select(LegalRelationship)).all())

    ingest_document(
        reg_seeded, source_path=FIXTURE, regulation_code="TEST-IR",
        content_type="IMPLEMENTING_REGULATION", effective_from=date(2020, 1, 1),
        authority="ZATCA", extractor=PlainTextExtractor(), provider=HashingEmbeddingProvider(),
    )
    reg_seeded.commit()

    assert len(reg_seeded.scalars(select(LegalUnit)).all()) == before_units
    assert len(reg_seeded.scalars(select(LegalUnitEmbedding)).all()) == before_emb
    assert len(reg_seeded.scalars(select(LegalRelationship)).all()) == before_rel


def test_content_type_and_authority_are_stamped_on_every_unit(reg_seeded):
    units = reg_seeded.scalars(
        select(LegalUnit).where(LegalUnit.regulation_code == "TEST-IR")).all()
    assert units
    assert all(u.content_type == "IMPLEMENTING_REGULATION" for u in units)
    assert all(u.authority == "ZATCA" for u in units)

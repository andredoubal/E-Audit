"""Test fixtures.

Most of the suite is pure — the pipeline, the adjudicator and the completeness checker are all
functions over data, and they need no database. Precedent and the planner do: they are
retrieval over a population, and testing them against a hand-built pair of rows would test the
fixture rather than the retrieval.

So this points the app at a throwaway SQLite database and seeds it once per session with the
real seeder. The env var must be set before `app.db` is imported, which is why nothing here is
imported at module scope. It is a temporary path, so a developer's local database is never at
risk of being dropped by running the tests.
"""
from __future__ import annotations

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="eaudit-tests-")
os.environ["EAUDIT_DATABASE_URL"] = f"sqlite:///{os.path.join(_TMP, 'main.db')}"
# No model is ever reached: without credentials `availability()` returns False and every
# feature degrades to its deterministic draft. `test_llm_path.py` stubs the SDK to exercise
# the live path, so the switch is deliberately NOT forced off here.
os.environ["EAUDIT_SKIP_REGULATORY_SEED"] = "1"
# The real-corpus ingestion in seed.py (~40s: 160 pages, bidi reconstruction) would otherwise
# run on every `seeded` fixture initialization for no benefit — the regulatory tests ingest
# their own small synthetic fixtures independently (see reg_seeded below).


@pytest.fixture(scope="session")
def seeded():
    """The demo database: 7 scenario cases, the dossier, and the 200-case precedent corpus."""
    from app.seed.seed import run

    run()
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def case(seeded):
    """The hero case — the one with a dossier, a prior audit and an issued request."""
    from sqlalchemy import select
    from app.models import AuditCase

    return seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0481"))


@pytest.fixture()
def reg_seeded(seeded):
    """The synthetic regulatory fixture, ingested into the same throwaway database — never the
    demo seed data. Uses HashingEmbeddingProvider (zero-network, pure numpy) so no model
    download is needed and the same provider is used everywhere else in the app."""
    from datetime import date
    from pathlib import Path

    from app.regulatory.embeddings import HashingEmbeddingProvider
    from app.regulatory.extract import PlainTextExtractor
    from app.regulatory.ingest import ingest_document

    fixture = Path(__file__).parent / "fixtures" / "regulatory" / "fake_vat_ir_excerpt.txt"
    ingest_document(
        seeded, source_path=fixture, regulation_code="TEST-IR",
        content_type="IMPLEMENTING_REGULATION", effective_from=date(2020, 1, 1),
        authority="ZATCA", extractor=PlainTextExtractor(), provider=HashingEmbeddingProvider(),
    )
    seeded.commit()
    return seeded

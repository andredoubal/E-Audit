"""Seeds the real KSA VAT Implementing Regulations into the regulatory schema.

Unlike the rest of seed.py (hand-built synthetic scenarios), this ingests an actual document —
`corpus/raw/Implementing Regulations of the VAT Law.pdf`, the Arabic authoritative text ZATCA
publishes. Re-runnable like the rest of the demo: `_persist` merges by unit_id, so re-seeding
re-derives the same rows rather than duplicating them.

The 2021 amendment PDF (`corpus/raw/VAT_IR Articles Changes - E-INV Changes (Arabic).pdf`) is
not ingested here — it has a different, table-based structure (digit-numbered articles, old/new
text columns) that arabic_chunker.py's article-header grammar doesn't parse. Real per-article
version history from that document is documented follow-up work, not attempted by this step.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from ..regulatory.ingest import ingest_arabic_document

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE_PDF = REPO_ROOT / "corpus" / "raw" / "Implementing Regulations of the VAT Law.pdf"

# The base Implementing Regulations was issued by GAZT Board Decision (3839), 14 Dhul Hijjah
# 1438H = 14 November 2016 (read from the PDF's own cover page). The PDF is the 10th,
# April-2025 consolidated edition — individual articles have been amended since 2016 by ~13
# board decisions this PDF does not itself date per-article, so this is the safest date this
# ingestion can assert without inventing precision it doesn't have.
BASE_EFFECTIVE_FROM = date(2016, 11, 14)


def build(db) -> dict:
    # Real-PDF extraction (~40s: 160 pages, bidi reconstruction) dwarfs every other seed step
    # combined, and the regulatory test suite doesn't need it — it ingests its own small
    # synthetic fixtures independently (see conftest.py's reg_seeded). Skipped in the test
    # environment by the same env-var-set-before-app.db-import convention conftest.py already
    # uses for EAUDIT_DATABASE_URL, so `pytest backend/tests` stays fast; `python -m
    # app.seed.seed` for the actual demo always ingests it.
    if os.getenv("EAUDIT_SKIP_REGULATORY_SEED") == "1":
        return {"seeded": False, "reason": "skipped (EAUDIT_SKIP_REGULATORY_SEED=1)"}
    if not SOURCE_PDF.exists():
        print(f"Regulatory corpus not found at {SOURCE_PDF} — skipping regulatory seed.")
        return {"seeded": False, "reason": "corpus file not found"}

    report = ingest_arabic_document(
        db,
        source_path=SOURCE_PDF,
        regulation_code="VAT-IR",
        content_type="IMPLEMENTING_REGULATION",
        effective_from=BASE_EFFECTIVE_FROM,
        authority="ZATCA",
    )
    return {
        "seeded": True,
        "units": report.units,
        "relationships": report.relationships,
        "warnings": report.warnings,
    }

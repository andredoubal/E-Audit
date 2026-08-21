"""regulatory schema — the legal corpus the Regulatory Knowledge Agent retrieves over.

Phase A: schema + ingestion/chunking/versioning/retrieval/citation pipeline, exercised only
against synthetic test fixtures (see backend/tests/fixtures/regulatory/) — no real ZATCA text
ships in this repo or this database yet. Phase B (real corpus, Excel case-analysis mode, wiring
into the Regulations agent / BLOCKED_TERMS) adds rows to the Layer-2/3 stub tables below without
touching Layer 1's shape.

Three layers (do not collapse them):
  Layer 1 — LegalUnit: the immutable legal text itself (article/paragraph/subparagraph), versioned.
  Layer 2 — RegulatoryInterpretation: what a legal unit means for audit purposes (stub in Phase A).
  Layer 3 — AuditTestRule: what an auditor should test against evidence (stub in Phase A).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import String, Integer, Text, Date, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

SCHEMA = "regulatory"

# content_type: what kind of text this is. The binding three may be cited as [[LAW:...]];
# everything else may only ever be cited as [[REF:...]] — enforced in llm/verify.py, not here.
CONTENT_TYPES = (
    "STATUTORY_TEXT", "IMPLEMENTING_REGULATION", "BOARD_DECISION",   # binding — Layer 1
    "OFFICIAL_GUIDANCE", "OFFICIAL_EXAMPLE", "FAQ",                  # non-binding, ZATCA-authored
    "INTERNAL_GUIDANCE", "AUDITOR_METHOD",                           # non-binding, ours
)
STATUTORY_CONTENT_TYPES = {"STATUTORY_TEXT", "IMPLEMENTING_REGULATION", "BOARD_DECISION"}

RELATIONSHIP_TYPES = (
    "REFERENCES", "SUBJECT_TO", "EXCEPTION_TO", "DEFINED_BY",
    "AMENDS", "REPLACES", "SUPERSEDES", "RELATED_TO", "IMPLEMENTS",
)

STATUS_ACTIVE = "ACTIVE"
STATUS_SUPERSEDED = "SUPERSEDED"
STATUS_NEEDS_VALIDATION = "NEEDS_LEGAL_VALIDATION"


class LegalUnit(Base):
    """One node of the legal hierarchy: an article, a paragraph, or a subparagraph.

    `unit_id` is the stable, human-legible ID (e.g. "VAT-IR-A49-P07"). `version_group` is the
    identifier shared by every version of the *same* provision over time — versioning.py
    filters on it. Chapter is descriptive metadata on the article row, not a separate node:
    nothing in this system ever retrieves at chapter granularity.
    """
    __tablename__ = "legal_unit"
    __table_args__ = {"schema": SCHEMA}

    unit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version_group: Mapped[str] = mapped_column(String(64), index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey(f"{SCHEMA}.legal_unit.unit_id"), nullable=True)

    regulation_code: Mapped[str] = mapped_column(String(30))          # "VAT-IR"
    level: Mapped[str] = mapped_column(String(20))                    # article/paragraph/subparagraph
    chapter_no: Mapped[str] = mapped_column(String(10), default="")
    chapter_title: Mapped[str] = mapped_column(String(200), default="")
    article_no: Mapped[str] = mapped_column(String(10), default="")
    paragraph_no: Mapped[str] = mapped_column(String(10), default="")
    subparagraph_no: Mapped[str] = mapped_column(String(10), default="")

    content_type: Mapped[str] = mapped_column(String(30))
    authority: Mapped[str] = mapped_column(String(60), default="")    # ZATCA / GAZT / ...
    title: Mapped[str] = mapped_column(String(300), default="")
    citation_label: Mapped[str] = mapped_column(String(200))          # "Article 49, Paragraph 7"
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(5), default="en")

    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default=STATUS_ACTIVE)

    source_document: Mapped[str] = mapped_column(String(300), default="")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    parent: Mapped[Optional["LegalUnit"]] = relationship(remote_side=[unit_id])


class LegalRelationship(Base):
    """Explicit cross-references, deliberately a plain table and not a graph database —
    the corpus is small enough that a relational table preserves the same semantics
    (from_id/to_id/relationship_type) without the added infrastructure."""
    __tablename__ = "legal_relationship"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    from_id: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.legal_unit.unit_id"), index=True)
    to_id: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.legal_unit.unit_id"), index=True)
    relationship_type: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(String(300), default="")


class LegalUnitEmbedding(Base):
    """Kept off LegalUnit so re-embedding with a new model never touches the legal text.

    Plain float array, not pgvector: pgvector isn't in the current docker-compose Postgres
    image, and at this corpus size (dozens to low hundreds of chunks) an in-memory brute-force
    cosine search (regulatory/retrieval.py) is simple, exact, and explainable — no ANN
    approximation to account for. Document pgvector as the swap-in once the corpus is large
    enough to need it.
    """
    __tablename__ = "legal_unit_embedding"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.legal_unit.unit_id"), index=True)
    model_name: Mapped[str] = mapped_column(String(120))
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list] = mapped_column(JSON)


class RetrievalTrace(Base):
    """Observability: every query's candidates, scores, chosen chunks and resolved version,
    inspectable via GET /api/regulatory/trace/{id}. Structured JSON, no hidden chain-of-thought."""
    __tablename__ = "retrieval_trace"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    query_text: Mapped[str] = mapped_column(Text)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    chosen_chunks: Mapped[list] = mapped_column(JSON, default=list)
    legal_version: Mapped[dict] = mapped_column(JSON, default=dict)
    answer_source: Mapped[str] = mapped_column(String(30), default="")
    verified: Mapped[Optional[bool]] = mapped_column(nullable=True)
    violations: Mapped[list] = mapped_column(JSON, default=list)


# ---------------------------------------------------- Layer 2/3 stubs (empty in Phase A) -----
class RegulatoryInterpretation(Base):
    """Layer 2: what a legal unit means for audit purposes. Empty until Phase B — kept here now
    so Phase B is additive rather than a rework of Layer 1."""
    __tablename__ = "regulatory_interpretation"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.legal_unit.unit_id"), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    applies_when: Mapped[dict] = mapped_column(JSON, default=dict)


class AuditTestRule(Base):
    """Layer 3: what an auditor should test against evidence. This is where
    agents/document_tests.py's BLOCKED_TERMS placeholder becomes a real lookup, in Phase B."""
    __tablename__ = "audit_test_rule"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    interpretation_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.regulatory_interpretation.id"))
    test_kind: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSON, default=dict)

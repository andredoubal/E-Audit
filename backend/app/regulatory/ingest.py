"""Ingestion: PDF/text -> extracted pages -> chunked LegalUnit rows -> embeddings ->
cross-reference relationships.

Two-pass, deliberately: units are persisted first, *then* cross-references are resolved —
so a reference to a not-yet-ingested target (a forward reference within the same document, or
a reference to a different document ingested later) is simply dropped, never guessed at. A
reference resolves only once its target actually exists as a row.

Two entry points, one shared persistence step: `ingest_document` (English/digit-numbered
grammar) and `ingest_arabic_document` (the real ZATCA Implementing Regulations' grammar —
spelled-out ordinal article numbers, RTL reconstruction). They differ only in extraction/
chunking/cross-reference-detection; `_persist` is identical either way.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..models.regulatory import LegalRelationship, LegalUnit, LegalUnitEmbedding, STATUS_ACTIVE
from .chunker import chunk, find_article_references, make_unit_id
from .embeddings import EmbeddingProvider, get_provider
from .extract import PdfplumberExtractor, TextExtractor


@dataclass
class IngestReport:
    units: int
    relationships: int
    source: str
    warnings: list[str]


def _persist(
    db, units: list[dict], *, regulation_code: str, content_type: str, effective_from: date,
    authority: str, lang: str, source_path, provider: EmbeddingProvider,
    find_refs,
) -> IngestReport:
    # Two chunks can share a unit_id (e.g. a title split across a page break re-triggers the
    # header match) — db.merge() does not reliably collapse duplicates within one uncommitted
    # batch, so dedupe explicitly here, keeping the last (most complete) occurrence, and record
    # it as a warning rather than silently overwriting.
    warnings: list[str] = []
    seen: dict[str, dict] = {}
    for u in units:
        if u["unit_id"] in seen:
            warnings.append(f"duplicate unit_id {u['unit_id']!r} — kept the later occurrence")
        seen[u["unit_id"]] = u
    units = list(seen.values())

    for u in units:
        db.merge(LegalUnit(
            unit_id=u["unit_id"],
            version_group=u["unit_id"],
            parent_id=u["parent_id"],
            regulation_code=regulation_code,
            level=u["level"],
            chapter_no=u["chapter_no"],
            chapter_title=u["chapter_title"],
            article_no=u["article_no"],
            paragraph_no=u["paragraph_no"],
            subparagraph_no=u["subparagraph_no"],
            content_type=content_type,
            authority=authority,
            title=u["title"],
            citation_label=u["citation_label"],
            text=u["text"],
            lang=u.get("lang", lang),
            effective_from=effective_from,
            effective_to=None,
            status=STATUS_ACTIVE,
            source_document=str(source_path),
        ))
    db.flush()

    # Re-embed only if no embedding exists yet for this unit/model pair — re-running ingestion
    # on an unchanged document should not silently multiply embedding rows.
    existing = {
        (row.unit_id, row.model_name)
        for row in db.query(LegalUnitEmbedding.unit_id, LegalUnitEmbedding.model_name).all()
    }
    to_embed = [u for u in units if (u["unit_id"], provider.MODEL) not in existing]
    if to_embed:
        vectors = provider.embed_passages([u["text"] for u in to_embed])
        for u, v in zip(to_embed, vectors):
            db.add(LegalUnitEmbedding(
                unit_id=u["unit_id"], model_name=provider.MODEL, dim=provider.dim, vector=v))
    db.flush()

    n_rel = 0
    existing_rel = {
        (r.from_id, r.to_id, r.relationship_type)
        for r in db.query(LegalRelationship.from_id, LegalRelationship.to_id,
                          LegalRelationship.relationship_type).all()
    }
    for u in units:
        for art_no in find_refs(u["text"], exclude_article=u["article_no"]):
            target = make_unit_id(regulation_code, art_no)
            if db.get(LegalUnit, target) is None:
                continue  # not (yet) ingested — dropped, never guessed at
            key = (u["unit_id"], target, "REFERENCES")
            if key in existing_rel:
                continue
            db.add(LegalRelationship(from_id=u["unit_id"], to_id=target,
                                     relationship_type="REFERENCES"))
            existing_rel.add(key)
            n_rel += 1
    db.flush()

    return IngestReport(units=len(units), relationships=n_rel, source=str(source_path),
                        warnings=warnings)


def ingest_document(
    db,
    *,
    source_path: str | Path,
    regulation_code: str,
    content_type: str,
    effective_from: date,
    authority: str = "",
    lang: str = "en",
    extractor: TextExtractor | None = None,
    provider: EmbeddingProvider | None = None,
) -> IngestReport:
    extractor = extractor or PdfplumberExtractor()
    provider = provider or get_provider()

    pages = extractor.extract(Path(source_path))
    full_text = "\n".join(p.text for p in pages)
    units = chunk(full_text, regulation_code=regulation_code)

    return _persist(db, units, regulation_code=regulation_code, content_type=content_type,
                    effective_from=effective_from, authority=authority, lang=lang,
                    source_path=source_path, provider=provider,
                    find_refs=find_article_references)


def ingest_arabic_document(
    db,
    *,
    source_path: str | Path,
    regulation_code: str,
    content_type: str,
    effective_from: date,
    authority: str = "",
    extractor: TextExtractor | None = None,
    provider: EmbeddingProvider | None = None,
    needs_bidi_reconstruction: bool = True,
) -> IngestReport:
    """The real ZATCA Implementing Regulations' grammar: spelled-out Arabic ordinal article
    numbers, RTL-reconstructed from pdfplumber's presentation-form extraction. Article-level
    granularity only — see arabic_chunker.py's module docstring for why.

    `needs_bidi_reconstruction` defaults to True (the real PDF's extraction needs it) — set it
    False for an extractor whose text is already in correct logical order, e.g.
    `PlainTextExtractor` reading a hand-written test fixture. Applying bidi reconstruction to
    already-correct text would scramble it, not fix it.
    """
    from .arabic_chunker import chunk_arabic, find_arabic_article_references, reconstruct_pages

    extractor = extractor or PdfplumberExtractor()
    provider = provider or get_provider()

    pages = extractor.extract(Path(source_path))
    page_texts = [p.text for p in pages]
    full_text = "\n".join(reconstruct_pages(page_texts) if needs_bidi_reconstruction
                          else [ln for t in page_texts for ln in t.split("\n") if ln.strip()])
    units, warnings = chunk_arabic(full_text, regulation_code=regulation_code)

    report = _persist(db, units, regulation_code=regulation_code, content_type=content_type,
                      effective_from=effective_from, authority=authority, lang="ar",
                      source_path=source_path, provider=provider,
                      find_refs=find_arabic_article_references)
    report.warnings.extend(warnings)
    return report

"""The Regulatory Knowledge Agent: pure deterministic Python — retrieval, version resolution,
relationship expansion. It never calls Claude. A separate function in `llm/service.py` (the
only allowed Claude boundary) does answer-synthesis over the structured `grounding` this
produces.

Contract: given a question (and optionally a tax period), return the legal text that answers
it, with citation, authority, effective version, and confidence already resolved — so the
language layer downstream has nothing left to decide about *which* law applies, only how to
explain it.
"""
from __future__ import annotations

from datetime import date

from ..models.regulatory import STATUS_NEEDS_VALIDATION, LegalUnit, RetrievalTrace
from .embeddings import EmbeddingProvider, get_provider
from .relationships import expand
from .retrieval import hybrid_retrieve
from .versioning import resolve_version


def _serialize_unit(unit: LegalUnit, *, status: str, score: float) -> dict:
    return {
        "unit_id": unit.unit_id,
        "citation_label": unit.citation_label,
        "content_type": unit.content_type,
        "text": unit.text,
        "authority": unit.authority,
        "effective_from": unit.effective_from.isoformat(),
        "effective_to": unit.effective_to.isoformat() if unit.effective_to else None,
        "status": status,
        "score": score,
    }


def answer_query(
    db, question: str, *, regulation_code: str = "VAT-IR",
    tax_period: date | None = None, top_k: int = 8,
    provider: EmbeddingProvider | None = None,
) -> tuple[dict, int]:
    provider = provider or get_provider()
    candidates = hybrid_retrieve(
        db, question, regulation_code=regulation_code, provider=provider, top_k=top_k)

    cited_units: list[dict] = []
    legal_version: dict[str, dict] = {}
    for c in candidates:
        unit = db.get(LegalUnit, c.unit_id)
        if unit is None:
            continue
        resolved = resolve_version(db, unit.version_group, tax_period)
        needs_validation = resolved is None
        resolved = resolved or unit
        status = STATUS_NEEDS_VALIDATION if needs_validation else resolved.status
        legal_version[c.unit_id] = {"resolved_unit_id": resolved.unit_id, "status": status}

        exp = expand(db, resolved)
        entry = _serialize_unit(resolved, status=status, score=c.fused)
        entry["parent"] = (
            _serialize_unit(exp["parent"], status=exp["parent"].status, score=0.0)
            if exp["parent"] else None
        )
        entry["related"] = [
            {"type": t, "unit_id": u.unit_id, "citation_label": u.citation_label}
            for t, u in exp["related"]
        ]
        cited_units.append(entry)

    grounding = {
        "query": question,
        "tax_period": tax_period.isoformat() if tax_period else None,
        "cited_units": cited_units,
    }

    trace = RetrievalTrace(
        query_text=question,
        filters={"regulation_code": regulation_code, "tax_period": grounding["tax_period"]},
        candidates=[
            {"unit_id": c.unit_id, "lexical": c.lexical, "vector": c.vector,
             "exact": c.exact, "fused": c.fused}
            for c in candidates
        ],
        chosen_chunks=[u["unit_id"] for u in cited_units],
        legal_version=legal_version,
    )
    db.add(trace)
    db.flush()

    return grounding, trace.id


def grounding_from_trace(db, trace: RetrievalTrace) -> dict:
    """Re-hydrates a past trace's grounding from the persisted chosen_chunks + legal_version,
    rather than re-running retrieval — so the streamed explanation always matches exactly what
    the citations panel already showed the user, even if the corpus changes in between."""
    cited_units: list[dict] = []
    for unit_id in trace.chosen_chunks:
        unit = db.get(LegalUnit, unit_id)
        if unit is None:
            continue
        status = (trace.legal_version.get(unit_id) or {}).get("status", unit.status)
        cand = next((c for c in trace.candidates if c["unit_id"] == unit_id), None)
        score = cand["fused"] if cand else 0.0
        exp = expand(db, unit)
        entry = _serialize_unit(unit, status=status, score=score)
        entry["parent"] = (
            _serialize_unit(exp["parent"], status=exp["parent"].status, score=0.0)
            if exp["parent"] else None
        )
        entry["related"] = [
            {"type": t, "unit_id": u.unit_id, "citation_label": u.citation_label}
            for t, u in exp["related"]
        ]
        cited_units.append(entry)

    return {
        "query": trace.query_text,
        "tax_period": trace.filters.get("tax_period"),
        "cited_units": cited_units,
    }

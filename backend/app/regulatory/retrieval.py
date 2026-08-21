"""Hybrid retrieval: exact article-number match + lexical term-overlap + vector cosine
similarity, combined by a deterministic weighted fusion.

Explicitly not a learned reranker: at this corpus size (dozens to low hundreds of chunks), a
cross-encoder adds a new model dependency and latency for no real gain, and — same reasoning as
`precedent/index.py` — an auditor has to be able to see why something ranked where it did.
Named weights that sum to 1.0 and a stable sort are the whole scoring story.

Lexical search is pure-Python term overlap, not Postgres `tsvector`: the test suite runs
against SQLite (conftest.py), which has no `tsvector` equivalent, and a dialect-specific
lexical implementation would mean either an untested code path or two diverging
implementations. This applies the same "load into memory, score in Python" approach already
used for vector search to lexical search too.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select

from ..models.regulatory import LegalUnit, LegalUnitEmbedding
from .embeddings import EmbeddingProvider

W_EXACT, W_VECTOR, W_LEXICAL = 0.50, 0.30, 0.20
assert abs((W_EXACT + W_VECTOR + W_LEXICAL) - 1.0) < 1e-9

ARTICLE_QUERY_RE = re.compile(r"article\s+(\d+)", re.I)
_WORD_RE = re.compile(r"\w+")
# Arabic single-letter prefixes (و=and, ف=so, ب=by/with, ك=like, ل=for, ال=the) attach directly
# to the following word with no space, so "بخصم" (a query's "[with] deduction") and "خصم" (an
# article's own "deduction") never share a token without this — a light, standard technique in
# Arabic IR, well short of full morphological stemming (which is out of scope here).
_AR_PREFIX_RE = re.compile(r"^(?:وال|فال|بال|كال|لل|ال|و|ف|ب|ك|ل)(?=.{2,})")


def _light_stem(word: str) -> str:
    return _AR_PREFIX_RE.sub("", word)


@dataclass
class Candidate:
    unit_id: str
    lexical: float
    vector: float
    exact: float
    fused: float


_AR_ARTICLE_DIGIT_RE = re.compile(r"المادة\s*\(?\s*(\d+)\s*\)?")
_AR_ARTICLE_ORDINAL_RE = re.compile(r"المادة\s+([؀-ۿ]{2,25}(?:\s+عشرة)?(?:\s+و[؀-ۿ]{2,15})?)")


def exact_match(db, query: str, regulation_code: str) -> set[str]:
    """"Article 49" (English, digits) or "المادة 49" / "المادة التاسعة والأربعون" (Arabic,
    digits or spelled-out ordinal) in the query text -> the unit_id for that article, if it
    exists."""
    from .arabic_ordinals import parse_ordinal
    from .chunker import make_unit_id

    nums = set(ARTICLE_QUERY_RE.findall(query or "")) | set(_AR_ARTICLE_DIGIT_RE.findall(query or ""))
    for m in _AR_ARTICLE_ORDINAL_RE.findall(query or ""):
        # The Arabic-block character class also matches Arabic punctuation (؟ ، etc.), which
        # can end up glued onto the end of a greedy capture — strip it before ordinal lookup.
        n = parse_ordinal(m.strip().rstrip("؟،؛.!? \t"))
        if n is not None:
            nums.add(str(n))

    out = set()
    for n in nums:
        uid = make_unit_id(regulation_code, n)
        if db.get(LegalUnit, uid) is not None:
            out.add(uid)
    return out


def lexical_search(db, query: str, *, regulation_code: str) -> dict[str, float]:
    terms = {_light_stem(w) for w in _WORD_RE.findall((query or "").lower())}
    if not terms:
        return {}
    scores: dict[str, float] = {}
    units = db.scalars(
        select(LegalUnit).where(LegalUnit.regulation_code == regulation_code)).all()
    for u in units:
        body = {_light_stem(w) for w in _WORD_RE.findall((u.text or "").lower())}
        overlap = terms & body
        if overlap:
            # Jaccard, not hits/len(terms): a real omnibus "transitional provisions" article
            # (134k characters, touching nearly every topic) scored 1.0 under plain overlap —
            # it contains every query term somewhere, so it "wins" against short, specific
            # articles purely by being huge. Dividing by the UNION size penalizes exactly that:
            # a big, generic vocabulary lowers the score unless the overlap is proportionally
            # large too.
            scores[u.unit_id] = len(overlap) / len(terms | body)
    return scores


def vector_search(db, query_vec: list[float], *, regulation_code: str,
                   top_k: int = 20) -> dict[str, float]:
    rows = db.execute(
        select(LegalUnitEmbedding.unit_id, LegalUnitEmbedding.vector)
        .join(LegalUnit, LegalUnit.unit_id == LegalUnitEmbedding.unit_id)
        .where(LegalUnit.regulation_code == regulation_code)
    ).all()
    if not rows:
        return {}
    mat = np.array([r.vector for r in rows], dtype=np.float64)
    q = np.array(query_vec, dtype=np.float64)
    denom = np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) + 1e-12)
    denom[denom == 0] = 1e-12
    sims = (mat @ q) / denom
    order = np.argsort(-sims)[:top_k]
    return {rows[i].unit_id: float(sims[i]) for i in order}


def hybrid_retrieve(db, query: str, *, regulation_code: str, provider: EmbeddingProvider,
                     top_k: int = 8) -> list[Candidate]:
    exact_ids = exact_match(db, query, regulation_code)
    lex = lexical_search(db, query, regulation_code=regulation_code)
    vec = vector_search(db, provider.embed_query(query), regulation_code=regulation_code)

    ids = set(lex) | set(vec) | exact_ids
    out = []
    for uid in ids:
        e = 1.0 if uid in exact_ids else 0.0
        v = vec.get(uid, 0.0)
        l = lex.get(uid, 0.0)
        out.append(Candidate(uid, lexical=l, vector=v, exact=e,
                             fused=round(W_EXACT * e + W_VECTOR * v + W_LEXICAL * l, 6)))
    out.sort(key=lambda c: (-c.fused, c.unit_id))  # stable, reproducible ordering
    return out[:top_k]

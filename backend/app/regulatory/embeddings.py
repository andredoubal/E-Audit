"""Local, no-API-key embedding providers.

Not Anthropic (no first-party embeddings endpoint) and not a paid external vendor — consistent
with the rest of the app working with zero credentials, and it avoids sending legal text to a
third vendor unnecessarily.

Two providers, one interface:

- `HashingEmbeddingProvider` (default): a character-trigram hashing vector (the "hashing
  trick"), pure numpy, needs no model download, ever. This is deliberate, not a shortcut taken
  for lack of time: a live check in this environment found that huggingface.co (and every other
  external content host tried) is blocked by the sandbox's network policy — see the proxy's own
  `recentRelayFailures`. A POC whose retrieval quietly breaks the first time it runs somewhere
  without model-hub access is a worse default than one with weaker semantic recall that always
  works, matching this app's existing "every deterministic fallback is complete, sendable
  output" discipline. It has no true cross-lingual understanding — it is a token/character
  similarity signal, not semantic — so it is deliberately only one of three signals in
  `retrieval.hybrid_retrieve` (alongside exact-match and lexical overlap), never the sole one.
- `FastEmbedProvider` (optional upgrade): a real multilingual neural embedding model via
  `fastembed` (ONNX runtime, no PyTorch), for a deployment with normal internet access on first
  run. Not installed by default — `pip install fastembed` to enable it, then point
  `EAUDIT_REGULATORY_EMBEDDING_PROVIDER=fastembed` at it (see config.py).
"""
from __future__ import annotations

import hashlib
from typing import Protocol

import numpy as np


class EmbeddingProvider(Protocol):
    MODEL: str
    dim: int

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashingEmbeddingProvider:
    MODEL = "hashing-trigram-v1"
    dim = 256

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float64)
        text = (text or "").lower()
        grams = [text[i : i + 3] for i in range(len(text) - 2)] or ([text] if text else [])
        for g in grams:
            idx = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % self.dim
            v[idx] += 1.0
        norm = np.linalg.norm(v)
        return (v / norm if norm > 0 else v).tolist()


class FastEmbedProvider:
    """Optional upgrade — requires `pip install fastembed` and, on first run, internet access
    to download the model. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`: small
    (384-dim), ONNX (no PyTorch), covers Arabic — relevant once bilingual retrieval is in scope.
    """

    MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    dim = 384

    def __init__(self):
        from fastembed import TextEmbedding  # deferred: only imported if this provider is used

        self._model = TextEmbedding(model_name=self.MODEL)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return next(self._model.embed([text])).tolist()


_provider: EmbeddingProvider | None = None


def get_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        from ..config import settings

        name = getattr(settings, "regulatory_embedding_provider", "hashing")
        _provider = FastEmbedProvider() if name == "fastembed" else HashingEmbeddingProvider()
    return _provider

"""On-device sentence embeddings (Apple Natural Language) for paraphrase-tolerant recall."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np

LOG = logging.getLogger(__name__)

Embedder = Callable[[str], np.ndarray | None]


def local_embedder(model: str = "BAAI/bge-small-en-v1.5") -> Embedder:
    """A small sentence-embedding model run locally (ONNX). ~3 ms per short text on M-series."""
    from fastembed import TextEmbedding

    engine = TextEmbedding(model)

    def embed(text: str) -> np.ndarray | None:
        for v in engine.embed([text]):
            a = np.asarray(v, dtype=np.float32)
            n = float(np.linalg.norm(a))
            return a / n if n else None
        return None

    return embed


def default_embedder() -> Embedder | None:
    """Best available: the local model, else Apple's built-in, else none (lexical only)."""
    for factory in (local_embedder, apple_embedder):
        try:
            return factory()
        except Exception as e:  # noqa: BLE001 - a missing model or framework just drops a tier
            LOG.warning("embedder %s unavailable: %s", factory.__name__, type(e).__name__)
    return None


def apple_embedder() -> Embedder:
    """macOS's built-in English sentence embedding (512-d). ~7 ms per string, no network."""
    import NaturalLanguage as NL

    model: Any = NL.NLEmbedding.sentenceEmbeddingForLanguage_("en")

    def embed(text: str) -> np.ndarray | None:
        if model is None:
            return None
        v = model.vectorForString_(text)
        if v is None:
            return None
        a = np.asarray(list(v), dtype=np.float32)
        n = float(np.linalg.norm(a))
        return a / n if n else None

    return embed


class EmbeddingCache:
    """Memoises unit vectors per text so repeated candidates (menus) cost nothing."""

    def __init__(self, embed: Embedder) -> None:
        self._embed = embed
        self._cache: dict[str, np.ndarray | None] = {}

    def get(self, text: str) -> np.ndarray | None:
        if text not in self._cache:
            self._cache[text] = self._embed(text)
        return self._cache[text]


def cosine(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 0.0
    return float(np.dot(a, b))  # both unit-normalised


def rank_fusion(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal rank fusion: keys that rank well under any signal float to the top."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for i, key in enumerate(ranking):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + i + 1)
    return sorted(scores, key=lambda key: (-scores[key], key))

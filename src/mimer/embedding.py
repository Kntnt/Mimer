"""Local, lightweight embeddings for semantic recall (ADR 0006).

Mimer embeds with model2vec's static ``potion-base-8M`` model: a small,
CPU-only, dependency-light model (no ONNX runtime, no service) that is fast
enough to embed inline during capture and deterministic enough that a reindex
reproduces identical results. Vectors are unit-normalised so a plain L2 distance
in the index reads back as cosine similarity.

Settled decisions (recorded in the vision's open-decisions list): model
``minishlab/potion-base-8M``, 256 dimensions, one chunk per Markdown heading
block of the daily long-term logs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from model2vec import StaticModel

MODEL_NAME = "minishlab/potion-base-8M"
EMBEDDING_DIMENSIONS = 256


@lru_cache(maxsize=1)
def _model() -> StaticModel:
    """Load and cache the embedding model (downloaded once, then cached by HF)."""

    from model2vec import StaticModel

    return StaticModel.from_pretrained(MODEL_NAME)


def embed(texts: list[str]) -> list[list[float]]:
    """Embed texts into unit-normalised 256-dimensional vectors."""

    import numpy as np

    vectors = np.asarray(_model().encode(list(texts)), dtype="float32")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    normalised = vectors / np.clip(norms, 1e-12, None)
    result: list[list[float]] = normalised.tolist()
    return result

"""Synopsis embeddings.

Structured genres and tags only match when two sources happen to use the same
word, and they largely do not: TMDB and IGDB agree on ~14% of their tag
vocabulary even after canonicalization. So "a game like this show" could only
ever be answered on broad genre overlap. Embedding each title's synopsis turns
meaning into a vector, which is what lets a dragon/kingdom/intrigue show sit
near a medieval/magic/sword game without either sharing a token.

all-MiniLM-L6-v2: 384 dimensions, runs locally, no API key, no per-call cost.
The dimension is baked into the `embedding vector(384)` column, so changing
models means a migration.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from .models import CatalogItem

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384


@lru_cache(maxsize=1)
def _model():
    """Loaded on first use, not at import: the API should boot without paying a
    model load, and the test suite should never pay it at all."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def text_for(item: CatalogItem) -> str:
    """What actually gets embedded.

    The title carries real signal ("Dark Souls", "The Silmarillion") and is the
    only signal at all for the 56 books Open Library has no description for, so
    it leads. Genres are left out on purpose - they already have their own
    weighted block, and repeating them here would double-count them.
    """
    parts = [item.title]
    if item.overview.strip():
        parts.append(item.overview.strip())
    return ". ".join(parts)


def encode(texts: list[str], batch_size: int = 64) -> np.ndarray:
    """Embed texts into unit-length vectors, so a dot product is a cosine."""
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    vecs = _model().encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(vecs, dtype=np.float32)


def encode_items(items: list[CatalogItem], batch_size: int = 64) -> dict[str, np.ndarray]:
    """id -> unit embedding, for items worth embedding."""
    usable = [i for i in items if text_for(i).strip()]
    if not usable:
        return {}
    vecs = encode([text_for(i) for i in usable], batch_size=batch_size)
    return {it.id: vecs[n] for n, it in enumerate(usable)}

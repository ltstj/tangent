"""Content-based recommender (Phase 1).

Each title becomes a vector: a multi-hot of its unified genre/tag tokens (the
dominant signal) plus a couple of normalized numeric metrics (rating, era). A
user's taste is the average of their favorites' vectors; recommendations are the
nearest catalog items by cosine similarity, filtered to the medium(s) asked for.

Because the token vocabulary is shared across media, a movie and a game with the
same genres/themes sit near each other automatically, which is what powers the
cross-media jump. (Phase 2 adds synopsis embeddings on top of this.)
"""
from __future__ import annotations

import datetime as _dt
from typing import Iterable

import numpy as np

from .models import CatalogItem, Medium

# How much categorical taste (genres/tags) counts vs numeric metrics.
W_CATEGORICAL = 1.0
W_RATING = 0.25
W_ERA = 0.15
# The era scale is fixed (not Date.now-derived) so results are deterministic.
_ERA_MIN, _ERA_MAX = 1950, 2030


def _era_norm(year: int | None) -> float:
    if not year:
        return 0.5
    y = max(_ERA_MIN, min(_ERA_MAX, year))
    return (y - _ERA_MIN) / (_ERA_MAX - _ERA_MIN)


class TasteModel:
    def __init__(self, items: Iterable[CatalogItem]) -> None:
        self.items: list[CatalogItem] = list(items)
        self.index: dict[str, int] = {it.id: i for i, it in enumerate(self.items)}
        vocab = sorted({tok for it in self.items for tok in it.taste_tokens()})
        self.vocab: dict[str, int] = {tok: i for i, tok in enumerate(vocab)}
        self.matrix = np.zeros((len(self.items), len(vocab) + 2), dtype=np.float32)
        for i, it in enumerate(self.items):
            self.matrix[i] = self._vector(it)

    def _vector(self, item: CatalogItem) -> np.ndarray:
        vec = np.zeros(len(self.vocab) + 2, dtype=np.float32)
        toks = [self.vocab[t] for t in item.taste_tokens() if t in self.vocab]
        if toks:
            # L2-normalize the categorical block so titles with many tags don't dominate.
            cat = np.zeros(len(self.vocab), dtype=np.float32)
            cat[toks] = 1.0
            cat /= np.linalg.norm(cat)
            vec[: len(self.vocab)] = cat * W_CATEGORICAL
        rating = (item.rating if item.rating is not None else 5.0) / 10.0
        vec[-2] = rating * W_RATING
        vec[-1] = _era_norm(item.year) * W_ERA
        return vec

    def recommend(
        self,
        favorite_ids: list[str],
        target_media: list[Medium] | None = None,
        limit: int = 12,
    ) -> list[dict]:
        known = [fid for fid in favorite_ids if fid in self.index]
        if not known:
            return []
        taste = self.matrix[[self.index[fid] for fid in known]].mean(axis=0)
        taste_n = taste / (np.linalg.norm(taste) or 1.0)

        norms = np.linalg.norm(self.matrix, axis=1)
        norms[norms == 0] = 1.0
        scores = (self.matrix @ taste_n) / norms

        fav_items = [self.items[self.index[fid]] for fid in known]
        fav_genres = {g for it in fav_items for g in it.genres}
        fav_tags = {t for it in fav_items for t in it.tags}
        exclude = set(known)

        ranked = np.argsort(-scores)
        out: list[dict] = []
        for i in ranked:
            it = self.items[int(i)]
            if it.id in exclude:
                continue
            if target_media and it.medium not in target_media:
                continue
            out.append({
                "item": it,
                "score": round(float(scores[int(i)]), 4),
                "reasons": self._reasons(it, fav_genres, fav_tags),
            })
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _reasons(item: CatalogItem, fav_genres: set[str], fav_tags: set[str]) -> list[str]:
        shared_g = [g for g in item.genres if g in fav_genres]
        shared_t = [t for t in item.tags if t in fav_tags]
        reasons = []
        if shared_g:
            reasons.append("shares " + ", ".join(shared_g[:3]))
        if shared_t:
            reasons.append("themes: " + ", ".join(shared_t[:3]))
        return reasons

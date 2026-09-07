"""Content-based recommender (Phase 1).

Each title becomes several independent blocks: a multi-hot of its unified genre
tokens (the dominant signal), a multi-hot of its theme tags, and a couple of
normalized numeric metrics (rating, era). The score is a weighted blend of the
per-block similarities, as ROADMAP.md describes, and a user's taste is the
per-block average of their favorites.

Blending per block rather than cosine-ing one concatenated vector is what keeps
cross-media honest. Sources are wildly uneven in how many tags they supply (TMDB
gives none, Open Library a dozen), and under a single cosine those extra tags
inflate the vector norm, so a tag-rich book scored below a tag-less movie even
when both matched the query genre exactly. Per-block, one shared genre is worth
the same to a book as to a movie.

Because the token vocabulary is shared across media, a movie and a game with the
same genres/themes sit near each other automatically, which is what powers the
cross-media jump. (Phase 2 adds synopsis embeddings on top of this.)
"""
from __future__ import annotations

import datetime as _dt
from typing import Iterable

import numpy as np

from .models import CatalogItem, Medium

# How much each block of taste counts. Genres and tags are weighted and
# normalized *separately* on purpose: sources are wildly uneven in how many tags
# they supply (TMDB gives none, Open Library gives a dozen), and normalizing them
# together let a verbose source dilute its own genre signal until its titles
# stopped matching anything cross-media. Splitting the blocks makes one shared
# genre worth the same to a book as to a movie.
# W_TAG keeps genre dominant while leaving tags decisive between titles that
# share a genre (below ~0.45 the seed cases regress: Game of Thrones stops
# matching The Witcher 3 and drifts to whatever shares the generic 'action').
W_GENRE = 1.0
W_TAG = 0.6
# Synopsis embeddings (see embed.py). This is the block that answers "a game
# like this show": genres and tags only match on a shared literal token, and the
# sources agree on ~14% of each other's tag vocabulary, so meaning has to carry
# the rest. Weighted near genre because it is the more reliable cross-media
# signal of the two, but not above it - a semantic near-miss should not outrank
# an actual genre match.
W_EMBED = 0.9
W_RATING = 0.25
W_ERA = 0.15
# The era scale is fixed (not Date.now-derived) so results are deterministic.
_ERA_MIN, _ERA_MAX = 1950, 2030


def _unit(vec: np.ndarray) -> np.ndarray:
    """L2-normalize, tolerating an all-zero block (an item with no tags)."""
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def _idf(items: list[CatalogItem], vocab: dict[str, int], tokens_of) -> np.ndarray:
    """Inverse document frequency per token.

    Without it every token counts the same, so sharing "action" (29% of the
    catalog) looks as meaningful as sharing "cyberpunk" (one title), and generic
    blockbusters crowd out the title that matches on something distinctive.
    """
    df = np.zeros(len(vocab), dtype=np.float32)
    for it in items:
        for t in set(tokens_of(it)):
            i = vocab.get(t)
            if i is not None:
                df[i] += 1.0
    return np.log(1.0 + len(items) / np.maximum(df, 1.0)).astype(np.float32)


def _fill_unit(row: np.ndarray, tokens: list[str], vocab: dict[str, int],
               idf: np.ndarray) -> None:
    """Write a unit-length, IDF-weighted multi-hot of `tokens` into `row`, in place."""
    idx = [vocab[t] for t in tokens if t in vocab]
    if not idx:
        return
    row[idx] = idf[idx]
    norm = float(np.linalg.norm(row))
    if norm:
        row /= norm


def _era_norm(year: int | None) -> float:
    if not year:
        return 0.5
    y = max(_ERA_MIN, min(_ERA_MAX, year))
    return (y - _ERA_MIN) / (_ERA_MAX - _ERA_MIN)


class TasteModel:
    def __init__(
        self,
        items: Iterable[CatalogItem],
        embeddings: dict[str, np.ndarray] | None = None,
    ) -> None:
        self.items: list[CatalogItem] = list(items)
        self.index: dict[str, int] = {it.id: i for i, it in enumerate(self.items)}
        g_vocab = sorted({tok for it in self.items for tok in it.genre_tokens()})
        t_vocab = sorted({tok for it in self.items for tok in it.tag_tokens()})
        self.genre_vocab: dict[str, int] = {tok: i for i, tok in enumerate(g_vocab)}
        self.tag_vocab: dict[str, int] = {tok: i for i, tok in enumerate(t_vocab)}

        self.genre_idf = _idf(self.items, self.genre_vocab, lambda it: it.genre_tokens())
        self.tag_idf = _idf(self.items, self.tag_vocab, lambda it: it.tag_tokens())

        n = len(self.items)
        self.genres = np.zeros((n, len(g_vocab)), dtype=np.float32)
        self.tags = np.zeros((n, len(t_vocab)), dtype=np.float32)
        self.rating = np.zeros(n, dtype=np.float32)
        self.era = np.zeros(n, dtype=np.float32)
        # Zero rows for items with no embedding yet: a zero block contributes
        # nothing rather than skewing the score, so partial coverage degrades
        # gracefully instead of ranking un-embedded titles oddly.
        vecs = embeddings or {}
        dim = len(next(iter(vecs.values()))) if vecs else 0
        self.embed = np.zeros((n, dim), dtype=np.float32)

        for i, it in enumerate(self.items):
            _fill_unit(self.genres[i], it.genre_tokens(), self.genre_vocab, self.genre_idf)
            _fill_unit(self.tags[i], it.tag_tokens(), self.tag_vocab, self.tag_idf)
            self.rating[i] = (it.rating if it.rating is not None else 5.0) / 10.0
            self.era[i] = _era_norm(it.year)
            v = vecs.get(it.id)
            if v is not None and dim:
                self.embed[i] = v

    def recommend(
        self,
        favorite_ids: list[str],
        target_media: list[Medium] | None = None,
        limit: int = 12,
    ) -> list[dict]:
        known = [fid for fid in favorite_ids if fid in self.index]
        if not known:
            return []
        rows = [self.index[fid] for fid in known]

        # Taste = per-block average of the favorites, each block re-normalized so
        # one block's magnitude can't borrow weight from another.
        g_taste = _unit(self.genres[rows].mean(axis=0))
        t_taste = _unit(self.tags[rows].mean(axis=0))
        r_taste = float(self.rating[rows].mean())
        e_taste = float(self.era[rows].mean())

        scores = (
            W_GENRE * (self.genres @ g_taste)
            + W_TAG * (self.tags @ t_taste)
            + W_RATING * (1.0 - np.abs(self.rating - r_taste))
            + W_ERA * (1.0 - np.abs(self.era - e_taste))
        )
        if self.embed.shape[1]:
            scores = scores + W_EMBED * (self.embed @ _unit(self.embed[rows].mean(axis=0)))

        fav_items = [self.items[r] for r in rows]
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

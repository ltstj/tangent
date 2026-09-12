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
# Collaborative filtering, scaled by how much interaction data exists (see
# collab.confidence). Deliberately capable of outweighing a tag match but not a
# genre one: "other people liked both" is a strong hint and a poor veto - it
# knows nothing about what either title actually is.
W_COLLAB = 0.7
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

    def _genre_seed(self, genres: list[str]) -> np.ndarray:
        """A taste vector built from bare genre names, for cold start.

        Someone with no favorites yet can still say "I like fantasy and
        mystery"; that is a point in the same genre space a favorite would
        occupy, just without tags or a synopsis behind it.
        """
        toks = [f"g:{g.strip().lower()}" for g in genres]
        vec = np.zeros(len(self.genre_vocab), dtype=np.float32)
        _fill_unit(vec, toks, self.genre_vocab, self.genre_idf)
        return vec

    def recommend(
        self,
        favorite_ids: list[str],
        target_media: list[Medium] | None = None,
        limit: int = 12,
        seed_genres: list[str] | None = None,
        filter_genres: list[str] | None = None,
        genre_weight: float | None = None,
        weights: dict[str, float] | None = None,
        exclude_ids: set[str] | None = None,
        collab_scores: dict[str, float] | None = None,
    ) -> list[dict]:
        """Rank the catalog against a taste.

        seed_genres    - cold start: taste from genre names when there are no
                         favorites yet (also blended in when there are).
        filter_genres  - restrict results to items carrying any of these genres.
                         A filter, not a preference: it never changes the score.
        genre_weight   - the "genre versus tone" lever, 0..1. 0 leans entirely on
                         tone (themes and synopsis meaning), 1 entirely on genre,
                         and 0.5 is the tuned default. Implemented as a
                         multiplier on the existing block weights, so the lever
                         moves the same knobs the score is already built from.
        weights        - signed per-item pull from a user's library: positive
                         moves the taste vector towards a title, negative away.
                         See taste.weights_from_library.
        exclude_ids    - never recommend these. Anything already in the library
                         is a poor recommendation however well it scores.
        collab_scores  - item -> collaborative score from collab.scores_for.
                         Blended on top, weighted by W_COLLAB.
        """
        known = [fid for fid in favorite_ids if fid in self.index]
        seeds = [g for g in (seed_genres or []) if f"g:{g.strip().lower()}" in self.genre_vocab]
        # A signed weight per item: positive pulls the taste vector towards it,
        # negative pushes away. Favorites are simply weight 1.0.
        signed: dict[int, float] = {self.index[fid]: 1.0 for fid in known}
        for item_id, w in (weights or {}).items():
            row = self.index.get(item_id)
            if row is not None:
                signed[row] = signed.get(row, 0.0) + float(w)
        if not signed and not seeds:
            return []
        # Every weighted item contributes, negatives included - that is what
        # makes a dislike push rather than merely be ignored.
        rows = list(signed)
        # ...unless nothing is liked at all. A vector built only from dislikes
        # points away from everything, which ranks by anti-taste and is not a
        # recommendation. In that case the categorical blocks sit this one out
        # and the score falls back to rating/era, i.e. "we don't know you yet" -
        # while the dislikes still count as exclusions.
        liked = any(w > 0 for w in signed.values())

        g_mult, tone_mult = 1.0, 1.0
        if genre_weight is not None:
            gw = min(1.0, max(0.0, float(genre_weight)))
            g_mult, tone_mult = 2.0 * gw, 2.0 * (1.0 - gw)

        # Taste = per-block average of the favorites, each block re-normalized so
        # one block's magnitude can't borrow weight from another.
        if rows and liked:
            w = np.array([signed.get(r, 1.0) for r in rows], dtype=np.float32)
            g_taste = _unit(w @ self.genres[rows])
            t_taste = _unit(w @ self.tags[rows])
            # Rating and era describe *what you like*, so only liked items vote:
            # a disliked title's release year is not a preference to move away
            # from, and a negative weight here would skew both towards nonsense.
            pos = np.clip(w, 0.0, None)
            mass = float(pos.sum()) or 1.0
            r_taste = float(pos @ self.rating[rows] / mass)
            e_taste = float(pos @ self.era[rows] / mass)
        else:
            # Cold start: no tags, no synopsis, no rating/era preference.
            g_taste = np.zeros(len(self.genre_vocab), dtype=np.float32)
            t_taste = np.zeros(len(self.tag_vocab), dtype=np.float32)
            r_taste, e_taste = 0.7, 0.5   # nudge towards well-rated, era-neutral
        if seeds:
            g_taste = _unit(g_taste + self._genre_seed(seeds))

        scores = (
            W_GENRE * g_mult * (self.genres @ g_taste)
            + W_TAG * tone_mult * (self.tags @ t_taste)
            + W_RATING * (1.0 - np.abs(self.rating - r_taste))
            + W_ERA * (1.0 - np.abs(self.era - e_taste))
        )
        if self.embed.shape[1] and rows and liked:
            w_e = np.array([signed.get(r, 1.0) for r in rows], dtype=np.float32)
            scores = scores + W_EMBED * tone_mult * (self.embed @ _unit(w_e @ self.embed[rows]))

        if collab_scores:
            collab = np.zeros(len(self.items), dtype=np.float32)
            for item_id, value in collab_scores.items():
                row = self.index.get(item_id)
                if row is not None:
                    collab[row] = value
            scores = scores + W_COLLAB * collab

        fav_items = [self.items[r] for r in rows]
        fav_genres = {g for it in fav_items for g in it.genres} | {
            g.strip().lower() for g in seeds
        }
        fav_tags = {t for it in fav_items for t in it.tags}
        # Everything that shaped the taste is excluded, plus anything the caller
        # named - a title already in your library is a poor recommendation.
        exclude = {self.items[r].id for r in signed} | set(exclude_ids or set())
        wanted = {g.strip().lower() for g in (filter_genres or [])}

        ranked = np.argsort(-scores)
        out: list[dict] = []
        for i in ranked:
            it = self.items[int(i)]
            if it.id in exclude:
                continue
            if target_media and it.medium not in target_media:
                continue
            if wanted and not wanted.intersection(it.genres):
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

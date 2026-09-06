"""Unified taste vocabulary.

Each source speaks its own genre language. We fold them into one shared set so a
sci-fi movie, a sci-fi game, and a sci-fi novel share the token "scifi" and can
be compared. Unknown labels pass through as lowercased slugs (still useful as
tags), so nothing is lost when a mapping is missing.
"""
from __future__ import annotations

import re

# The shared genre vocabulary the app reasons about.
UNIFIED_GENRES = {
    "action", "adventure", "animation", "comedy", "crime", "documentary",
    "drama", "family", "fantasy", "history", "horror", "music", "mystery",
    "romance", "scifi", "sport", "thriller", "war", "western", "rpg",
    "strategy", "shooter", "puzzle", "platformer", "simulation", "indie",
    "nonfiction",
}

# Source-label -> unified genre. Lowercased keys.
_MAP = {
    # TMDB (movies + TV)
    "science fiction": "scifi", "sci-fi & fantasy": "scifi", "action & adventure": "action",
    "tv movie": "drama", "kids": "family", "reality": "documentary", "news": "documentary",
    "soap": "drama", "talk": "documentary", "war & politics": "war",
    # IGDB (games)
    "role-playing (rpg)": "rpg", "role playing": "rpg", "turn-based strategy (tbs)": "strategy",
    "real time strategy (rts)": "strategy", "hack and slash/beat 'em up": "action",
    "shooter": "shooter", "platform": "platformer", "puzzle": "puzzle", "racing": "sport",
    "sport": "sport", "fighting": "action", "adventure": "adventure", "indie": "indie",
    "simulator": "simulation", "strategy": "strategy", "tactical": "strategy",
    # Open Library (books) subjects (best-effort)
    "fiction": "drama", "juvenile fiction": "family", "science fiction": "scifi",
    "fantasy fiction": "fantasy", "detective and mystery stories": "mystery",
    "biography": "nonfiction", "history": "history", "romance fiction": "romance",
    "thrillers": "thriller", "horror tales": "horror",
}


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", label.strip().lower())


def normalize_genre(label: str) -> str | None:
    """Map a raw source genre to a unified genre, or None if it isn't one."""
    low = label.strip().lower()
    if low in _MAP:
        return _MAP[low]
    slug = _slug(label)
    return slug if slug in UNIFIED_GENRES else None


def split_genres_tags(labels: list[str]) -> tuple[list[str], list[str]]:
    """Partition raw labels into (unified genres, leftover tags). Deduped, order-stable."""
    genres: list[str] = []
    tags: list[str] = []
    seen_g: set[str] = set()
    seen_t: set[str] = set()
    for label in labels:
        if not label:
            continue
        g = normalize_genre(label)
        if g:
            if g not in seen_g:
                seen_g.add(g)
                genres.append(g)
        else:
            slug = _slug(label)
            if slug and slug not in seen_t:
                seen_t.add(slug)
                tags.append(slug)
    return genres, tags

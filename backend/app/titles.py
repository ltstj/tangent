"""Matching our catalog titles against a store's titles.

Both price sources need the same judgement calls, and both get them wrong in the
same ways if written twice: a title search returns editions, DLC and
same-named siblings, and picking the wrong one quotes the wrong price.
"""
from __future__ import annotations

import re
from typing import Any, Callable

# An edition is a different way to buy the same game. DLC is not: "The Witcher 3
# - Hearts of Stone" is an expansion that *requires* the base game, so offering
# it as a cheaper alternative would be plainly wrong. Hence a whitelist -
# guessing which unmarked subtitles are DLC is the mistake this avoids.
EDITION_MARKERS = (
    "complete edition", "definitive edition", "deluxe edition", "ultimate edition",
    "gold edition", "enhanced edition", "anniversary edition", "special edition",
    "game of the year", "goty", "remastered", "collection", "royal edition",
)


def norm(title: str) -> str:
    """Comparison key: case, punctuation and spacing differ between sources and
    none of those differences mean anything."""
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def pick_exact(rows: list[Any], title: str, title_of: Callable[[Any], str]) -> Any | None:
    """Best match for `title`: an exact normalized hit, else the shortest title
    containing ours - which prefers a base game over its bundles."""
    if not rows:
        return None
    want = norm(title)
    exact = [r for r in rows if norm(title_of(r)) == want]
    if exact:
        return exact[0]
    contains = [r for r in rows if want and want in norm(title_of(r))]
    if contains:
        return min(contains, key=lambda r: len(title_of(r)))
    return None


def is_edition_of(candidate: str, base: str) -> bool:
    """True when `candidate` is `base` plus an edition suffix and nothing else.

    Strict on purpose. Containment alone is not enough: "ELDEN RING NIGHTREIGN
    Deluxe Edition" contains "Elden Ring" but is a different game, and offering
    it as a cheaper edition of Elden Ring would be wrong.
    """
    low = candidate.lower()
    marker = next((m for m in EDITION_MARKERS if m in low), None)
    if marker is None:
        return False
    return norm(low.replace(marker, "")) == norm(base)

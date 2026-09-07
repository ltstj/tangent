"""Reconciling the hand-built seed catalog with real ingested rows.

seed.py exists so Tangent runs with zero API keys. Once real ingestion has run,
7 of its 17 items have a genuine counterpart and both sit in the catalog, so the
same title can appear twice in one result list.

The real row wins: it has cover art (seed rows have none, so they can never
reach showcase()), a fuller synopsis, and a real popularity figure. But the seed
rows were curated by hand and carry signal the sources do not - seed Game of
Thrones is tagged `epic`, which TMDB never supplies - so their genres and tags
are folded in rather than discarded.

Pure functions: planning a merge touches no database, so it is testable offline.
"""
from __future__ import annotations

from collections import defaultdict

from .models import CatalogItem

SEED_SOURCE = "seed"


def _key(item: CatalogItem) -> tuple[str, str]:
    return item.medium, item.title.strip().lower()


def plan_seed_merges(
    items: list[CatalogItem],
) -> tuple[list[CatalogItem], list[str]]:
    """Fold seed rows into their real counterparts.

    Returns (rows to write back, ids to delete). A seed row with no real
    counterpart is left exactly as it is - it is still the only copy of that
    title, and dropping it would shrink the zero-keys demo catalog.
    """
    groups: dict[tuple[str, str], list[CatalogItem]] = defaultdict(list)
    for item in items:
        groups[_key(item)].append(item)

    updated: list[CatalogItem] = []
    drop: list[str] = []

    for members in groups.values():
        seeds = [i for i in members if i.source == SEED_SOURCE]
        real = [i for i in members if i.source != SEED_SOURCE]
        if not seeds or not real:
            continue
        # Most popular real row wins; popularity is the sources' own signal for
        # which release is the canonical one.
        winner = max(real, key=lambda i: i.popularity or 0.0)
        genres = list(winner.genres)
        tags = list(winner.tags)
        for seed in seeds:
            genres += [g for g in seed.genres if g not in genres]
            tags += [t for t in seed.tags if t not in tags]
            drop.append(seed.id)
        if genres != winner.genres or tags != winner.tags:
            winner.genres = genres
            winner.tags = tags
        updated.append(winner)

    return updated, drop

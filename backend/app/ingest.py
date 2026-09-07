"""Populate the catalog.

Loads the built-in seed always, then pulls from any source whose keys are
configured (TMDB, IGDB) plus Open Library (keyless). Run it before serving:

    python -m app.ingest            # seed + every configured source
    python -m app.ingest --seed     # seed only (no network)
"""
from __future__ import annotations

import sys

from .dedupe import plan_seed_merges
from .seed import SEED_ITEMS
from .sources import igdb, openlibrary, tmdb
from .store import CatalogStore


def ingest(store: CatalogStore, seed_only: bool = False) -> dict[str, int]:
    counts: dict[str, int] = {}
    counts["seed"] = store.upsert_items(SEED_ITEMS)
    if seed_only:
        return counts

    # Open Library needs no key.
    try:
        counts["openlibrary"] = store.upsert_items(openlibrary.fetch_default())
    except Exception as exc:  # network hiccup shouldn't abort the whole ingest
        print(f"[openlibrary] skipped: {exc}", file=sys.stderr)

    for name, fetch in (
        ("tmdb-movie", lambda: tmdb.fetch_popular("movie", pages=2)),
        ("tmdb-tv", lambda: tmdb.fetch_popular("tv", pages=2)),
        ("igdb", lambda: igdb.fetch_popular(limit=100)),
    ):
        try:
            counts[name] = store.upsert_items(fetch())
        except Exception as exc:
            print(f"[{name}] skipped: {exc}", file=sys.stderr)

    # The seed upsert above is unconditional, so a second ingest would reinstate
    # the placeholder rows that real sources have since superseded. Fold them
    # back in here and ingest stays idempotent.
    updated, drop = plan_seed_merges(store.all_items())
    if drop:
        store.upsert_items(updated)
        store.delete_items(drop)
        counts["seed-merged"] = len(drop)
    return counts


def main() -> None:
    seed_only = "--seed" in sys.argv
    store = CatalogStore()
    counts = ingest(store, seed_only=seed_only)
    total = store.count()
    print("Ingested:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"Catalog now holds {total} items.")


if __name__ == "__main__":
    main()

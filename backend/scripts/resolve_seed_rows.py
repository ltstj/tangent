"""Give the leftover hand-written seed rows real source ids.

Ten seed items survived the earlier merge because no ingested row matched them.
They are second-class in a way that shows: no cover art, a one-line synopsis,
and - since Phase 3 - no availability at all, because looking up where to watch
something needs a TMDB id and a seed row has none.

This searches each seed title against the real source for its medium, files what
comes back, then reuses dedupe.plan_seed_merges to fold the seed row into it.
Nothing new is invented: if a search finds no convincing match, the seed row is
left exactly as it is.

    python -m scripts.resolve_seed_rows --dry-run
    python -m scripts.resolve_seed_rows
"""
from __future__ import annotations

import sys

from app.dedupe import plan_seed_merges
from app.sources import igdb, openlibrary, tmdb
from app.store import CatalogStore


def _norm(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())


def _search(item):
    """Live search for one seed item, in the source that owns its medium."""
    if item.medium in ("movie", "tv"):
        return [i for i in tmdb.search_multi(item.title, limit=8) if i.medium == item.medium]
    if item.medium == "game":
        return igdb.search(item.title, limit=8)
    return openlibrary.search(item.title, limit=8)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    store = CatalogStore()
    seeds = [i for i in store.all_items() if i.source == "seed"]
    if not seeds:
        print("No seed rows left. Nothing to do.")
        return 0

    print(f"{len(seeds)} seed rows to resolve\n")
    found, missed = [], []
    for seed in seeds:
        try:
            candidates = _search(seed)
        except Exception as exc:
            print(f"  ?  {seed.title[:30]:32} search failed: {type(exc).__name__}")
            missed.append(seed)
            continue
        # Exact title match only. A near-miss here would attach the wrong film.
        match = next((c for c in candidates if _norm(c.title) == _norm(seed.title)), None)
        if match is None:
            print(f"  -  {seed.title[:30]:32} no exact match in {len(candidates)} results")
            missed.append(seed)
            continue
        print(f"  ok {seed.title[:30]:32} -> {match.id}")
        found.append(match)

    if dry_run:
        print(f"\n--dry-run: would file {len(found)} real rows, "
              f"leaving {len(missed)} seed rows untouched.")
        return 0

    if found:
        store.upsert_items(found)
        updated, drop = plan_seed_merges(store.all_items())
        if drop:
            store.upsert_items(updated)
            store.delete_items(drop)
        print(f"\nfiled {len(found)} real rows; merged away {len(drop)} seed rows")
    print(f"catalog now holds {store.count()} items; "
          f"{len([i for i in store.all_items() if i.source == 'seed'])} seed rows remain")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

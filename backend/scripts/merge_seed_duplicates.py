"""Fold seed rows into the real ingested rows that supersede them.

    python -m scripts.merge_seed_duplicates --dry-run   # show the plan
    python -m scripts.merge_seed_duplicates             # apply it

See app/dedupe.py for why the real row wins and the seed's tags are kept.
Safe to re-run: once the seed rows are gone there is nothing left to merge.
"""
from __future__ import annotations

import sys

from app.dedupe import plan_seed_merges
from app.store import CatalogStore


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    store = CatalogStore()
    items = store.all_items()
    updated, drop = plan_seed_merges(items)

    if not drop:
        print(f"{len(items)} items, no seed rows shadowed by a real row. Nothing to do.")
        return 0

    print(f"{len(items)} items; merging {len(drop)} seed rows into {len(updated)} real rows\n")
    for row in updated:
        print(f"  keep  {row.id:24} {row.title[:30]}")
        print(f"        genres={row.genres}")
        print(f"        tags={row.tags}")
    print("\n  drop  " + ", ".join(drop))

    if dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    store.upsert_items(updated)
    removed = store.delete_items(drop)
    print(f"\nwrote {len(updated)} merged rows, removed {removed}; catalog now {store.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

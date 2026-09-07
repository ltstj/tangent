"""One-shot migration: local SQLite catalog -> Supabase Postgres.

Phase 1 built the catalog in backend/data/catalog.db. Phase 2 makes Postgres the
source of truth, so this copies what is already there rather than re-ingesting
(which would re-hit TMDB/IGDB/Open Library and lose the keyword enrichment and
tag canonicalization already applied to these rows).

    python -m scripts.migrate_sqlite_to_pg            # migrate
    python -m scripts.migrate_sqlite_to_pg --dry-run  # report only

Idempotent: upserts by id, so re-running it is safe.
"""
from __future__ import annotations

import sys
from collections import Counter

from app.store import DEFAULT_DB, CatalogStore, SqliteCatalogStore


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    if not DEFAULT_DB.exists():
        print(f"No SQLite catalog at {DEFAULT_DB} - nothing to migrate.")
        return 1

    src = SqliteCatalogStore(DEFAULT_DB)
    items = src.all_items()
    if not items:
        print("SQLite catalog is empty - nothing to migrate.")
        return 1

    by_medium = Counter(i.medium for i in items)
    by_source = Counter(i.source for i in items)
    print(f"source: {DEFAULT_DB}")
    print(f"  {len(items)} items  media={dict(by_medium)}  sources={dict(by_source)}")

    dst = CatalogStore()
    before = dst.count()
    print(f"destination: Postgres, currently holding {before} items")

    if dry_run:
        print("--dry-run: nothing written.")
        return 0

    written = dst.upsert_items(items)
    after = dst.count()
    print(f"upserted {written}; Postgres now holds {after} items (+{after - before})")

    # Verify a round trip rather than trusting the count alone.
    missing = [i.id for i in items if dst.get(i.id) is None]
    if missing:
        print(f"!! {len(missing)} items did not land, e.g. {missing[:5]}")
        return 1
    sample = items[0]
    echo = dst.get(sample.id)
    ok = (echo.title == sample.title and echo.genres == sample.genres
          and echo.tags == sample.tags)
    print(f"round-trip check on {sample.id}: {'ok' if ok else 'MISMATCH'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

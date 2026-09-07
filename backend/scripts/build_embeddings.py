"""Compute synopsis embeddings for the catalog and store them in pgvector.

    python -m scripts.build_embeddings              # only items missing one
    python -m scripts.build_embeddings --all        # recompute everything
    python -m scripts.build_embeddings --dry-run    # report coverage only

Re-runnable: by default it skips rows that already have an embedding, so it is
cheap to call after an ingest. Pass --all after changing the model or the text
that gets embedded.
"""
from __future__ import annotations

import sys
import time
from collections import Counter

from app import embed
from app.store import CatalogStore


def main() -> int:
    recompute = "--all" in sys.argv
    dry_run = "--dry-run" in sys.argv

    store = CatalogStore()
    items = store.all_items()
    have, total = store.embedding_coverage()
    print(f"catalog: {total} items, {have} with an embedding")

    todo = items if recompute else [i for i in items if i.id not in store.embeddings()]
    todo = [i for i in todo if embed.text_for(i).strip()]
    if not todo:
        print("nothing to do.")
        return 0

    by_medium = Counter(i.medium for i in todo)
    no_synopsis = sum(1 for i in todo if not i.overview.strip())
    print(f"to embed: {len(todo)}  {dict(by_medium)}")
    print(f"  of those, {no_synopsis} have no synopsis (title only)")

    if dry_run:
        print("--dry-run: nothing computed.")
        return 0

    t = time.perf_counter()
    vectors = embed.encode_items(todo)
    print(f"  encoded {len(vectors)} in {time.perf_counter() - t:.1f}s "
          f"({embed.MODEL_NAME}, dim {embed.DIM})")

    written = store.upsert_embeddings(vectors)
    have, total = store.embedding_coverage()
    print(f"  wrote {written}; coverage now {have}/{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

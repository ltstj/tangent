"""Catalog store.

Phase 2 moves the catalog to Supabase Postgres (pgvector), which is the single
source of truth: `CatalogStore` is the Postgres implementation and the app talks
to nothing else.

`SqliteCatalogStore` stays behind it as the offline test double. It is not a
second catalog - no app code constructs it - it exists so the suite runs in ~1s
with no network and no credentials, and so it never writes to the real table.
Both classes expose the same six methods, so a test exercises the same contract
the API does.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings
from .models import CatalogItem

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "catalog.db"

# Every column except `embedding`. Selecting the vector would pull 384 floats per
# row on each all_items() call - and all_items() feeds every model rebuild - for
# data the recommender reads through its own query.
_COLS = (
    "id, medium, title, year, rating, popularity, overview, "
    "source, source_id, genres, tags, image"
)


def _row_to_item(row: dict) -> CatalogItem:
    """Map a result row to a CatalogItem. Shared by both backends; Postgres hands
    back text[] as a list, SQLite hands back a JSON string."""
    genres, tags = row["genres"], row["tags"]
    if isinstance(genres, str):
        genres = json.loads(genres or "[]")
    if isinstance(tags, str):
        tags = json.loads(tags or "[]")
    return CatalogItem(
        id=row["id"], medium=row["medium"], title=row["title"], year=row["year"],
        rating=row["rating"], popularity=row["popularity"], overview=row["overview"] or "",
        source=row["source"] or "", source_id=row["source_id"] or "",
        genres=list(genres or []), tags=list(tags or []), image=row.get("image"),
    )


class CatalogStore:
    """Supabase Postgres catalog."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or settings.database_url
        if not self.dsn:
            raise RuntimeError(
                "DATABASE_URL is not set. The catalog lives in Supabase Postgres; "
                "see backend/.env and supabase/migrations/."
            )
        # Sync FastAPI endpoints run in a threadpool, so hand each request its own
        # connection rather than serializing them behind one.
        #
        # open=False matters: main.py builds a store at import time, and an eager
        # pool would dial Postgres just for `import app.main` - which would make
        # the offline test suite hit the real database.
        self._pool = ConnectionPool(
            self.dsn, min_size=1, max_size=5, timeout=15, open=False,
            kwargs={"row_factory": dict_row},
        )
        self._opened = False

    @contextmanager
    def _connection(self):
        """Borrow a pooled connection, opening the pool on first real use."""
        if not self._opened:
            self._pool.open()
            self._opened = True
        with self._pool.connection() as conn:
            yield conn

    def upsert_items(self, items: list[CatalogItem]) -> int:
        if not items:
            return 0
        rows = [
            (it.id, it.medium, it.title, it.year, it.rating, it.popularity,
             it.overview, it.source, it.source_id, it.genres, it.tags, it.image)
            for it in items
        ]
        with self._connection() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO items (id, medium, title, year, rating, popularity, overview,
                                   source, source_id, genres, tags, image)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET
                    medium=excluded.medium, title=excluded.title, year=excluded.year,
                    rating=excluded.rating, popularity=excluded.popularity,
                    overview=excluded.overview, source=excluded.source,
                    source_id=excluded.source_id, genres=excluded.genres,
                    tags=excluded.tags, image=excluded.image, updated_at=now()
                """,
                rows,
            )
        return len(rows)

    def count(self) -> int:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM items")
            return cur.fetchone()["c"]

    def get(self, item_id: str) -> CatalogItem | None:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM items WHERE id = %s", (item_id,))
            row = cur.fetchone()
        return _row_to_item(row) if row else None

    def search(self, query: str, medium: str | None = None, limit: int = 10) -> list[CatalogItem]:
        """Prefix/substring title search for autocomplete. Ranks prefix matches first."""
        q = query.strip()
        if not q:
            return []
        sql = (
            f"SELECT {_COLS} FROM items WHERE title ILIKE %s "
            + ("AND medium = %s " if medium else "")
            + "ORDER BY (title ILIKE %s) DESC, popularity DESC NULLS LAST, title ASC LIMIT %s"
        )
        params: list[object] = [f"%{q}%"]
        if medium:
            params.append(medium)
        params += [f"{q}%", limit]
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [_row_to_item(r) for r in cur.fetchall()]

    def showcase(self, limit: int = 48) -> list[CatalogItem]:
        """Popular items that have cover art (for the background wall)."""
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM items WHERE image IS NOT NULL "
                "ORDER BY popularity DESC NULLS LAST LIMIT %s",
                (limit,),
            )
            return [_row_to_item(r) for r in cur.fetchall()]

    def all_items(self, medium: str | None = None) -> list[CatalogItem]:
        sql = f"SELECT {_COLS} FROM items"
        params: tuple = ()
        if medium:
            sql += " WHERE medium = %s"
            params = (medium,)
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [_row_to_item(r) for r in cur.fetchall()]

    def close(self) -> None:
        if self._opened:
            self._pool.close()
            self._opened = False


class SqliteCatalogStore:
    """Offline test double. Same contract as CatalogStore, no network."""

    def __init__(self, path: str | Path = DEFAULT_DB) -> None:
        self.path = Path(path)
        if self.path.parent and str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY, medium TEXT NOT NULL, title TEXT NOT NULL,
                year INTEGER, rating REAL, popularity REAL, overview TEXT,
                source TEXT, source_id TEXT, genres TEXT, tags TEXT, image TEXT
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_items_medium ON items(medium)")
        self._conn.commit()

    def upsert_items(self, items: list[CatalogItem]) -> int:
        rows = [
            (it.id, it.medium, it.title, it.year, it.rating, it.popularity,
             it.overview, it.source, it.source_id,
             json.dumps(it.genres), json.dumps(it.tags), it.image)
            for it in items
        ]
        self._conn.executemany(
            """
            INSERT INTO items (id, medium, title, year, rating, popularity, overview,
                               source, source_id, genres, tags, image)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                medium=excluded.medium, title=excluded.title, year=excluded.year,
                rating=excluded.rating, popularity=excluded.popularity,
                overview=excluded.overview, source=excluded.source,
                source_id=excluded.source_id, genres=excluded.genres,
                tags=excluded.tags, image=excluded.image
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]

    def get(self, item_id: str) -> CatalogItem | None:
        row = self._conn.execute(f"SELECT {_COLS} FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(dict(row)) if row else None

    def search(self, query: str, medium: str | None = None, limit: int = 10) -> list[CatalogItem]:
        q = query.strip()
        if not q:
            return []
        sql = (
            f"SELECT {_COLS} FROM items WHERE lower(title) LIKE ? "
            + ("AND medium = ? " if medium else "")
            + "ORDER BY (lower(title) LIKE ?) DESC, popularity DESC NULLS LAST, title ASC LIMIT ?"
        )
        params: list[object] = [f"%{q.lower()}%"]
        if medium:
            params.append(medium)
        params += [f"{q.lower()}%", limit]
        return [_row_to_item(dict(r)) for r in self._conn.execute(sql, params).fetchall()]

    def showcase(self, limit: int = 48) -> list[CatalogItem]:
        rows = self._conn.execute(
            f"SELECT {_COLS} FROM items WHERE image IS NOT NULL "
            "ORDER BY popularity DESC NULLS LAST LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_item(dict(r)) for r in rows]

    def all_items(self, medium: str | None = None) -> list[CatalogItem]:
        sql = f"SELECT {_COLS} FROM items"
        params: tuple = ()
        if medium:
            sql += " WHERE medium = ?"
            params = (medium,)
        return [_row_to_item(dict(r)) for r in self._conn.execute(sql, params).fetchall()]

    def close(self) -> None:
        self._conn.close()

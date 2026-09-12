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

import numpy as np
from pgvector.psycopg import register_vector
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


def _to_array(value) -> np.ndarray:
    """pgvector hands back its own Vector wrapper, not a bare array."""
    if hasattr(value, "to_numpy"):
        value = value.to_numpy()
    return np.asarray(value, dtype=np.float32)


def _cols(prefix: str) -> str:
    """_COLS qualified with a table alias. Needed for the library join: both
    `items` and `library` have `rating` and `note`, so bare column names are
    ambiguous even when the output is aliased."""
    return ", ".join(f"{prefix}.{c.strip()}" for c in _COLS.split(","))


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
            # pgvector's type has to be registered per connection, or the
            # `embedding` column comes back as a string and writes fail.
            configure=register_vector,
            # Test a connection before handing it out. Without this, a
            # connection dropped while idle - Supabase timing it out, a network
            # blip, an OS memory event - is served to whichever request asks
            # next, which fails with a 500 before the pool notices and replaces
            # it. Observed exactly that on 2026-09-06. Costs one round-trip per
            # checkout, a few ms against the ~250ms a cross-network query
            # already takes.
            check=ConnectionPool.check_connection,
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

    def subscription_prices(self, region: str = "US") -> list[dict]:
        """Every tracked service for a region, price included or NULL."""
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT service_key, display_name, price, currency, period, "
                "checked_on, source_url, note FROM subscription_prices "
                "WHERE region = %s ORDER BY display_name",
                (region.upper(),),
            )
            return [dict(r) for r in cur.fetchall()]

    def set_subscription_price(
        self, service_key: str, price: float | None, region: str = "US",
        checked_on=None, note: str = "",
    ) -> bool:
        """Record a verified price. `checked_on` is what makes it usable - a
        price with no date is treated as unknown, see subscriptions.py."""
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE subscription_prices SET price = %s, checked_on = %s, note = %s "
                "WHERE service_key = %s AND region = %s",
                (price, checked_on, note, service_key, region.upper()),
            )
            return cur.rowcount > 0

    # --- per-user library ---------------------------------------------------
    #
    # Every one of these filters on user_id explicitly. The API connects as the
    # table owner and therefore bypasses row-level security, so RLS is defence
    # in depth here, not the guard - forgetting a user_id predicate would leak
    # one person's library to another.

    def library(self, user_id: str) -> list[dict]:
        """One user's entries, most recently touched first."""
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT l.item_id AS lib_item_id, l.status AS lib_status, "
                "l.rating AS lib_rating, l.note AS lib_note, "
                f"l.updated_at AS lib_updated_at, {_cols('i')} "
                "FROM library l JOIN items i ON i.id = l.item_id "
                "WHERE l.user_id = %s ORDER BY l.updated_at DESC",
                (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def set_library_entry(self, user_id: str, item_id: str, status: str,
                          rating: float | None = None, note: str = "") -> bool:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO library (user_id, item_id, status, rating, note)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id, item_id) DO UPDATE SET
                    status = excluded.status, rating = excluded.rating,
                    note = excluded.note, updated_at = now()
                """,
                (user_id, item_id, status, rating, note),
            )
            return cur.rowcount > 0

    def remove_library_entry(self, user_id: str, item_id: str) -> bool:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM library WHERE user_id = %s AND item_id = %s",
                        (user_id, item_id))
            return cur.rowcount > 0

    def interactions(self) -> list[tuple[str, str, float]]:
        """(user_id, item_id, weight) across everyone, for collaborative filtering.

        Cross-user by necessity - that is what collaborative filtering is - so it
        returns only what the model needs and never leaves the server. Nothing
        here reaches an API response; see collab.py for the thresholds that stop
        a small instance from exposing an individual through aggregates.
        """
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id::text AS user_id, item_id,
                       CASE WHEN rating IS NOT NULL THEN (rating - 5.0) / 5.0
                            WHEN status = 'finished' THEN 0.5
                            WHEN status = 'in_progress' THEN 0.4
                            ELSE 0.3 END AS weight
                FROM library
                UNION ALL
                SELECT user_id::text AS user_id, item_id,
                       CASE WHEN helpful THEN 0.35 ELSE -1.0 END AS weight
                FROM match_feedback
                """
            )
            return [(r["user_id"], r["item_id"], float(r["weight"])) for r in cur.fetchall()]

    def match_feedback(self, user_id: str) -> list[dict]:
        """This user's verdicts on recommendations they were given."""
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT item_id, source_ids, helpful FROM match_feedback "
                "WHERE user_id = %s", (user_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def set_match_feedback(self, user_id: str, item_id: str, helpful: bool,
                           source_ids: list[str] | None = None) -> bool:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO match_feedback (user_id, item_id, source_ids, helpful)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id, item_id) DO UPDATE SET
                    helpful = excluded.helpful, source_ids = excluded.source_ids,
                    created_at = now()
                """,
                (user_id, item_id, list(source_ids or []), helpful),
            )
            return cur.rowcount > 0

    def clear_match_feedback(self, user_id: str, item_id: str) -> bool:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM match_feedback WHERE user_id = %s AND item_id = %s",
                        (user_id, item_id))
            return cur.rowcount > 0

    def delete_user_data(self, user_id: str) -> int:
        """Everything we hold for one person, across every table that holds any.

        See auth.users' ON DELETE CASCADE: removing the account removes all of
        this too, but this lets someone clear their data without closing the
        account. Any new personal table must be added here as well, or "delete
        my data" quietly stops being true.
        """
        with self._connection() as conn, conn.cursor() as cur:
            total = 0
            for table in ("library", "match_feedback"):
                cur.execute(f"DELETE FROM {table} WHERE user_id = %s", (user_id,))
                total += cur.rowcount
            return total

    def delete_items(self, ids: list[str]) -> int:
        """Remove rows by id. Used to retire seed rows superseded by real ones."""
        if not ids:
            return 0
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM items WHERE id = ANY(%s)", (list(ids),))
            return cur.rowcount

    def upsert_embeddings(self, vectors: dict[str, np.ndarray]) -> int:
        """Write synopsis embeddings for ids already in the catalog."""
        if not vectors:
            return 0
        rows = [(np.asarray(v, dtype=np.float32), k) for k, v in vectors.items()]
        with self._connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "UPDATE items SET embedding = %s, updated_at = now() WHERE id = %s", rows
            )
        return len(rows)

    def embeddings(self) -> dict[str, np.ndarray]:
        """id -> embedding, for the rows that have one.

        Kept separate from all_items() so the 384-float column is only pulled by
        the caller that actually needs it.
        """
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, embedding FROM items WHERE embedding IS NOT NULL")
            return {r["id"]: _to_array(r["embedding"]) for r in cur.fetchall()}

    def embedding_coverage(self) -> tuple[int, int]:
        """(rows with an embedding, total rows)."""
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(embedding) AS have, count(*) AS total FROM items")
            r = cur.fetchone()
            return r["have"], r["total"]

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
                source TEXT, source_id TEXT, genres TEXT, tags TEXT, image TEXT,
                embedding TEXT   -- JSON array; pgvector's column, minus pgvector
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS library (
                user_id TEXT NOT NULL, item_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'want', rating REAL,
                note TEXT NOT NULL DEFAULT '', updated_at TEXT,
                PRIMARY KEY (user_id, item_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS match_feedback (
                user_id TEXT NOT NULL, item_id TEXT NOT NULL,
                source_ids TEXT NOT NULL DEFAULT '[]', helpful INTEGER NOT NULL,
                PRIMARY KEY (user_id, item_id)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscription_prices (
                service_key TEXT NOT NULL, display_name TEXT NOT NULL,
                region TEXT NOT NULL DEFAULT 'US', price REAL,
                currency TEXT NOT NULL DEFAULT 'USD',
                period TEXT NOT NULL DEFAULT 'month',
                checked_on TEXT, source_url TEXT, note TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (service_key, region)
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

    def subscription_prices(self, region: str = "US") -> list[dict]:
        rows = self._conn.execute(
            "SELECT service_key, display_name, price, currency, period, checked_on, "
            "source_url, note FROM subscription_prices WHERE region = ? ORDER BY display_name",
            (region.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_subscription_price(
        self, service_key: str, price: float | None, region: str = "US",
        checked_on=None, note: str = "",
    ) -> bool:
        cur = self._conn.execute(
            "INSERT INTO subscription_prices (service_key, display_name, region, price, "
            "checked_on, note) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(service_key, region) DO UPDATE SET price=excluded.price, "
            "checked_on=excluded.checked_on, note=excluded.note",
            (service_key, service_key, region.upper(), price,
             str(checked_on) if checked_on else None, note),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def library(self, user_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT l.item_id AS lib_item_id, l.status AS lib_status, "
            "l.rating AS lib_rating, l.note AS lib_note, "
            f"l.updated_at AS lib_updated_at, {_cols('i')} "
            "FROM library l JOIN items i ON i.id = l.item_id "
            "WHERE l.user_id = ? ORDER BY l.updated_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_library_entry(self, user_id: str, item_id: str, status: str,
                          rating: float | None = None, note: str = "") -> bool:
        cur = self._conn.execute(
            "INSERT INTO library (user_id, item_id, status, rating, note, updated_at) "
            "VALUES (?,?,?,?,?,datetime('now')) "
            "ON CONFLICT(user_id, item_id) DO UPDATE SET status=excluded.status, "
            "rating=excluded.rating, note=excluded.note, updated_at=datetime('now')",
            (user_id, item_id, status, rating, note),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def remove_library_entry(self, user_id: str, item_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM library WHERE user_id = ? AND item_id = ?",
                                 (user_id, item_id))
        self._conn.commit()
        return cur.rowcount > 0

    def interactions(self) -> list[tuple[str, str, float]]:
        rows = self._conn.execute(
            """
            SELECT user_id, item_id,
                   CASE WHEN rating IS NOT NULL THEN (rating - 5.0) / 5.0
                        WHEN status = 'finished' THEN 0.5
                        WHEN status = 'in_progress' THEN 0.4
                        ELSE 0.3 END AS weight
            FROM library
            UNION ALL
            SELECT user_id, item_id,
                   CASE WHEN helpful THEN 0.35 ELSE -1.0 END AS weight
            FROM match_feedback
            """
        ).fetchall()
        return [(r["user_id"], r["item_id"], float(r["weight"])) for r in rows]

    def match_feedback(self, user_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT item_id, source_ids, helpful FROM match_feedback WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["source_ids"] = json.loads(d["source_ids"] or "[]")
            d["helpful"] = bool(d["helpful"])
            out.append(d)
        return out

    def set_match_feedback(self, user_id: str, item_id: str, helpful: bool,
                           source_ids: list[str] | None = None) -> bool:
        cur = self._conn.execute(
            "INSERT INTO match_feedback (user_id, item_id, source_ids, helpful) "
            "VALUES (?,?,?,?) ON CONFLICT(user_id, item_id) DO UPDATE SET "
            "helpful=excluded.helpful, source_ids=excluded.source_ids",
            (user_id, item_id, json.dumps(list(source_ids or [])), 1 if helpful else 0),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def clear_match_feedback(self, user_id: str, item_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM match_feedback WHERE user_id = ? AND item_id = ?", (user_id, item_id))
        self._conn.commit()
        return cur.rowcount > 0

    def delete_user_data(self, user_id: str) -> int:
        total = 0
        for table in ("library", "match_feedback"):
            cur = self._conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            total += cur.rowcount
        self._conn.commit()
        return total

    def delete_items(self, ids: list[str]) -> int:
        if not ids:
            return 0
        cur = self._conn.executemany("DELETE FROM items WHERE id = ?", [(i,) for i in ids])
        self._conn.commit()
        return len(ids)

    def upsert_embeddings(self, vectors: dict[str, np.ndarray]) -> int:
        rows = [(json.dumps(np.asarray(v, dtype=np.float32).tolist()), k)
                for k, v in vectors.items()]
        self._conn.executemany("UPDATE items SET embedding = ? WHERE id = ?", rows)
        self._conn.commit()
        return len(rows)

    def embeddings(self) -> dict[str, np.ndarray]:
        rows = self._conn.execute(
            "SELECT id, embedding FROM items WHERE embedding IS NOT NULL"
        ).fetchall()
        return {r["id"]: _to_array(json.loads(r["embedding"])) for r in rows}

    def embedding_coverage(self) -> tuple[int, int]:
        row = self._conn.execute(
            "SELECT COUNT(embedding) AS have, COUNT(*) AS total FROM items"
        ).fetchone()
        return row["have"], row["total"]

    def close(self) -> None:
        self._conn.close()

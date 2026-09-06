"""SQLite catalog store.

Phase 1 keeps the catalog in a local SQLite file (zero external services) with an
in-memory list for the recommender to vectorize. The interface is deliberately
small (upsert, search, get, all) so Phase 2 can swap in Postgres + pgvector
without touching the recommender or API.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import CatalogItem

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "catalog.db"


class CatalogStore:
    def __init__(self, path: str | Path = DEFAULT_DB) -> None:
        self.path = Path(path)
        if self.path.parent and str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                medium TEXT NOT NULL,
                title TEXT NOT NULL,
                year INTEGER,
                rating REAL,
                popularity REAL,
                overview TEXT,
                source TEXT,
                source_id TEXT,
                genres TEXT,     -- JSON array
                tags TEXT,       -- JSON array
                image TEXT
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_items_medium ON items(medium)")
        # Migration: add `image` to catalogs created before it existed.
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(items)")}
        if "image" not in cols:
            self._conn.execute("ALTER TABLE items ADD COLUMN image TEXT")
        self._conn.commit()

    def upsert_items(self, items: list[CatalogItem]) -> int:
        rows = [
            (
                it.id, it.medium, it.title, it.year, it.rating, it.popularity,
                it.overview, it.source, it.source_id,
                json.dumps(it.genres), json.dumps(it.tags), it.image,
            )
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
                source_id=excluded.source_id, genres=excluded.genres, tags=excluded.tags,
                image=excluded.image
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]

    def _row_to_item(self, row: sqlite3.Row) -> CatalogItem:
        return CatalogItem(
            id=row["id"], medium=row["medium"], title=row["title"], year=row["year"],
            rating=row["rating"], popularity=row["popularity"], overview=row["overview"] or "",
            source=row["source"] or "", source_id=row["source_id"] or "",
            genres=json.loads(row["genres"] or "[]"), tags=json.loads(row["tags"] or "[]"),
            image=row["image"] if "image" in row.keys() else None,
        )

    def get(self, item_id: str) -> CatalogItem | None:
        row = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def search(self, query: str, medium: str | None = None, limit: int = 10) -> list[CatalogItem]:
        """Prefix/substring title search for autocomplete. Ranks prefix matches first."""
        q = query.strip()
        if not q:
            return []
        like = f"%{q.lower()}%"
        prefix = f"{q.lower()}%"
        sql = (
            "SELECT * FROM items WHERE lower(title) LIKE ? "
            + ("AND medium = ? " if medium else "")
            + "ORDER BY (lower(title) LIKE ?) DESC, popularity DESC NULLS LAST, title ASC LIMIT ?"
        )
        params: list[object] = [like]
        if medium:
            params.append(medium)
        params += [prefix, limit]
        return [self._row_to_item(r) for r in self._conn.execute(sql, params).fetchall()]

    def showcase(self, limit: int = 48) -> list[CatalogItem]:
        """Popular items that have cover art (for the background wall)."""
        rows = self._conn.execute(
            "SELECT * FROM items WHERE image IS NOT NULL "
            "ORDER BY popularity DESC NULLS LAST LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def all_items(self, medium: str | None = None) -> list[CatalogItem]:
        if medium:
            rows = self._conn.execute("SELECT * FROM items WHERE medium = ?", (medium,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM items").fetchall()
        return [self._row_to_item(r) for r in rows]

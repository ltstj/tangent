"""Tangent API.

Phase 1: catalog search (autocomplete), item lookup, and content-based
recommendations (including the cross-media jump). Backed by a local SQLite
catalog seeded on first run, so it works with zero API keys. See ../ROADMAP.md.
"""
from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .models import CatalogItem, Medium
from .recommend import TasteModel
from .seed import SEED_ITEMS
from .sources import igdb, openlibrary, tmdb
from .store import CatalogStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed the catalog on first run so the app works with zero API keys.
    if store.count() == 0:
        store.upsert_items(SEED_ITEMS)
    refresh_model()
    yield


app = FastAPI(title="Tangent API", version="0.1.0", lifespan=lifespan)

# Dev-friendly CORS so the Vite frontend can call the API locally.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

store = CatalogStore()
_model: TasteModel | None = None
_items: list[CatalogItem] | None = None
_model_lock = Lock()


def get_model() -> TasteModel:
    """Cached taste model; rebuilt after the catalog changes via refresh_model()."""
    global _model, _items
    with _model_lock:
        if _items is None:
            _items = store.all_items()
        if _model is None:
            _model = TasteModel(_items)
        return _model


def refresh_model(added: list[CatalogItem] | None = None) -> None:
    """Invalidate the taste model.

    Pass the items that just changed and the cached catalog is patched in place.
    Postgres lives across the network, so re-reading all 611 rows costs ~0.7s -
    which, on the autocomplete path, is worse than the live source lookup it was
    meant to complement. With no argument the next build reloads in full.
    """
    global _model, _items
    with _model_lock:
        _model = None
        if added is None or _items is None:
            _items = None
            return
        merged = {it.id: it for it in _items}
        merged.update({it.id: it for it in added})
        _items = list(merged.values())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/ready")
def ready() -> dict[str, object]:
    return {
        "catalog_items": store.count(),
        "tmdb": bool(settings.tmdb_api_key),
        "igdb": bool(settings.igdb_client_id and settings.igdb_client_secret),
        "supabase": bool(settings.supabase_url and settings.database_url),
        "openlibrary": True,
        "cheapshark": True,
    }


# Autocomplete fires per keystroke, so the response must not wait on the slowest
# provider. Open Library's search endpoint routinely takes 2-4s (server-side; the
# payload is 3KB), against ~0.3s for TMDB and ~0.5s for IGDB. Waiting on all three
# made every uncached keystroke a ~2.3s round trip. We now return whatever has
# arrived by the deadline and let stragglers land in the catalog in the
# background, so the title is instant on the next keystroke.
LIVE_DEADLINE_S = 0.9
# A complete answer is cached for a while; a partial one (a source missed the
# deadline) is cached briefly too, because a query that yields fewer than `limit`
# hits re-fires the fan-out on every keystroke otherwise.
_LIVE_CACHE_TTL_S = 300.0
_LIVE_PARTIAL_TTL_S = 20.0

_live_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="live-search")
_live_cache: dict[tuple[str, str | None], tuple[float, list[CatalogItem]]] = {}
_live_cache_lock = Lock()


def _absorb(items: list[CatalogItem]) -> list[CatalogItem]:
    """Add newly seen titles to the catalog so they become recommendable.

    TMDB search results carry no keywords, so a title added this way would sit in
    the catalog matchable on broad genres alone. Enrich it off the request path
    and re-save, so it is fully comparable by the time anyone recommends from it.
    """
    new = [i for i in items if store.get(i.id) is None]
    if new:
        store.upsert_items(new)
        refresh_model(new)
        needs_keywords = [i for i in new if i.source == "tmdb" and not i.tags]
        if needs_keywords:
            _live_pool.submit(_enrich_later, needs_keywords)
    return items


def _enrich_later(items: list[CatalogItem]) -> None:
    try:
        tmdb.enrich_keywords(items)
        store.upsert_items(items)
        refresh_model(items)
    except Exception:
        pass


def _drain_later(fut: Future) -> None:
    """A source that missed the deadline still gets its results into the catalog."""
    try:
        _absorb(fut.result())
    except Exception:
        pass


def _live_search(q: str, medium: Medium | None, limit: int) -> list[CatalogItem]:
    """Query the external sources concurrently for titles not yet in the catalog.
    Returns what is ready within LIVE_DEADLINE_S; slow sources are absorbed later.
    Guarded so a missing key or a network hiccup just yields fewer results."""
    key = (q.strip().lower(), medium)
    now = time.monotonic()
    with _live_cache_lock:
        hit = _live_cache.get(key)
        if hit and now < hit[0]:
            return hit[1]

    tasks = []
    if medium in (None, "movie", "tv"):
        tasks.append(lambda: tmdb.search_multi(q, limit))
    if medium in (None, "game"):
        tasks.append(lambda: igdb.search(q, limit))
    if medium in (None, "book"):
        tasks.append(lambda: openlibrary.search(q, limit))
    if not tasks:
        return []

    futures = [_live_pool.submit(t) for t in tasks]
    done, pending = wait(futures, timeout=LIVE_DEADLINE_S)

    live: list[CatalogItem] = []
    for fut in done:
        try:
            live += fut.result()
        except Exception:
            pass
    for fut in pending:
        fut.add_done_callback(_drain_later)

    live = [i for i in live if not medium or i.medium == medium]
    ttl = _LIVE_PARTIAL_TTL_S if pending else _LIVE_CACHE_TTL_S
    with _live_cache_lock:
        _live_cache[key] = (now + ttl, live)
    return live


@app.get("/api/search", response_model=list[CatalogItem])
def search(
    q: str = Query(..., min_length=1),
    medium: Medium | None = None,
    limit: int = Query(10, ge=1, le=50),
) -> list[CatalogItem]:
    """Autocomplete. Serves local catalog hits first; when there aren't enough,
    it searches TMDB/IGDB/Open Library live, adds those titles to the catalog (so
    they're recommendable), and merges them in."""
    local = store.search(q, medium=medium, limit=limit)
    if len(local) >= limit:
        return local

    live = _absorb(_live_search(q, medium, limit))

    seen = {i.id for i in local}
    merged = list(local)
    for it in live:
        if it.id not in seen:
            seen.add(it.id)
            merged.append(it)
    return merged[:limit]


@app.get("/api/item/{item_id:path}", response_model=CatalogItem)
def get_item(item_id: str) -> CatalogItem:
    item = store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found.")
    return item


@app.get("/api/media")
def media_counts() -> dict[str, int]:
    return {m: len(store.all_items(m)) for m in ("movie", "tv", "game", "book")}


@app.get("/api/showcase", response_model=list[CatalogItem])
def showcase(limit: int = Query(48, ge=1, le=120)) -> list[CatalogItem]:
    """Popular titles with cover art, for the background wall."""
    return store.showcase(limit)


class RecommendRequest(BaseModel):
    favorite_ids: list[str]
    target_media: list[Medium] | None = None  # None = any medium (incl. cross-media)
    limit: int = 12


@app.post("/api/recommend")
def recommend(req: RecommendRequest) -> dict[str, object]:
    """Recommend from favorites. Set target_media to a single medium for
    same-media recs, or a different one for the cross-media jump."""
    known = [fid for fid in req.favorite_ids if store.get(fid) is not None]
    if not known:
        raise HTTPException(status_code=400, detail="None of the favorite_ids are in the catalog.")
    results = get_model().recommend(known, target_media=req.target_media, limit=req.limit)
    return {"count": len(results), "results": results}

"""Tangent API.

Phase 1: catalog search (autocomplete), item lookup, and content-based
recommendations (including the cross-media jump). Backed by a local SQLite
catalog seeded on first run, so it works with zero API keys. See ../ROADMAP.md.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

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


def get_model() -> TasteModel:
    """Cached taste model; rebuilt after the catalog changes via refresh_model()."""
    global _model
    if _model is None:
        _model = TasteModel(store.all_items())
    return _model


def refresh_model() -> None:
    global _model
    _model = None


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


def _live_search(q: str, medium: Medium | None, limit: int) -> list[CatalogItem]:
    """Query the external sources concurrently for titles not yet in the catalog.
    Guarded so a missing key or a network hiccup just yields fewer results."""
    tasks = []
    if medium in (None, "movie", "tv"):
        tasks.append(lambda: tmdb.search_multi(q, limit))
    if medium in (None, "game"):
        tasks.append(lambda: igdb.search(q, limit))
    if medium in (None, "book"):
        tasks.append(lambda: openlibrary.search(q, limit))

    live: list[CatalogItem] = []
    with ThreadPoolExecutor(max_workers=len(tasks) or 1) as pool:
        for fut in [pool.submit(t) for t in tasks]:
            try:
                live += fut.result()
            except Exception:
                pass
    return [i for i in live if not medium or i.medium == medium]


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

    live = _live_search(q, medium, limit)
    new_items = [i for i in live if store.get(i.id) is None]
    if new_items:
        store.upsert_items(new_items)
        refresh_model()  # so the new titles are usable in recommendations

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

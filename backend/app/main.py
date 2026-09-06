"""Tangent API.

Phase 1: catalog search (autocomplete), item lookup, and content-based
recommendations (including the cross-media jump). Backed by a local SQLite
catalog seeded on first run, so it works with zero API keys. See ../ROADMAP.md.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .models import CatalogItem, Medium
from .recommend import TasteModel
from .seed import SEED_ITEMS
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


@app.get("/api/search", response_model=list[CatalogItem])
def search(
    q: str = Query(..., min_length=1),
    medium: Medium | None = None,
    limit: int = Query(10, ge=1, le=50),
) -> list[CatalogItem]:
    """Autocomplete over the catalog (title match)."""
    return store.search(q, medium=medium, limit=limit)


@app.get("/api/item/{item_id:path}", response_model=CatalogItem)
def get_item(item_id: str) -> CatalogItem:
    item = store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found.")
    return item


@app.get("/api/media")
def media_counts() -> dict[str, int]:
    return {m: len(store.all_items(m)) for m in ("movie", "tv", "game", "book")}


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

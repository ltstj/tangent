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

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import subscriptions
from . import taste
from .auth import User, current_user, optional_user
from .availability import availability_for
from .config import settings
from .models import CatalogItem, LibraryEntry, LibraryStatus, Medium
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
_item_index: dict[str, CatalogItem] | None = None
_embeddings: dict | None = None
_model_lock = Lock()

# The subscription table changes only when a human records a price, so re-reading
# it per request bought nothing and cost a network round-trip. Short TTL so an
# entry made by scripts/set_subscription_price shows up promptly anyway.
_PRICE_TTL_S = 60.0
_price_cache: dict[str, tuple[float, list[dict]]] = {}
_price_lock = Lock()


def _lookup_item(item_id: str) -> CatalogItem | None:
    """Find an item without a network round-trip when we already hold it.

    The catalog is already in memory for the recommender, so hitting Postgres
    again to resolve an id the model is holding was pure latency - it dominated
    the offers endpoint once its own results were cached.
    """
    global _item_index
    with _model_lock:
        if _item_index is None:
            # Seed from the recommender's catalog if it is already loaded;
            # otherwise start empty and fill in as ids are asked for. The offers
            # panel asks for the same handful of ids repeatedly, so memoizing
            # single lookups is enough - no need to pull the whole catalog just
            # to resolve one id.
            _item_index = {i.id: i for i in _items} if _items else {}
        hit = _item_index.get(item_id)
    if hit is not None:
        return hit
    found = store.get(item_id)
    if found is not None:
        with _model_lock:
            if _item_index is not None:
                _item_index[item_id] = found
    return found


def _price_rows(region: str) -> list[dict]:
    key = region.upper()
    now = time.monotonic()
    with _price_lock:
        hit = _price_cache.get(key)
        if hit and now < hit[0]:
            return hit[1]
    rows = store.subscription_prices(key)
    with _price_lock:
        _price_cache[key] = (now + _PRICE_TTL_S, rows)
    return rows


def get_model() -> TasteModel:
    """Cached taste model; rebuilt after the catalog changes via refresh_model()."""
    global _model, _items, _embeddings
    with _model_lock:
        if _items is None:
            _items = store.all_items()
        if _embeddings is None:
            _embeddings = store.embeddings()
        if _model is None:
            _model = TasteModel(_items, _embeddings)
        return _model


def refresh_model(added: list[CatalogItem] | None = None) -> None:
    """Invalidate the taste model.

    Pass the items that just changed and the cached catalog is patched in place.
    Postgres lives across the network, so re-reading all 611 rows costs ~0.7s -
    which, on the autocomplete path, is worse than the live source lookup it was
    meant to complement. With no argument the next build reloads in full.
    """
    global _model, _items, _item_index, _embeddings
    with _model_lock:
        _model = None
        _item_index = None
        if added is None or _items is None:
            _items = None
            _item_index = None
            _embeddings = None
            return
        merged = {it.id: it for it in _items}
        merged.update({it.id: it for it in added})
        _items = list(merged.values())
        _item_index = merged


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
        "embeddings": "%d/%d" % store.embedding_coverage(),
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


@app.get("/api/offers/{item_id:path}")
def offers(
    item_id: str,
    limit: int = Query(6, ge=1, le=20),
    region: str = Query("US", min_length=2, max_length=2),
) -> dict[str, object]:
    """Where to get one title. Prices where we can source them honestly, and
    plain link-outs where we cannot - see availability.py.

    `priced` tells the caller which it got, so the UI never has to infer whether
    a missing price means "free" or "unknown". Streaming availability carries
    JustWatch attribution, which TMDB's terms require.
    """
    item = _lookup_item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Unknown item id.")
    rows = _price_rows(region) if item.medium in ("movie", "tv") else None
    result = availability_for(item, limit=limit, region=region, price_rows=rows)
    found = result.offers
    body: dict[str, object] = {
        "item_id": item.id,
        "medium": item.medium,
        "title": item.title,
        "region": region.upper(),
        "offers": found,
        "priced": any(o.price is not None for o in found),
        # status distinguishes "nothing available" from "we could not ask".
        "status": result.status,
        "detail": result.detail,
        "price_region": result.price_region,
        "notes": result.notes,
    }
    best = subscriptions.cheapest(found)
    if best is not None:
        # None means "we can't price one", never "there isn't one" - the caller
        # must not render an absence here as "not streaming anywhere".
        body["cheapest_subscription"] = {
            "store": best.store, "price": best.price, "currency": best.currency,
        }
    if item.medium in ("movie", "tv") and found:
        body["attribution"] = tmdb.ATTRIBUTION
    return body


@app.get("/api/subscriptions")
def subscription_table(region: str = Query("US", min_length=2, max_length=2)) -> dict[str, object]:
    """The subscription price table, including which rows are unusable and why.

    Exposed so the staleness of this data is inspectable rather than implicit -
    it is the one part of pricing that a human has to keep current.
    """
    rows = store.subscription_prices(region)
    usable = subscriptions.usable_prices(rows)
    return {
        "region": region.upper(),
        "stale_after_days": subscriptions.STALE_AFTER_DAYS,
        "tracked": len(rows),
        "usable": len(usable),
        "services": [
            {**r, "usable": r["service_key"] in usable} for r in rows
        ],
    }


# --- library (requires a signed-in user) -------------------------------------


def _to_entry(row: dict) -> LibraryEntry:
    """A joined library row -> LibraryEntry, reusing the catalog mapper."""
    from .store import _row_to_item

    # The library's own columns are aliased lib_* by the query: an item has a
    # `rating` and a `note` too, and letting them share a name meant the join
    # returned one of the two at random.
    updated = row.get("lib_updated_at")
    return LibraryEntry(
        item=_row_to_item(row),
        status=row.get("lib_status") or "want",
        rating=float(row["lib_rating"]) if row.get("lib_rating") is not None else None,
        note=row.get("lib_note") or "",
        updated_at=str(updated) if updated else None,
    )


class LibraryWrite(BaseModel):
    status: LibraryStatus = "want"
    rating: float | None = None
    note: str = ""


@app.get("/api/library", response_model=list[LibraryEntry])
def get_library(user: User = Depends(current_user)) -> list[LibraryEntry]:
    """Everything this user has marked. Scoped by the verified token's subject -
    never by anything the caller supplies."""
    return [_to_entry(r) for r in store.library(user.id)]


@app.put("/api/library/{item_id:path}", response_model=LibraryEntry)
def put_library(
    item_id: str, body: LibraryWrite, user: User = Depends(current_user)
) -> LibraryEntry:
    """Mark a title want / in progress / finished, with an optional rating."""
    if body.rating is not None and not (0 <= body.rating <= 10):
        raise HTTPException(status_code=422, detail="Rating must be between 0 and 10.")
    if _lookup_item(item_id) is None:
        raise HTTPException(status_code=404, detail="Unknown item id.")
    store.set_library_entry(user.id, item_id, body.status, body.rating, body.note)
    row = next((r for r in store.library(user.id) if r["lib_item_id"] == item_id), None)
    if row is None:
        raise HTTPException(status_code=500, detail="Entry did not persist.")
    return _to_entry(row)


@app.delete("/api/library/{item_id:path}")
def delete_library(item_id: str, user: User = Depends(current_user)) -> dict[str, object]:
    return {"removed": store.remove_library_entry(user.id, item_id)}


@app.delete("/api/me/data")
def delete_my_data(user: User = Depends(current_user)) -> dict[str, object]:
    """Erase everything we hold for this user.

    Deleting the Supabase account cascades to the same rows, but someone may
    want to clear their library without closing the account.
    """
    return {"deleted_rows": store.delete_user_data(user.id)}


@app.get("/api/media")
def media_counts() -> dict[str, int]:
    return {m: len(store.all_items(m)) for m in ("movie", "tv", "game", "book")}


@app.get("/api/showcase", response_model=list[CatalogItem])
def showcase(limit: int = Query(48, ge=1, le=120)) -> list[CatalogItem]:
    """Popular titles with cover art, for the background wall."""
    return store.showcase(limit)


@app.get("/api/genres")
def genres(medium: Medium | None = None) -> list[dict[str, object]]:
    """The unified genre vocabulary actually present in the catalog, with counts.

    Driven by the data rather than taxonomy.UNIFIED_GENRES, so the UI never
    offers a genre that would return nothing.
    """
    counts: dict[str, int] = {}
    for item in get_model().items:
        if medium and item.medium != medium:
            continue
        for g in item.genres:
            counts[g] = counts.get(g, 0) + 1
    return [{"genre": g, "count": n}
            for g, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


class RecommendRequest(BaseModel):
    favorite_ids: list[str] = []
    target_media: list[Medium] | None = None  # None = any medium (incl. cross-media)
    seed_genres: list[str] | None = None      # cold start: taste from genres alone
    filter_genres: list[str] | None = None    # restrict results, never scores them
    genre_weight: float | None = None         # 0 = all tone, 1 = all genre, 0.5 default
    use_library: bool = True                  # ignored when signed out
    limit: int = 12


@app.post("/api/recommend")
def recommend(
    req: RecommendRequest, user: User | None = Depends(optional_user)
) -> dict[str, object]:
    """Recommend from favorites and/or chosen genres.

    Set target_media to a single medium for same-media recs, or a different one
    for the cross-media jump. With no favorites, seed_genres alone is enough -
    that is the cold-start path for someone who has not picked anything yet.
    """
    known = [fid for fid in req.favorite_ids if _lookup_item(fid) is not None]

    # A signed-in user's library is itself a statement of taste, so it counts
    # even with no favorites typed in - and its titles are never recommended
    # back to them.
    weights: dict[str, float] = {}
    if user is not None and req.use_library:
        weights = taste.weights_from_library(store.library(user.id))

    if not known and not req.seed_genres and not weights:
        raise HTTPException(
            status_code=400,
            detail="Give at least one known favorite_id, one seed genre, "
                   "or sign in and mark something in your library.",
        )
    if req.favorite_ids and not known:
        raise HTTPException(status_code=400, detail="None of the favorite_ids are in the catalog.")

    results = get_model().recommend(
        known,
        target_media=req.target_media,
        limit=req.limit,
        seed_genres=req.seed_genres,
        filter_genres=req.filter_genres,
        genre_weight=req.genre_weight,
        weights=weights,
    )
    return {
        "count": len(results),
        "results": results,
        # Say whether the library shaped this, so the UI need not guess.
        "personalized": bool(weights),
        "library_signals": len(weights),
    }

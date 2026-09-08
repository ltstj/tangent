"""TMDB (movies + TV). Needs TMDB_API_KEY (v3).

We fetch popular movies/TV and map TMDB's numeric genre_ids to names (from
/genre/*/list), then into the unified vocabulary. normalize() is pure so it's
unit-tested with a fixture; fetching hits the network.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from ..config import settings
from ..models import CatalogItem, Offer
from ..taxonomy import split_genres_tags

BASE = "https://api.themoviedb.org/3"


def _get(client: httpx.Client, path: str, **params: Any) -> dict[str, Any]:
    params["api_key"] = settings.tmdb_api_key
    return client.get(f"{BASE}{path}", params=params).json()


def genre_maps(client: httpx.Client) -> dict[str, dict[int, str]]:
    movie = _get(client, "/genre/movie/list").get("genres", [])
    tv = _get(client, "/genre/tv/list").get("genres", [])
    return {
        "movie": {g["id"]: g["name"] for g in movie},
        "tv": {g["id"]: g["name"] for g in tv},
    }


def normalize(raw: dict[str, Any], kind: str, genre_map: dict[int, str]) -> CatalogItem | None:
    tmdb_id = raw.get("id")
    title = raw.get("title") or raw.get("name")
    if not tmdb_id or not title:
        return None
    date = raw.get("release_date") or raw.get("first_air_date") or ""
    year = int(date[:4]) if date[:4].isdigit() else None
    labels = [genre_map.get(gid, "") for gid in raw.get("genre_ids", [])]
    genres, tags = split_genres_tags([g for g in labels if g])
    poster = raw.get("poster_path")
    return CatalogItem(
        id=f"{kind}:tmdb:{tmdb_id}",
        medium="movie" if kind == "movie" else "tv",
        title=title,
        year=year,
        genres=genres,
        tags=tags,
        rating=raw.get("vote_average"),
        popularity=raw.get("popularity"),
        overview=raw.get("overview", "") or "",
        image=f"https://image.tmdb.org/t/p/w342{poster}" if poster else None,
        source="tmdb",
        source_id=str(tmdb_id),
    )


# TMDB's list/search endpoints return genre ids and nothing else, so movies and
# TV arrived with zero theme tags while IGDB and Open Library supplied plenty.
# That left the shared taste space lopsided: a TMDB title could only ever match
# on broad genres like "action" (29% of the catalog), so generic blockbusters
# outranked the title that actually shared its specific vibe. Keywords come from
# a per-title endpoint, so they need their own fanned-out pass.
MAX_TAGS = 12


def fetch_keywords(client: httpx.Client, kind: str, tmdb_id: str) -> list[str]:
    """Raw keyword labels for one title. Movies nest them under "keywords",
    TV under "results" - same endpoint shape otherwise."""
    data = _get(client, f"/{kind}/{tmdb_id}/keywords")
    raw = data.get("keywords") if kind == "movie" else data.get("results")
    return [k.get("name", "") for k in (raw or []) if k.get("name")]


def enrich_keywords(items: list[CatalogItem], max_workers: int = 8) -> list[CatalogItem]:
    """Attach TMDB keywords to `items` in place, concurrently. Best-effort: a
    title whose lookup fails simply keeps the tags it already had."""
    if not settings.tmdb_api_key or not items:
        return items

    def one(item: CatalogItem) -> None:
        kind = "movie" if item.medium == "movie" else "tv"
        with httpx.Client(timeout=15) as client:
            labels = fetch_keywords(client, kind, item.source_id)
        if not labels:
            return
        genres, tags = split_genres_tags(labels)
        item.genres = list(dict.fromkeys([*item.genres, *genres]))
        item.tags = list(dict.fromkeys([*item.tags, *tags]))[:MAX_TAGS]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for fut in [pool.submit(one, i) for i in items]:
            try:
                fut.result()
            except Exception:
                pass
    return items


# Watch providers. TMDB sources this from JustWatch and their terms require
# attributing them, so ATTRIBUTION travels with the data rather than living in a
# comment someone can drop.
DEFAULT_REGION = "US"
ATTRIBUTION = "Streaming availability from JustWatch, via TMDB."

# What TMDB calls each bucket -> what it means for the caller. Note the thing
# this cannot do: TMDB returns provider_id, provider_name, logo_path and
# display_priority, and *no price field at all* - verified across three titles
# and all 117 regions. So a rent or buy offer here says where, never how much.
# "Cheapest subscription that has it" needs a maintained price table on our side;
# inventing a number to fill the field would be worse than leaving it null.
_BUCKETS: dict[str, tuple[str, str]] = {
    "flatrate": ("subscription", ""),
    "free": ("free", ""),
    "ads": ("free", "with ads"),
    "rent": ("rent", "price not published by TMDB"),
    "buy": ("buy", "price not published by TMDB"),
}


# TMDB lists the same service several times: once directly, once per reseller
# channel ("HBO Max" and "HBO Max Amazon Channel"), and once per ad tier
# ("Amazon Prime Video" and "Amazon Prime Video with Ads"). All of those are the
# same answer to "where can I watch this", so they collapse to one row. Tier
# names that mean a genuinely different price - Paramount Plus Premium versus
# Essential - are deliberately left alone.
_CHANNEL_SUFFIXES = (
    " amazon channel", " apple tv channel", " roku premium channel", " channel",
)
_ADS_SUFFIXES = (" free with ads", " with ads")


def store_key(name: str) -> str:
    """Dedup key for a provider: the service, minus how you get to it."""
    key = re.sub(r"\s+", " ", name.lower().replace("+", " plus")).strip()
    for suffix in _ADS_SUFFIXES + _CHANNEL_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
    return key


def _has_ads(name: str) -> bool:
    return "with ads" in name.lower()


def normalize_providers(
    payload: dict[str, Any], region: str = DEFAULT_REGION, limit: int = 8
) -> list[Offer]:
    """A /watch/providers response -> Offers for one region. Pure.

    Subscriptions come first (that is the cheapest route if you already pay for
    one), then free, then rent, then buy; within a bucket TMDB's own
    display_priority decides, which roughly tracks how mainstream a provider is.
    """
    region_data = (payload.get("results") or {}).get(region.upper()) or {}
    link = region_data.get("link") or ""
    order = ["flatrate", "free", "ads", "rent", "buy"]
    offers: list[Offer] = []
    for bucket in order:
        rows = region_data.get(bucket)
        if not isinstance(rows, list):
            continue
        for row in sorted(rows, key=lambda r: r.get("display_priority", 999)):
            name = row.get("provider_name")
            if not name:
                continue
            kind, note = _BUCKETS[bucket]
            if _has_ads(name) and not note:
                note = "with ads"
            offers.append(Offer(kind=kind, store=name, url=link, price=None, note=note))

    # One row per service per kind, in display_priority order. Within a group
    # show the plainest name: TMDB sometimes ranks a reseller above the service
    # itself, and "HBO Max" is a better answer than "HBO Max Amazon Channel"
    # even when TMDB lists the latter first. Shortest name is that name.
    kept: dict[tuple[str, str], Offer] = {}
    for offer in offers:
        key = (offer.kind, store_key(offer.store))
        existing = kept.get(key)
        if existing is None:
            kept[key] = offer
        elif len(offer.store) < len(existing.store):
            existing.store = offer.store
    return list(kept.values())[:limit]


def watch_providers(kind: str, tmdb_id: str, region: str = DEFAULT_REGION,
                    limit: int = 8) -> list[Offer]:
    """Live lookup of where to watch one title. [] if no key or nothing listed."""
    if not settings.tmdb_api_key or not tmdb_id:
        return []
    with httpx.Client(timeout=15) as client:
        payload = _get(client, f"/{kind}/{tmdb_id}/watch/providers")
    return normalize_providers(payload, region=region, limit=limit)


_GENRE_CACHE: dict[str, dict[int, str]] | None = None


def _cached_genre_maps(client: httpx.Client) -> dict[str, dict[int, str]]:
    global _GENRE_CACHE
    if _GENRE_CACHE is None:
        _GENRE_CACHE = genre_maps(client)
    return _GENRE_CACHE


def search_multi(query: str, limit: int = 8) -> list[CatalogItem]:
    """Live TMDB search across movies + TV (for autocomplete). [] if no key."""
    if not settings.tmdb_api_key:
        return []
    with httpx.Client(timeout=15) as client:
        maps = _cached_genre_maps(client)
        data = _get(client, "/search/multi", query=query, page=1)
    out: list[CatalogItem] = []
    for raw in data.get("results", []):
        mt = raw.get("media_type")
        if mt not in ("movie", "tv"):
            continue
        item = normalize(raw, mt, maps.get(mt, {}))
        if item:
            out.append(item)
        if len(out) >= limit:
            break
    return out


def fetch_popular(kind: str = "movie", pages: int = 2) -> list[CatalogItem]:
    if not settings.tmdb_api_key:
        raise RuntimeError("TMDB_API_KEY is not set")
    items: list[CatalogItem] = []
    with httpx.Client(timeout=30) as client:
        gmap = genre_maps(client)[kind]
        for page in range(1, pages + 1):
            data = _get(client, f"/{kind}/popular", page=page)
            for raw in data.get("results", []):
                it = normalize(raw, kind, gmap)
                if it:
                    items.append(it)
    return enrich_keywords(items)

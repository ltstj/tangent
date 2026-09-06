"""TMDB (movies + TV). Needs TMDB_API_KEY (v3).

We fetch popular movies/TV and map TMDB's numeric genre_ids to names (from
/genre/*/list), then into the unified vocabulary. normalize() is pure so it's
unit-tested with a fixture; fetching hits the network.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from ..models import CatalogItem
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
    return items

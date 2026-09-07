"""IGDB (games). Needs IGDB_CLIENT_ID + IGDB_CLIENT_SECRET (Twitch app creds).

Auth is Twitch OAuth client-credentials; then we query IGDB's games endpoint.
normalize() is pure (unit-tested with a fixture); fetching hits the network.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from ..models import CatalogItem
from ..taxonomy import split_genres_tags

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
# IGDB keyword lists run long on big titles; keep the most relevant handful.
MAX_KEYWORDS = 14
BASE = "https://api.igdb.com/v4"


def _token(client: httpx.Client) -> str:
    resp = client.post(TOKEN_URL, params={
        "client_id": settings.igdb_client_id,
        "client_secret": settings.igdb_client_secret,
        "grant_type": "client_credentials",
    })
    return resp.json()["access_token"]


def normalize(raw: dict[str, Any]) -> CatalogItem | None:
    igdb_id = raw.get("id")
    title = raw.get("name")
    if not igdb_id or not title:
        return None
    # IGDB expands genres/themes to objects with "name" when requested.
    labels = [g.get("name", "") for g in raw.get("genres", [])]
    labels += [t.get("name", "") for t in raw.get("themes", [])]
    # IGDB "themes" is a ~12-value gameplay vocabulary (openworld, stealth,
    # sandbox...), which says nothing about subject matter. "keywords" is where
    # the thematic signal lives - medieval, dragons, post-apocalyptic - and it is
    # what lets a game match a show or a novel on more than a broad genre.
    labels += [k.get("name", "") for k in raw.get("keywords", [])][:MAX_KEYWORDS]
    genres, tags = split_genres_tags([label for label in labels if label])
    year = None
    if raw.get("first_release_date"):
        # epoch seconds -> year, without Date.now (pure arithmetic).
        year = 1970 + int(raw["first_release_date"]) // 31_557_600
    rating = raw.get("total_rating")
    cover = (raw.get("cover") or {}).get("url")
    image = None
    if cover:
        image = "https:" + cover.replace("t_thumb", "t_cover_big")
    return CatalogItem(
        id=f"game:igdb:{igdb_id}",
        medium="game",
        title=title,
        year=year,
        genres=genres,
        tags=tags,
        rating=round(rating / 10, 1) if rating else None,  # IGDB is 0..100
        popularity=raw.get("total_rating_count"),
        overview=raw.get("summary", "") or "",
        image=image,
        source="igdb",
        source_id=str(igdb_id),
    )


_TOKEN_CACHE: str | None = None


def _cached_token(client: httpx.Client) -> str:
    global _TOKEN_CACHE
    if _TOKEN_CACHE is None:
        _TOKEN_CACHE = _token(client)
    return _TOKEN_CACHE


def search(query: str, limit: int = 8) -> list[CatalogItem]:
    """Live IGDB game search (for autocomplete). [] if creds are missing."""
    if not (settings.igdb_client_id and settings.igdb_client_secret):
        return []
    safe = query.replace('"', "").strip()
    if not safe:
        return []
    with httpx.Client(timeout=15) as client:
        token = _cached_token(client)
        headers = {"Client-ID": settings.igdb_client_id, "Authorization": f"Bearer {token}"}
        body = (
            f'search "{safe}"; fields name, summary, cover.url, genres.name, themes.name, keywords.name, '
            f"total_rating, total_rating_count, first_release_date; limit {limit};"
        )
        data = client.post(f"{BASE}/games", headers=headers, content=body).json()
    out = [normalize(raw) for raw in data]
    return [i for i in out if i]


def fetch_popular(limit: int = 100) -> list[CatalogItem]:
    if not (settings.igdb_client_id and settings.igdb_client_secret):
        raise RuntimeError("IGDB_CLIENT_ID / IGDB_CLIENT_SECRET are not set")
    with httpx.Client(timeout=30) as client:
        token = _token(client)
        headers = {"Client-ID": settings.igdb_client_id, "Authorization": f"Bearer {token}"}
        body = (
            "fields name, summary, cover.url, genres.name, themes.name, keywords.name, total_rating, "
            "total_rating_count, first_release_date; "
            f"sort total_rating_count desc; where total_rating_count > 50; limit {limit};"
        )
        data = client.post(f"{BASE}/games", headers=headers, content=body).json()
    out = [normalize(raw) for raw in data]
    return [i for i in out if i]

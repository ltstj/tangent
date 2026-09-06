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
    genres, tags = split_genres_tags([label for label in labels if label])
    year = None
    if raw.get("first_release_date"):
        # epoch seconds -> year, without Date.now (pure arithmetic).
        year = 1970 + int(raw["first_release_date"]) // 31_557_600
    rating = raw.get("total_rating")
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
        source="igdb",
        source_id=str(igdb_id),
    )


def fetch_popular(limit: int = 100) -> list[CatalogItem]:
    if not (settings.igdb_client_id and settings.igdb_client_secret):
        raise RuntimeError("IGDB_CLIENT_ID / IGDB_CLIENT_SECRET are not set")
    with httpx.Client(timeout=30) as client:
        token = _token(client)
        headers = {"Client-ID": settings.igdb_client_id, "Authorization": f"Bearer {token}"}
        body = (
            "fields name, summary, genres.name, themes.name, total_rating, "
            "total_rating_count, first_release_date; "
            f"sort total_rating_count desc; where total_rating_count > 50; limit {limit};"
        )
        data = client.post(f"{BASE}/games", headers=headers, content=body).json()
    out = [normalize(raw) for raw in data]
    return [i for i in out if i]

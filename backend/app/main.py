"""Tangent API entrypoint.

Phase 0: health + a config-readiness probe (which integrations have keys). The
recommender, catalog ingest, and search land in Phase 1 (see ../../ROADMAP.md).
"""
from __future__ import annotations

from fastapi import FastAPI

from .config import settings

app = FastAPI(title="Tangent API", version="0.0.1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/ready")
def ready() -> dict[str, object]:
    """Which integrations are configured (booleans only; never echoes secrets)."""
    return {
        "tmdb": bool(settings.tmdb_api_key),
        "igdb": bool(settings.igdb_client_id and settings.igdb_client_secret),
        "supabase": bool(settings.supabase_url and settings.database_url),
        "openlibrary": True,  # no key needed
        "cheapshark": True,   # no key needed
    }

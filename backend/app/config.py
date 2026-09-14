"""App settings, loaded from environment (see ../../.env.example).

No secrets in code: API keys and the database URL come from env only. Missing
keys are allowed here (empty strings) so the app boots for local dev before every
integration is wired.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"

    # Browser origins allowed to call this API, comma-separated. The permissive
    # "*" that was here is fine on a laptop and wrong facing the internet: it
    # lets any site issue credentialed requests on a visitor's behalf.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Per-IP, per-minute caps on the endpoints that spend third-party quota.
    # Google Books allows 1,000 requests/day and IsThereAnyDeal rate-limits
    # aggressively enough to trip during ordinary testing, so an open instance
    # can burn someone else's budget in minutes.
    rate_limit_search_per_min: int = 30
    rate_limit_offers_per_min: int = 30

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() not in ("dev", "development", "local", "test")

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Data sources
    tmdb_api_key: str = ""
    igdb_client_id: str = ""
    igdb_client_secret: str = ""
    # Open Library + CheapShark need no key.
    # Google Books: ebook retail prices for the book medium. Keyless requests
    # share a global quota that is routinely exhausted (HTTP 429), so a key is
    # what makes this dependable rather than optional.
    google_books_api_key: str = ""
    # IsThereAnyDeal: regional game prices, which CheapShark cannot provide.
    itad_api_key: str = ""

    # Supabase / Postgres (pgvector)
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""


settings = Settings()

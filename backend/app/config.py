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

    # Data sources
    tmdb_api_key: str = ""
    igdb_client_id: str = ""
    igdb_client_secret: str = ""
    # Open Library + CheapShark need no key.

    # Supabase / Postgres (pgvector)
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""


settings = Settings()

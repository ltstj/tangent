"""Verifying Supabase access tokens.

The frontend signs in with Supabase directly and sends the resulting access
token to us; this module turns that token into a user id, or refuses it.

This project's tokens are **ES256** signed against a published JWKS
(/auth/v1/.well-known/jwks.json), which is worth knowing because it decides the
whole approach: verification is local against public keys, so there is no shared
secret to leak and no network round-trip per request once the keys are cached.
Older Supabase projects use a symmetric HS256 secret instead - if this ever
starts failing after a project migration, that is the first thing to check.

We deliberately do not accept the anon/publishable key as authentication. It is
public by design and identifies the project, not a person.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from .config import settings

# Supabase mints access tokens with this audience by default.
AUDIENCE = "authenticated"
_JWKS_TTL_S = 3600.0

_jwk_client: PyJWKClient | None = None
_jwk_fetched_at = 0.0


@dataclass(frozen=True)
class User:
    """Just enough identity to own rows. We store no profile of our own."""

    id: str
    email: str | None = None


def _jwks_url() -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _client() -> PyJWKClient:
    """Cached JWKS client. Refreshed hourly so key rotation is picked up without
    a restart, but not per request."""
    global _jwk_client, _jwk_fetched_at
    now = time.monotonic()
    if _jwk_client is None or now - _jwk_fetched_at > _JWKS_TTL_S:
        _jwk_client = PyJWKClient(_jwks_url(), cache_keys=True)
        _jwk_fetched_at = now
    return _jwk_client


def verify_token(token: str) -> User:
    """Access token -> User. Raises HTTPException(401) on anything suspect."""
    if not settings.supabase_url:
        raise HTTPException(status_code=503, detail="Auth is not configured.")
    try:
        signing_key = _client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience=AUDIENCE,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired; sign in again.")
    except (jwt.InvalidTokenError, httpx.HTTPError, Exception) as exc:
        # Deliberately opaque to the caller: a verification failure should not
        # explain *why* to whoever supplied the token.
        raise HTTPException(status_code=401, detail="Invalid session.") from exc

    subject = claims.get("sub")
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid session.")
    return User(id=str(subject), email=claims.get("email"))


def current_user(authorization: str | None = Header(default=None)) -> User:
    """FastAPI dependency for endpoints that require a signed-in user."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to use this.")
    return verify_token(authorization.split(" ", 1)[1].strip())


def optional_user(authorization: str | None = Header(default=None)) -> User | None:
    """For endpoints that work signed out but do more when signed in."""
    if not authorization:
        return None
    try:
        return current_user(authorization)
    except HTTPException:
        return None

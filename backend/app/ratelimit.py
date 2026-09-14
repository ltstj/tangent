"""Per-IP rate limiting for the endpoints that spend third-party quota.

Search and offers reach out to TMDB, IGDB, Open Library, CheapShark,
IsThereAnyDeal and Google Books. Those are our keys and our budgets: Google
Books allows 1,000 requests a day, and IsThereAnyDeal rate-limited us during
ordinary development testing. Without a cap, a shared link lets anyone exhaust
both in minutes.

Deliberately dependency-free and in-process. That means the limit is per worker
rather than per cluster, which is the honest trade for a single-instance app -
if this ever runs more than one process the limit multiplies, and it would want
Redis instead. Recommendation and library endpoints are uncapped: they touch
only our own database.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request

_WINDOW_S = 60.0
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_lock = Lock()


def client_key(request: Request) -> str:
    """Best-effort client identity.

    X-Forwarded-For is only meaningful behind a proxy that sets it, and is
    trivially spoofed otherwise - so this is a courtesy limit that shapes
    ordinary traffic, not a defence against a determined abuser.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(bucket: str, key: str, per_minute: int) -> None:
    """Raise 429 if `key` has exceeded `per_minute` in this bucket."""
    if per_minute <= 0:
        return
    now = time.monotonic()
    cutoff = now - _WINDOW_S
    with _lock:
        seen = _hits[(bucket, key)]
        while seen and seen[0] < cutoff:
            seen.popleft()
        if len(seen) >= per_minute:
            retry = max(1, int(_WINDOW_S - (now - seen[0])))
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests; try again in {retry}s.",
                headers={"Retry-After": str(retry)},
            )
        seen.append(now)
        # Keep the dict from growing without bound on a long-lived process.
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v or v[-1] < cutoff]:
                _hits.pop(k, None)


def limit(bucket: str, per_minute_getter) -> object:
    """Build a FastAPI dependency enforcing one bucket."""

    def dependency(request: Request) -> None:
        check(bucket, client_key(request), per_minute_getter())

    return dependency

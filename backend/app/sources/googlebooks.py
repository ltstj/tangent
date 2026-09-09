"""Google Books: ebook retail prices for the book medium.

Books were the one medium with no prices at all - Open Library has none, and
there is no free API for print retail across sellers - so they got link-outs
only. Google Books does publish a real price for the Play Store ebook edition,
which is a genuine answer to "how much does this cost" even though it is one
seller and one format.

Two things to know:

- **A key matters here.** Keyless requests share a global quota that is
  routinely exhausted; testing this returned HTTP 429 outright. Without
  GOOGLE_BOOKS_API_KEY set, this returns nothing rather than half-working.
- **It is genuinely regional.** The `country` parameter changes the price and
  currency, unlike CheapShark which ignores every region parameter it is given.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from ..config import settings
from ..models import Offer

BASE = "https://www.googleapis.com/books/v1/volumes"

# Google returns matching volumes in a non-stable order, so a for-sale edition
# can fall outside a short result window - "Foundation" matched at 40 results and
# missed at 10 on identical queries. A wider window costs one request either way.
MAX_RESULTS = 40


def _norm(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())


def clean_title(title: str) -> str:
    """Strip the packaging our catalog titles carry and Google's do not.

    Open Library records titles like "The Dark Forest (The Three-Body Problem
    Series Book 2)"; Google has plain "The Dark Forest". Exact matching on the
    raw string therefore missed books that are on sale.
    """
    out = re.sub(r"\s*[\(\[][^)\]]*[)\]]", "", title)
    out = re.sub(r"\s*[:;-]\s*(a novel|a memoir|a story)\s*$", "", out, flags=re.I)
    return out.strip() or title.strip()


def _price_of(item: dict[str, Any]) -> float | None:
    amount = ((item.get("saleInfo") or {}).get("retailPrice") or {}).get("amount")
    try:
        return float(amount) if amount is not None else None
    except (TypeError, ValueError):
        return None


def pick_volume(items: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    """The cheapest for-sale volume whose title matches ours. Pure.

    An exact normalized title match is required because a search for one novel
    readily returns study guides, summaries and box sets, and quoting one of
    those as the book's price would be wrong.

    Cheapest rather than first, for two reasons. Google returns matching volumes
    in an unstable order, so "first" made the price depend on luck - the same
    query for "Artemis" returned Andy Weir's novel at $8.22 on one call and a
    same-titled academic book at $47.19 on another. And when several distinct
    works share a title, the cheapest is both the deterministic answer and the
    honest one to "how much does this cost".
    """
    want = _norm(clean_title(title))
    candidates = []
    for item in items:
        info = item.get("volumeInfo") or {}
        sale = item.get("saleInfo") or {}
        # Both sides cleaned, so the comparison is symmetric.
        if _norm(clean_title(info.get("title", ""))) != want:
            continue
        if sale.get("saleability") != "FOR_SALE":
            continue
        price = _price_of(item)
        if price is None:
            continue
        candidates.append((price, item))
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[0])[1]


def normalize_volume(item: dict[str, Any]) -> Offer | None:
    """A volume -> a priced ebook Offer. Pure."""
    sale = item.get("saleInfo") or {}
    retail = sale.get("retailPrice") or {}
    listed = sale.get("listPrice") or {}
    amount = retail.get("amount")
    if amount is None:
        return None
    try:
        price = float(amount)
        was = float(listed["amount"]) if listed.get("amount") is not None else None
    except (TypeError, ValueError):
        return None
    return Offer(
        kind="buy",
        store="Google Play Books",
        url=sale.get("buyLink") or "https://play.google.com/store/books",
        price=price,
        currency=retail.get("currencyCode") or "USD",
        was=was if was and was > price else None,
        note="ebook",
    )


def ebook_offer(title: str, region: str = "US") -> Offer | None:
    """Live lookup of the Play Books price for one title. None if no key, no
    match, or nothing for sale. Raises on transport failure so the caller can
    tell an outage from an absence."""
    if not settings.google_books_api_key or not title.strip():
        return None
    params = {
        "q": f'intitle:"{clean_title(title)}"',
        "maxResults": MAX_RESULTS,
        "country": region.upper(),
        "key": settings.google_books_api_key,
    }
    with httpx.Client(timeout=15) as client:
        payload = client.get(BASE, params=params).json()
    match = pick_volume(payload.get("items") or [], title)
    return normalize_volume(match) if match else None

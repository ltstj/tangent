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

from typing import Any

import httpx

from ..config import settings
from ..models import Offer

BASE = "https://www.googleapis.com/books/v1/volumes"


def _norm(title: str) -> str:
    return "".join(ch for ch in title.lower() if ch.isalnum())


def pick_volume(items: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    """The for-sale volume whose title matches ours. Pure.

    Requires an exact normalized title match: a search for one novel readily
    returns study guides, summaries and box sets, and quoting one of those as
    the book's price would be wrong.
    """
    want = _norm(title)
    for item in items:
        info = item.get("volumeInfo") or {}
        sale = item.get("saleInfo") or {}
        if _norm(info.get("title", "")) != want:
            continue
        if sale.get("saleability") != "FOR_SALE":
            continue
        if (sale.get("retailPrice") or {}).get("amount") is None:
            continue
        return item
    return None


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
        "q": f'intitle:"{title}"',
        "maxResults": 10,
        "country": region.upper(),
        "key": settings.google_books_api_key,
    }
    with httpx.Client(timeout=15) as client:
        payload = client.get(BASE, params=params).json()
    match = pick_volume(payload.get("items") or [], title)
    return normalize_volume(match) if match else None

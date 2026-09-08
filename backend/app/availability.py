"""Where to get a title, and for how much.

Phase 3. Dispatches per medium, because each one has a genuinely different
answer available:

- **games**: real prices from CheapShark across ~35 storefronts.
- **books**: link-outs only. There is no free API that gives honest, current
  retail book prices across sellers, so this hands over search URLs - including
  "check your library" - rather than inventing numbers. ROADMAP.md is explicit
  about that: no scraping, no fabricated prices.
- **movies/tv**: TMDB watch-providers (JustWatch data) - which services carry
  it, on subscription, rent or buy. TMDB publishes no prices, so these say
  where and not how much. See tmdb.normalize_providers.

A caller can always tell the difference: a priced offer has `price` set, a
pointer has `kind == "link"` and `price is None`.
"""
from __future__ import annotations

from urllib.parse import quote_plus

from . import subscriptions
from .models import CatalogItem, Offer
from .sources import cheapshark, tmdb


def _book_links(item: CatalogItem) -> list[Offer]:
    """Honest pointers for a book. No prices, because we cannot source them."""
    q = quote_plus(item.title)
    links = [
        ("Bookshop.org", f"https://bookshop.org/search?keywords={q}",
         "supports independent bookshops"),
        ("Open Library", f"https://openlibrary.org/search?q={q}",
         "borrow or read online"),
        ("WorldCat", f"https://search.worldcat.org/search?q={q}",
         "check your local library"),
    ]
    return [Offer(kind="link", store=store, url=url, note=note)
            for store, url, note in links]


def offers_for(
    item: CatalogItem,
    limit: int = 6,
    region: str = "US",
    price_rows: list[dict] | None = None,
) -> list[Offer]:
    """Ways to get `item`, priced where we can source a price honestly.

    `price_rows` is the subscription price table; passed in rather than fetched
    here so this stays a pure dispatch and the caller controls the query.
    """
    if item.medium == "game":
        try:
            return cheapshark.offers_for_title(item.title, limit=limit)
        except Exception:
            return []   # a pricing outage must not break the page
    if item.medium == "book":
        return _book_links(item)
    if item.medium in ("movie", "tv") and item.source == "tmdb":
        try:
            found = tmdb.watch_providers(
                "movie" if item.medium == "movie" else "tv",
                item.source_id, region=region, limit=limit,
            )
        except Exception:
            return []
        if found and price_rows is not None:
            subscriptions.annotate(found, price_rows)
        return found
    return []

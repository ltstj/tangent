"""Where to get a title, and for how much.

Phase 3. Dispatches per medium, because each one has a genuinely different
answer available - and, importantly, reports *which* answer it gave:

- **games**: IsThereAnyDeal when a key is configured - real prices in the
  caller's own currency, per country - falling back to CheapShark, which is
  keyless but US/USD only.
- **movies/tv**: TMDB watch-providers (JustWatch data), genuinely per-region.
  Which services carry it, on subscription, rent or buy - TMDB publishes no
  prices, so these say where and not how much.
- **books**: link-outs always, plus a real Google Play ebook price when
  GOOGLE_BOOKS_API_KEY is set. There is still no free source for *print* retail
  across sellers, so the link-outs stay.

Every result carries a status, because "we could not reach the price source" and
"this genuinely has no offers" are different facts and rendering them the same
way tells the reader something we do not know.
"""
from __future__ import annotations

import time
from threading import Lock
from urllib.parse import quote_plus

from . import subscriptions
from .config import settings
from .models import Availability, CatalogItem, Offer
from .sources import cheapshark, googlebooks, itad, tmdb

# Offers were a live external call on every panel expand - 500-700ms each, and a
# request to a free service for every click. Cache per medium at roughly the rate
# the underlying data moves: game deals rotate daily, streaming rights monthly,
# and book links are constructed URLs that never go stale at all.
_TTL_SECONDS = {"game": 900, "movie": 3600, "tv": 3600, "book": 86_400}

_cache: dict[tuple[str, str, int], tuple[float, Availability]] = {}
_cache_lock = Lock()


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


def _books(item: CatalogItem, region: str) -> Availability:
    """Link-outs, plus a priced ebook when we have a key for it."""
    offers = _book_links(item)
    notes: list[str] = []
    priced_region = None
    try:
        ebook = googlebooks.ebook_offer(item.title, region=region)
    except Exception as exc:
        notes.append(f"Ebook price unavailable ({type(exc).__name__}).")
        ebook = None
    if ebook is not None:
        # Priced offer first: it is the only number on the panel.
        offers = [ebook, *offers]
        priced_region = region.upper()
    elif not settings.google_books_api_key:
        notes.append("Set GOOGLE_BOOKS_API_KEY for ebook prices.")
    return Availability(offers=offers, status="ok", price_region=priced_region, notes=notes)


def _cheapshark(item: CatalogItem, limit: int, region: str,
                extra_notes: list[str] | None = None) -> Availability:
    """Keyless fallback. US/USD only, and labelled as such."""
    try:
        offers, notes = cheapshark.offers_for_title(item.title, limit=limit)
    except Exception as exc:
        return Availability(
            status="source_unavailable",
            detail=f"Could not reach CheapShark ({type(exc).__name__}).",
        )
    notes = [*(extra_notes or []), *notes]
    # CheapShark ignores every region parameter it is given, so saying "here are
    # prices for GB" would be a lie. Label them instead.
    if region.upper() != cheapshark.PRICE_REGION:
        notes.append(f"Prices are {cheapshark.PRICE_REGION} storefronts in USD.")
    return Availability(
        offers=offers,
        status="ok" if offers else "none_listed",
        detail="" if offers else "No current deals listed.",
        price_region=cheapshark.PRICE_REGION,
        notes=notes,
    )


def _games(item: CatalogItem, limit: int, region: str) -> Availability:
    """IsThereAnyDeal first when we have a key: it prices in the caller's own
    currency and reports the historical low, so it supersedes CheapShark."""
    if not settings.itad_api_key:
        return _cheapshark(item, limit, region)
    try:
        offers, notes = itad.offers_for_title(item.title, country=region, limit=limit)
    except Exception as exc:
        # Degrade to US prices rather than showing nothing, but say so - a
        # silent currency switch would be worse than an explicit downgrade.
        return _cheapshark(
            item, limit, region,
            extra_notes=[f"Regional pricing unavailable ({type(exc).__name__})."],
        )
    if not offers:
        # ITAD knows the game but has no deals in this country; CheapShark may
        # still have a US price, which beats an empty panel.
        return _cheapshark(item, limit, region,
                           extra_notes=[f"No {region.upper()} deals listed."])
    return Availability(
        offers=offers,
        status="ok",
        price_region=region.upper(),
        notes=notes,
    )


def _watch(item: CatalogItem, limit: int, region: str,
           price_rows: list[dict] | None) -> Availability:
    if item.source != "tmdb" or not item.source_id:
        return Availability(
            status="not_supported",
            detail="No TMDB id for this title, so availability cannot be looked up.",
        )
    try:
        offers = tmdb.watch_providers(
            "movie" if item.medium == "movie" else "tv",
            item.source_id, region=region, limit=limit,
        )
    except Exception as exc:
        return Availability(
            status="source_unavailable",
            detail=f"Could not reach TMDB ({type(exc).__name__}).",
        )
    if offers and price_rows is not None:
        subscriptions.annotate(offers, price_rows)
    return Availability(
        offers=offers,
        status="ok" if offers else "none_listed",
        detail="" if offers else f"Nothing listed for {region.upper()}.",
        price_region=region.upper(),
    )


def availability_for(
    item: CatalogItem,
    limit: int = 6,
    region: str = "US",
    price_rows: list[dict] | None = None,
) -> Availability:
    """Ways to get `item`, priced where we can source a price honestly.

    Cached per (item, region, limit). Failures are deliberately not cached - a
    transient outage should not pin "unavailable" for the whole TTL.
    """
    key = (item.id, region.upper(), limit)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now < hit[0]:
            return hit[1]

    if item.medium == "game":
        result = _games(item, limit, region)
    elif item.medium == "book":
        result = _books(item, region)
    elif item.medium in ("movie", "tv"):
        result = _watch(item, limit, region, price_rows)
    else:
        result = Availability(status="not_supported", detail="Unsupported medium.")

    if result.status in ("ok", "none_listed"):
        with _cache_lock:
            _cache[key] = (now + _TTL_SECONDS.get(item.medium, 900), result)
    return result


def offers_for(item: CatalogItem, limit: int = 6, region: str = "US",
               price_rows: list[dict] | None = None) -> list[Offer]:
    """Back-compat shim: just the offers. Prefer availability_for for the status."""
    return availability_for(item, limit=limit, region=region, price_rows=price_rows).offers

"""CheapShark: current game prices across storefronts. No API key required.

CheapShark aggregates live deals from ~35 PC stores and, usefully, also reports
`cheapestPriceEver` per game - the historical low that ROADMAP.md assigns to
IsThereAnyDeal. That may make the second integration unnecessary.

Two things this module has to get right:

- **A descriptive User-Agent is mandatory.** A generic one gets a 400 with
  "Missing or generic User-Agent header detected". Their docs suggest including
  a contact email; we point at the public repo instead, so no personal address
  is sent to a third party.
- **Titles do not match ours.** CheapShark says "ELDEN RING", IGDB says "Elden
  Ring", and a title search also returns editions ("ELDEN RING Deluxe Edition")
  and sequels ("ELDEN RING NIGHTREIGN"). Matching is normalized and prefers an
  exact hit, so a search for a base game does not return its deluxe edition's
  price.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from ..models import Offer

BASE = "https://www.cheapshark.com/api/1.0"
# CheapShark has no regional support: country, region, currency and cc are all
# ignored and /stores carries no region field. Everything it returns is USD from
# US storefronts, so callers must label it rather than imply local pricing.
PRICE_REGION = "US"
# Identifies us and gives them a way to reach a human, without sending anyone's
# email address to a third-party service.
USER_AGENT = "Tangent/0.1 (+https://github.com/ltstj/tangent)"
REDIRECT = "https://www.cheapshark.com/redirect?dealID="

_HEADERS = {"User-Agent": USER_AGENT}
_STORE_CACHE: dict[str, str] | None = None


def _client() -> httpx.Client:
    return httpx.Client(timeout=20, follow_redirects=True, headers=_HEADERS)


def _norm(title: str) -> str:
    """Comparison key for titles: case, punctuation and spacing all differ
    between sources, and none of those differences mean anything."""
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def stores(client: httpx.Client | None = None) -> dict[str, str]:
    """storeID -> store name, for active stores. Cached; the list rarely moves."""
    global _STORE_CACHE
    if _STORE_CACHE is not None:
        return _STORE_CACHE
    owned = client is None
    client = client or _client()
    try:
        rows = client.get(f"{BASE}/stores").json()
    finally:
        if owned:
            client.close()
    _STORE_CACHE = {
        str(r["storeID"]): r["storeName"]
        for r in rows
        if isinstance(r, dict) and str(r.get("isActive")) == "1"
    }
    return _STORE_CACHE


def pick_game(rows: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    """Best match for `title` among CheapShark search rows.

    Exact normalized match wins; otherwise the shortest title that contains ours,
    which prefers the base game over its editions and bundles. Pure, so it is
    unit-tested without network.
    """
    if not rows:
        return None
    want = _norm(title)
    exact = [r for r in rows if _norm(r.get("external", "")) == want]
    if exact:
        return exact[0]
    contains = [r for r in rows if want and want in _norm(r.get("external", ""))]
    if contains:
        return min(contains, key=lambda r: len(r.get("external", "")))
    return None


def normalize_deals(
    payload: dict[str, Any], store_names: dict[str, str], limit: int = 6
) -> list[Offer]:
    """A /games?id= response -> Offers, cheapest first. Pure."""
    deals = payload.get("deals") or []
    ever = payload.get("cheapestPriceEver") or {}
    try:
        low = float(ever.get("price")) if ever.get("price") is not None else None
    except (TypeError, ValueError):
        low = None

    offers: list[Offer] = []
    for deal in deals:
        try:
            price = float(deal["price"])
            retail = float(deal["retailPrice"])
        except (KeyError, TypeError, ValueError):
            continue
        store_id = str(deal.get("storeID"))
        note = ""
        # Only claim a historical low when this deal actually matches it.
        if low is not None and abs(price - low) < 0.01:
            note = "historical low"
        elif low is not None and price > low:
            note = f"low was ${low:.2f}"
        offers.append(
            Offer(
                kind="free" if price == 0 else "buy",
                store=store_names.get(store_id, f"store {store_id}"),
                url=f"{REDIRECT}{deal.get('dealID', '')}",
                price=price,
                was=retail if retail > price else None,
                note=note,
            )
        )
    offers.sort(key=lambda o: (o.price if o.price is not None else 1e9))
    return offers[:limit]


# An edition is a different way to buy the same game. DLC is not: "The Witcher
# 3 - Hearts of Stone" at $9.99 is an expansion that *requires* the base game, so
# offering it as a cheaper alternative would be plainly wrong. A title search
# returns both, so candidates must carry an actual edition marker - a whitelist,
# because guessing which unmarked subtitles are DLC is the mistake this avoids.
_EDITION_MARKERS = (
    "complete edition", "definitive edition", "deluxe edition", "ultimate edition",
    "gold edition", "enhanced edition", "anniversary edition", "special edition",
    "game of the year", "goty", "remastered", "collection", "royal edition",
)


def cheaper_edition(rows: list[dict[str, Any]], match: dict[str, Any]) -> dict[str, Any] | None:
    """A cheaper *edition* of the game we matched, or None.

    The title search already returns every edition with its cheapest price, so
    this is free information we were otherwise discarding - and it is often the
    most useful line on the panel: The Witcher 3 base game is $39.99 while its
    Complete Edition is $24.99, which is cheaper *and* more content. Pure.
    """
    try:
        ours = float(match.get("cheapest"))
    except (TypeError, ValueError):
        return None
    ours_key = _norm(match.get("external", ""))
    best: dict[str, Any] | None = None
    for row in rows:
        if row.get("gameID") == match.get("gameID"):
            continue
        title = row.get("external", "")
        low = title.lower()
        marker = next((m for m in _EDITION_MARKERS if m in low), None)
        if marker is None:
            continue
        # Strict: the candidate must be *our* title plus an edition suffix and
        # nothing else. Containment is not enough - "ELDEN RING NIGHTREIGN
        # Deluxe Edition" contains "Elden Ring" but is a different game, and
        # offering it as a cheaper edition would be wrong.
        if _norm(low.replace(marker, "")) != ours_key:
            continue
        try:
            price = float(row.get("cheapest"))
        except (TypeError, ValueError):
            continue
        if price < ours and (best is None or price < float(best["cheapest"])):
            best = row
    return best


def offers_for_title(title: str, limit: int = 6) -> tuple[list[Offer], list[str]]:
    """Live lookup: search by title, then fetch that game's deals.

    Returns (offers, notes). Raises on transport failure so the caller can tell
    an outage from a genuine absence - swallowing that made a CheapShark outage
    look identical to a game having no deals.
    """
    if not title.strip():
        return [], []
    with _client() as client:
        rows = client.get(f"{BASE}/games", params={"title": title, "limit": 12}).json()
        if not isinstance(rows, list):
            return [], []
        match = pick_game(rows, title)
        if not match or not match.get("gameID"):
            return [], []
        payload = client.get(f"{BASE}/games", params={"id": match["gameID"]}).json()
        offers = normalize_deals(payload, stores(client), limit=limit)

        notes: list[str] = []
        alt = cheaper_edition(rows, match)
        if alt:
            notes.append(
                f"{alt['external']} is cheaper at ${float(alt['cheapest']):.2f}"
            )
        return offers, notes

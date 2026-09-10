"""IsThereAnyDeal: game prices, per country.

CheapShark ignores every region parameter it is given and only ever returns USD
from US storefronts, so it cannot answer "what does this cost where I live".
ITAD can, and it returns the historical low too, so it supersedes CheapShark
wherever a key is configured. CheapShark stays as the keyless fallback.

Shape of their v1/v3 API, since it is not obvious:

    GET  /games/search/v1?key=&title=          -> [{id: uuid, title, ...}]
    POST /games/prices/v3?key=&country=XX      body: [uuid, ...]
                                               -> [{id, deals: [...], historyLow}]

A deal carries price{amount,currency}, regular{...}, shop{name}, url and cut.

One trap worth recording: /service/shops/v1 returns 200 for *any* key, valid or
not, so it cannot be used to check credentials. The game endpoints return
403 "Invalid or expired api key", and those are the ones that matter.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import settings
from ..models import Offer
from ..titles import is_edition_of, pick_exact

BASE = "https://api.isthereanydeal.com"
# Both game price sources cover PC storefronts only. ITAD's US shop list is 34
# entries of Steam, GOG, Epic, Humble and friends - no PSN, Xbox Store or
# Nintendo eShop - and CheapShark is the same. Console prices are simply not
# available from any free source, so the panel says which platform these are
# for rather than letting a console player assume they apply.
PLATFORM_NOTE = "PC storefront prices; consoles not covered."


def _search(client: httpx.Client, title: str, results: int = 12) -> list[dict[str, Any]]:
    r = client.get(f"{BASE}/games/search/v1",
                   params={"key": settings.itad_api_key, "title": title, "results": results})
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, list) else []


def _prices(client: httpx.Client, ids: list[str], country: str) -> dict[str, dict[str, Any]]:
    """game id -> its price entry, for several games in one request."""
    if not ids:
        return {}
    r = client.post(f"{BASE}/games/prices/v3",
                    params={"key": settings.itad_api_key, "country": country.upper()},
                    json=ids)
    r.raise_for_status()
    payload = r.json()
    return {e["id"]: e for e in payload if isinstance(e, dict) and e.get("id")}


def normalize_deals(entry: dict[str, Any], limit: int = 6) -> list[Offer]:
    """One /games/prices/v3 entry -> Offers, cheapest first. Pure."""
    deals = entry.get("deals") or []
    low = ((entry.get("historyLow") or {}).get("all") or {}).get("amount")
    try:
        low = float(low) if low is not None else None
    except (TypeError, ValueError):
        low = None

    offers: list[Offer] = []
    for deal in deals:
        price = (deal.get("price") or {}).get("amount")
        currency = (deal.get("price") or {}).get("currency") or "USD"
        regular = (deal.get("regular") or {}).get("amount")
        if price is None:
            continue
        try:
            price = float(price)
            regular = float(regular) if regular is not None else None
        except (TypeError, ValueError):
            continue
        note = ""
        if low is not None and abs(price - low) < 0.01:
            note = "historical low"
        elif low is not None and price > low:
            note = f"low was {low:.2f}"
        offers.append(Offer(
            kind="free" if price == 0 else "buy",
            store=(deal.get("shop") or {}).get("name") or "unknown shop",
            url=deal.get("url") or "",
            price=price,
            currency=currency,
            was=regular if regular and regular > price else None,
            note=note,
        ))
    offers.sort(key=lambda o: o.price if o.price is not None else 1e9)
    return offers[:limit]


def offers_for_title(
    title: str, country: str = "US", limit: int = 6
) -> tuple[list[Offer], list[str]]:
    """Regional prices for one game. Returns (offers, notes).

    Raises on transport failure so the caller can tell an outage from an
    absence - the same contract as the CheapShark source.
    """
    if not settings.itad_api_key or not title.strip():
        return [], []
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        rows = _search(client, title)
        match = pick_exact(rows, title, lambda r: r.get("title", ""))
        if not match or not match.get("id"):
            return [], []

        # Price the match and any genuine cheaper edition in one request - the
        # endpoint takes a list, so the edition check costs nothing extra.
        editions = [r for r in rows
                    if r.get("id") and r["id"] != match["id"]
                    and is_edition_of(r.get("title", ""), match.get("title", ""))]
        priced = _prices(client, [match["id"], *(e["id"] for e in editions)], country)

        entry = priced.get(match["id"])
        if entry is None:
            return [], []
        offers = normalize_deals(entry, limit=limit)

        notes: list[str] = []
        ours = offers[0].price if offers else None
        best_alt, best_price = None, None
        for ed in editions:
            alt = normalize_deals(priced.get(ed["id"]) or {}, limit=1)
            if not alt:
                continue
            if ours is not None and alt[0].price < ours and (
                best_price is None or alt[0].price < best_price
            ):
                best_alt, best_price = ed, alt[0].price
        if best_alt is not None:
            cur = offers[0].currency if offers else ""
            notes.append(f"{best_alt['title']} is cheaper at {best_price:.2f} {cur}".strip())
        return offers, notes

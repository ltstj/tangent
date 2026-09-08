"""Pricing the subscription half of "where to get it".

TMDB says which services carry a title; it publishes no prices, so the prices
come from our own `subscription_prices` table (see the migration for why it is
shaped the way it is).

The rule this module exists to enforce: **an undated or stale price is not a
price.** Subscription costs change once or twice a year, and a number that was
right last spring is simply wrong today. So a row is only used if it has both a
price and a `checked_on` within STALE_AFTER_DAYS; otherwise the offer goes out
unpriced exactly as it does with no table at all. Going stale then shows up as a
missing price rather than a confident wrong one.
"""
from __future__ import annotations

import datetime as _dt

from .models import Offer
from .sources.tmdb import store_key

# Two subscription price changes a year is typical, so a price unverified for
# four months is past the point of being trustworthy.
STALE_AFTER_DAYS = 120


def _fresh(checked_on, today: _dt.date) -> bool:
    if checked_on is None:
        return False
    if isinstance(checked_on, _dt.datetime):
        checked_on = checked_on.date()
    return (today - checked_on).days <= STALE_AFTER_DAYS


def usable_prices(rows: list[dict], today: _dt.date | None = None) -> dict[str, dict]:
    """service_key -> row, for rows we are willing to quote. Pure."""
    today = today or _dt.date.today()
    return {
        r["service_key"]: r
        for r in rows
        if r.get("price") is not None and _fresh(r.get("checked_on"), today)
    }


def annotate(offers: list[Offer], rows: list[dict], today: _dt.date | None = None) -> list[Offer]:
    """Attach prices to subscription offers where we have a fresh one. In place.

    Unpriced services get a pointer to their own pricing page rather than a
    guess, so the gap is visible and actionable.
    """
    usable = usable_prices(rows, today)
    by_key = {r["service_key"]: r for r in rows}
    for offer in offers:
        if offer.kind != "subscription":
            continue
        key = store_key(offer.store)
        row = usable.get(key)
        if row:
            offer.price = float(row["price"])
            offer.currency = row.get("currency") or "USD"
            checked = row.get("checked_on")
            offer.note = f"per {row.get('period') or 'month'}, checked {checked}"
        elif key in by_key:
            offer.note = "subscription price not verified"
        else:
            offer.note = "subscription price not tracked"
    return offers


def cheapest(offers: list[Offer]) -> Offer | None:
    """The cheapest subscription that actually carries the title, if we can price
    one. `None` means "we don't know", never "there isn't one"."""
    priced = [o for o in offers if o.kind == "subscription" and o.price is not None]
    return min(priced, key=lambda o: o.price) if priced else None

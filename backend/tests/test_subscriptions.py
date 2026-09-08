"""Subscription pricing is pure and tested offline. The staleness rule is the
point of this module, so most of these tests are about refusing to quote."""
from __future__ import annotations

import datetime as _dt

from app.models import Offer
from app.subscriptions import STALE_AFTER_DAYS, annotate, cheapest, usable_prices

TODAY = _dt.date(2026, 9, 8)


def _row(key, price, days_ago=None, name=None):
    return {
        "service_key": key, "display_name": name or key, "price": price,
        "currency": "USD", "period": "month",
        "checked_on": None if days_ago is None else TODAY - _dt.timedelta(days=days_ago),
        "source_url": f"https://example.com/{key}", "note": "",
    }


def test_a_fresh_price_is_quoted():
    rows = [_row("netflix", 15.49, days_ago=10)]
    assert list(usable_prices(rows, TODAY)) == ["netflix"]


def test_an_undated_price_is_not_a_price():
    """A number with no date is unverifiable, so it must not be served."""
    assert usable_prices([_row("netflix", 15.49, days_ago=None)], TODAY) == {}


def test_a_stale_price_is_not_served():
    assert usable_prices([_row("netflix", 15.49, days_ago=STALE_AFTER_DAYS + 1)], TODAY) == {}


def test_the_staleness_boundary_is_inclusive():
    assert list(usable_prices([_row("n", 1.0, days_ago=STALE_AFTER_DAYS)], TODAY)) == ["n"]


def test_a_missing_price_with_a_date_is_still_unusable():
    assert usable_prices([_row("netflix", None, days_ago=1)], TODAY) == {}


def test_annotate_prices_subscriptions_and_leaves_other_kinds_alone():
    offers = [
        Offer(kind="subscription", store="Netflix", url="u"),
        Offer(kind="buy", store="Amazon Video", url="u", note="price not published by TMDB"),
    ]
    annotate(offers, [_row("netflix", 15.49, days_ago=5, name="Netflix")], TODAY)
    assert offers[0].price == 15.49 and "checked 2026-09-03" in offers[0].note
    assert offers[1].price is None and offers[1].note == "price not published by TMDB"


def test_annotate_distinguishes_untracked_from_unverified():
    """These are different problems: one needs a row, the other needs a human."""
    offers = [Offer(kind="subscription", store="Netflix", url="u"),
              Offer(kind="subscription", store="Obscure TV", url="u")]
    annotate(offers, [_row("netflix", None, days_ago=None, name="Netflix")], TODAY)
    assert offers[0].note == "subscription price not verified"
    assert offers[1].note == "subscription price not tracked"


def test_annotate_matches_reseller_names_to_the_service():
    """TMDB may hand us "HBO Max Amazon Channel"; the price lives under "hbo max"."""
    offers = [Offer(kind="subscription", store="HBO Max Amazon Channel", url="u")]
    annotate(offers, [_row("hbo max", 16.99, days_ago=3, name="HBO Max")], TODAY)
    assert offers[0].price == 16.99


def test_cheapest_picks_the_lowest_priced_subscription():
    offers = [Offer(kind="subscription", store="A", url="u", price=17.99),
              Offer(kind="subscription", store="B", url="u", price=9.99),
              Offer(kind="buy", store="C", url="u", price=3.99)]
    best = cheapest(offers)
    assert best is not None and best.store == "B"


def test_cheapest_is_none_when_nothing_can_be_priced():
    """None must read as "we don't know", never as "it isn't streaming"."""
    assert cheapest([Offer(kind="subscription", store="A", url="u")]) is None
    assert cheapest([]) is None

"""IsThereAnyDeal normalization and the game-price fallback chain. All offline."""
from __future__ import annotations

import app.availability as av
from app.models import CatalogItem, Offer
from app.sources import itad
from app.titles import is_edition_of, pick_exact

GAME = CatalogItem(id="game:t:1", medium="game", title="Elden Ring")


def _deal(shop, amount, currency="GBP", regular=None, url="u"):
    d = {"shop": {"name": shop}, "price": {"amount": amount, "currency": currency}, "url": url}
    if regular is not None:
        d["regular"] = {"amount": regular, "currency": currency}
    return d


def test_deals_are_cheapest_first_and_keep_their_currency():
    entry = {"deals": [_deal("WinGameStore", 42.81), _deal("PlayerLand", 40.96)],
             "historyLow": {"all": {"amount": 24.79}}}
    offers = itad.normalize_deals(entry)
    assert [o.price for o in offers] == [40.96, 42.81]
    # A hardcoded dollar sign would mislabel these; the currency travels.
    assert all(o.currency == "GBP" for o in offers)


def test_historical_low_is_flagged_only_when_the_deal_matches_it():
    entry = {"deals": [_deal("A", 24.79), _deal("B", 40.96)],
             "historyLow": {"all": {"amount": 24.79}}}
    offers = itad.normalize_deals(entry)
    assert offers[0].note == "historical low"
    assert offers[1].note == "low was 24.79"


def test_was_is_only_set_on_a_real_discount():
    entry = {"deals": [_deal("A", 40.0, regular=59.99), _deal("B", 59.99, regular=59.99)],
             "historyLow": {}}
    offers = itad.normalize_deals(entry)
    assert offers[0].was == 59.99 and offers[1].was is None


def test_malformed_and_priceless_rows_are_skipped():
    entry = {"deals": [{"shop": {"name": "X"}}, _deal("Y", None), _deal("Z", 5.0)],
             "historyLow": {}}
    assert [o.price for o in itad.normalize_deals(entry)] == [5.0]


def test_zero_price_is_free_not_buy():
    entry = {"deals": [_deal("Epic", 0)], "historyLow": {}}
    assert itad.normalize_deals(entry)[0].kind == "free"


# --- the fallback chain -------------------------------------------------------

def test_no_itad_key_falls_back_to_cheapshark(monkeypatch):
    monkeypatch.setattr(av.settings, "itad_api_key", "")
    monkeypatch.setattr(av.cheapshark, "offers_for_title",
                        lambda *a, **k: ([Offer(kind="buy", store="Steam", url="u", price=9.99)], []))
    result = av.availability_for(GAME, region="GB")
    assert result.price_region == "US"            # honest about what it served
    assert any("USD" in n for n in result.notes)


def test_itad_is_used_when_a_key_is_present(monkeypatch):
    monkeypatch.setattr(av.settings, "itad_api_key", "x")
    monkeypatch.setattr(av.itad, "offers_for_title",
                        lambda *a, **k: ([Offer(kind="buy", store="PlayerLand", url="u",
                                                price=40.96, currency="GBP")], []))
    result = av.availability_for(GAME, region="GB")
    assert result.price_region == "GB" and result.offers[0].currency == "GBP"
    assert not any("USD" in n for n in result.notes)


def test_an_itad_outage_degrades_to_us_prices_and_says_so(monkeypatch):
    """Silently switching currency would be worse than an explicit downgrade."""
    monkeypatch.setattr(av.settings, "itad_api_key", "x")

    def boom(*a, **k):
        raise ConnectionError("rate limited")

    monkeypatch.setattr(av.itad, "offers_for_title", boom)
    monkeypatch.setattr(av.cheapshark, "offers_for_title",
                        lambda *a, **k: ([Offer(kind="buy", store="Steam", url="u", price=9.99)], []))
    result = av.availability_for(GAME, region="GB")
    assert result.price_region == "US"
    assert any("Regional pricing unavailable" in n for n in result.notes)
    assert result.status == "ok"                  # degraded, but still useful


def test_no_regional_deals_still_tries_cheapshark(monkeypatch):
    monkeypatch.setattr(av.settings, "itad_api_key", "x")
    monkeypatch.setattr(av.itad, "offers_for_title", lambda *a, **k: ([], []))
    monkeypatch.setattr(av.cheapshark, "offers_for_title",
                        lambda *a, **k: ([Offer(kind="buy", store="Steam", url="u", price=9.99)], []))
    result = av.availability_for(GAME, region="JP")
    assert result.offers and any("No JP deals listed" in n for n in result.notes)


# --- shared title matching ----------------------------------------------------

def test_is_edition_of_accepts_editions_and_rejects_dlc_and_siblings():
    base = "Elden Ring"
    assert is_edition_of("Elden Ring Deluxe Edition", base)
    assert is_edition_of("ELDEN RING GOTY", base)
    # DLC requires the base game, so it is not a cheaper way to buy it.
    assert not is_edition_of("Elden Ring Shadow of the Erdtree", base)
    # A different game whose title merely contains ours.
    assert not is_edition_of("ELDEN RING NIGHTREIGN Deluxe Edition", base)


def test_pick_exact_prefers_exact_then_shortest_containing():
    rows = [{"t": "Elden Ring Deluxe"}, {"t": "Elden Ring"}, {"t": "Elden Ring Bundle Pack"}]
    assert pick_exact(rows, "Elden Ring", lambda r: r["t"])["t"] == "Elden Ring"
    rows2 = [{"t": "Portal 2 Bundle Extra Long"}, {"t": "Portal 2 Deluxe"}]
    assert pick_exact(rows2, "Portal 2", lambda r: r["t"])["t"] == "Portal 2 Deluxe"
    assert pick_exact([], "Anything", lambda r: r["t"]) is None

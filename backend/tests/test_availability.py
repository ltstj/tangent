"""Offer normalization is pure and unit-tested with fixture payloads (no network)."""
from __future__ import annotations

from app.availability import offers_for
from app.models import CatalogItem
from app.sources import cheapshark

STORES = {"1": "Steam", "23": "GameBillet", "15": "Fanatical"}


def _deal(store, price, retail, deal_id="abc"):
    return {"storeID": store, "price": str(price), "retailPrice": str(retail),
            "savings": "0", "dealID": deal_id}


def test_pick_game_prefers_the_base_game_over_its_editions():
    # A title search returns editions and sequels; matching the wrong one would
    # quote the deluxe edition's price for the base game.
    rows = [
        {"external": "ELDEN RING NIGHTREIGN", "gameID": "3"},
        {"external": "ELDEN RING Deluxe Edition", "gameID": "2"},
        {"external": "ELDEN RING", "gameID": "1"},
    ]
    assert cheapshark.pick_game(rows, "Elden Ring")["gameID"] == "1"


def test_pick_game_falls_back_to_shortest_containing_title():
    rows = [{"external": "Portal 2 Soundtrack Bundle", "gameID": "9"},
            {"external": "Portal 2 - Deluxe", "gameID": "5"}]
    assert cheapshark.pick_game(rows, "Portal 2")["gameID"] == "5"


def test_pick_game_returns_none_when_nothing_matches():
    assert cheapshark.pick_game([], "Anything") is None
    assert cheapshark.pick_game([{"external": "Doom", "gameID": "1"}], "Tetris") is None


def test_normalize_deals_sorts_cheapest_first_and_flags_the_historical_low():
    payload = {
        "cheapestPriceEver": {"price": "9.99"},
        "deals": [_deal("15", 19.99, 29.99), _deal("23", 9.99, 29.99), _deal("1", 29.99, 29.99)],
    }
    offers = cheapshark.normalize_deals(payload, STORES)
    assert [o.price for o in offers] == [9.99, 19.99, 29.99]
    assert offers[0].store == "GameBillet" and offers[0].note == "historical low"
    assert offers[1].note == "low was $9.99"
    # `was` is only set when it really is a discount, so no fake "was" prices.
    assert offers[0].was == 29.99 and offers[2].was is None
    assert offers[0].savings_pct == 67 and offers[2].savings_pct is None


def test_normalize_deals_survives_a_malformed_row():
    payload = {"deals": [{"storeID": "1"}, _deal("23", 5.0, 10.0)], "cheapestPriceEver": {}}
    offers = cheapshark.normalize_deals(payload, STORES)
    assert [o.price for o in offers] == [5.0]


def test_free_games_are_marked_free_not_buy():
    payload = {"deals": [_deal("1", 0.0, 19.99)], "cheapestPriceEver": {"price": "0"}}
    assert cheapshark.normalize_deals(payload, STORES)[0].kind == "free"


def test_unknown_store_id_degrades_to_a_label_not_a_crash():
    payload = {"deals": [_deal("999", 5.0, 10.0)], "cheapestPriceEver": {}}
    assert cheapshark.normalize_deals(payload, STORES)[0].store == "store 999"


def test_books_get_honest_links_and_never_a_price():
    """No free API gives current retail book prices, so we point instead of guess."""
    book = CatalogItem(id="book:t:1", medium="book", title="Piranesi & Co")
    offers = offers_for(book)
    assert offers and all(o.kind == "link" and o.price is None for o in offers)
    assert any("worldcat" in o.url for o in offers)          # check your library
    assert all("Piranesi+%26+Co" in o.url for o in offers)   # title is URL-encoded


def test_movies_return_nothing_rather_than_guessing():
    movie = CatalogItem(id="movie:t:1", medium="movie", title="Whatever")
    assert offers_for(movie) == []

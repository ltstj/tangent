"""Offer normalization is pure and unit-tested with fixture payloads (no network)."""
from __future__ import annotations

from app.availability import offers_for
from app.models import CatalogItem
from app.sources import cheapshark, tmdb

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


def test_a_movie_without_a_tmdb_id_returns_nothing_rather_than_guessing():
    movie = CatalogItem(id="movie:t:1", medium="movie", title="Whatever")
    assert offers_for(movie) == []


PROVIDERS = {
    "results": {
        "US": {
            "link": "https://www.themoviedb.org/movie/1/watch?locale=US",
            "flatrate": [{"provider_name": "Paramount Plus", "display_priority": 2},
                         {"provider_name": "fuboTV", "display_priority": 1},
                         {"provider_name": "Paramount Plus", "display_priority": 9}],
            "rent": [{"provider_name": "Amazon Video", "display_priority": 1}],
            "buy": [{"provider_name": "Apple TV Store", "display_priority": 3}],
            "ads": [{"provider_name": "Tubi", "display_priority": 4}],
        },
        "GB": {"link": "x", "flatrate": [{"provider_name": "Now TV", "display_priority": 1}]},
    }
}


def test_providers_order_subscription_first_then_free_then_rent_then_buy():
    offers = tmdb.normalize_providers(PROVIDERS, region="US")
    # Two distinct subscriptions in the fixture, then one of each other kind.
    assert [o.kind for o in offers] == [
        "subscription", "subscription", "free", "rent", "buy",
    ]
    # Within a bucket TMDB's own display_priority decides.
    assert offers[0].store == "fuboTV"


def test_providers_never_carry_a_price_because_tmdb_publishes_none():
    """Verified against the live API: provider objects have no price field at
    all, so rent/buy say where, not how much."""
    offers = tmdb.normalize_providers(PROVIDERS, region="US")
    assert all(o.price is None for o in offers)
    rent = next(o for o in offers if o.kind == "rent")
    assert "not published" in rent.note


def test_duplicate_channel_variants_collapse():
    offers = tmdb.normalize_providers(PROVIDERS, region="US")
    subs = [o.store for o in offers if o.kind == "subscription"]
    assert subs.count("Paramount Plus") == 1


def test_ads_supported_counts_as_free_but_says_so():
    free = next(o for o in tmdb.normalize_providers(PROVIDERS, region="US") if o.kind == "free")
    assert free.store == "Tubi" and free.note == "with ads"


def test_region_selects_the_right_listing_and_missing_region_is_empty():
    assert [o.store for o in tmdb.normalize_providers(PROVIDERS, region="GB")] == ["Now TV"]
    assert tmdb.normalize_providers(PROVIDERS, region="JP") == []


def test_reseller_channels_and_ad_tiers_collapse_to_one_row_per_service():
    """TMDB's real payload for Reacher lists Amazon three times and, for Game of
    Thrones, HBO Max twice. All are the same answer to "where can I watch this"."""
    payload = {"results": {"US": {
        "link": "x",
        "flatrate": [
            {"provider_name": "Amazon Prime Video", "display_priority": 1},
            {"provider_name": "Amazon Prime Video with Ads", "display_priority": 2},
            {"provider_name": "HBO Max", "display_priority": 3},
            {"provider_name": "HBO Max Amazon Channel", "display_priority": 4},
            {"provider_name": "Paramount+ Roku Premium Channel", "display_priority": 5},
            {"provider_name": "Paramount Plus", "display_priority": 6},
        ],
        "ads": [{"provider_name": "Amazon Prime Video Free with Ads", "display_priority": 7}],
    }}}
    offers = tmdb.normalize_providers(payload, region="US", limit=20)
    subs = [o.store for o in offers if o.kind == "subscription"]
    # Note Paramount: TMDB ranked the Roku reseller above the service itself, and
    # the plainer name still wins.
    assert subs == ["Amazon Prime Video", "HBO Max", "Paramount Plus"]
    # The ad-supported tier is a different kind, so it survives separately.
    free = [o for o in offers if o.kind == "free"]
    assert len(free) == 1 and free[0].note == "with ads"


def test_genuinely_different_price_tiers_are_not_collapsed():
    """Paramount Plus Premium and Essential cost different amounts; merging them
    would hide a real choice."""
    payload = {"results": {"US": {"link": "x", "flatrate": [
        {"provider_name": "Paramount Plus Premium", "display_priority": 1},
        {"provider_name": "Paramount Plus Essential", "display_priority": 2},
    ]}}}
    offers = tmdb.normalize_providers(payload, region="US")
    assert len(offers) == 2

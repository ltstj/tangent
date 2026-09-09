"""Offer normalization is pure and unit-tested with fixture payloads (no network)."""
from __future__ import annotations

from app.availability import availability_for, offers_for
from app.models import CatalogItem, Offer
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


# --- Google Books ebook prices -------------------------------------------------

def _volume(title, price, saleability="FOR_SALE", listed=None):
    sale = {"saleability": saleability, "buyLink": "https://play.google.com/x"}
    if price is not None:
        sale["retailPrice"] = {"amount": price, "currencyCode": "USD"}
    if listed is not None:
        sale["listPrice"] = {"amount": listed, "currencyCode": "USD"}
    return {"volumeInfo": {"title": title}, "saleInfo": sale}


def test_ebook_pick_requires_an_exact_title_and_a_real_sale():
    """A book search returns study guides and summaries; quoting one of those as
    the book's price would be wrong."""
    from app.sources import googlebooks

    items = [
        _volume("Neuromancer: A Study Guide", 4.99),
        _volume("Neuromancer", None),                          # for sale, no price
        _volume("Neuromancer", 9.99, saleability="NOT_FOR_SALE"),
        _volume("Neuromancer", 8.99, listed=12.99),            # the one we want
    ]
    picked = googlebooks.pick_volume(items, "Neuromancer")
    offer = googlebooks.normalize_volume(picked)
    assert offer.price == 8.99 and offer.was == 12.99
    assert offer.kind == "buy" and offer.note == "ebook"
    assert offer.store == "Google Play Books"


def test_ebook_pick_returns_none_when_nothing_qualifies():
    from app.sources import googlebooks

    assert googlebooks.pick_volume([], "Anything") is None
    assert googlebooks.pick_volume([_volume("Other Book", 5.0)], "Neuromancer") is None


def test_ebook_offer_is_skipped_without_a_key(monkeypatch):
    """No key means no price, rather than a half-working keyless request that
    shares an exhausted global quota."""
    from app.config import settings
    from app.sources import googlebooks

    monkeypatch.setattr(settings, "google_books_api_key", "")
    assert googlebooks.ebook_offer("Neuromancer") is None


def test_book_availability_says_how_to_enable_prices(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "google_books_api_key", "")
    book = CatalogItem(id="book:t:9", medium="book", title="Some Unique Title Here")
    result = availability_for(book, region="US")
    assert result.status == "ok"
    assert all(o.price is None for o in result.offers)
    assert any("GOOGLE_BOOKS_API_KEY" in n for n in result.notes)


# --- status: "we could not ask" is not "there is nothing" ----------------------

def test_a_source_outage_is_reported_not_disguised_as_no_deals(monkeypatch):
    """The defect this replaced: `except Exception: return []` made a CheapShark
    outage produce the same output as a game genuinely having no deals, and the
    UI then told the reader "no prices available" - a claim we hadn't earned."""
    import app.availability as av

    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(av.cheapshark, "offers_for_title", boom)
    av._cache.clear()
    game = CatalogItem(id="game:t:out", medium="game", title="Some Game")
    result = av.availability_for(game)
    assert result.status == "source_unavailable"
    assert result.offers == [] and "CheapShark" in result.detail


def test_genuinely_empty_results_say_none_listed(monkeypatch):
    import app.availability as av

    monkeypatch.setattr(av.cheapshark, "offers_for_title", lambda *a, **k: ([], []))
    av._cache.clear()
    game = CatalogItem(id="game:t:empty", medium="game", title="Obscure Game")
    result = av.availability_for(game)
    assert result.status == "none_listed" and result.offers == []


def test_failures_are_not_cached(monkeypatch):
    """A transient outage must not pin "unavailable" for the whole TTL."""
    import app.availability as av

    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("down")
        return ([Offer(kind="buy", store="Steam", url="u", price=1.0)], [])

    monkeypatch.setattr(av.cheapshark, "offers_for_title", flaky)
    av._cache.clear()
    game = CatalogItem(id="game:t:flaky", medium="game", title="Flaky Game")
    assert av.availability_for(game).status == "source_unavailable"
    assert av.availability_for(game).status == "ok"        # retried, not cached
    assert av.availability_for(game).status == "ok"        # now cached
    assert calls["n"] == 2


def test_game_prices_are_labelled_us_when_another_region_is_asked_for(monkeypatch):
    """CheapShark ignores every region parameter, so presenting its prices as
    local would be a lie. Verified against the live API: country, region,
    currency and cc all return identical USD prices."""
    import app.availability as av

    monkeypatch.setattr(av.cheapshark, "offers_for_title",
                        lambda *a, **k: ([Offer(kind="buy", store="Steam", url="u", price=9.99)], []))
    av._cache.clear()
    game = CatalogItem(id="game:t:reg", medium="game", title="Region Game")
    gb = av.availability_for(game, region="GB")
    assert gb.price_region == "US"
    assert any("USD" in n for n in gb.notes)
    av._cache.clear()
    us = av.availability_for(game, region="US")
    assert not any("USD" in n for n in us.notes)   # no needless note at home


def test_a_movie_without_a_tmdb_id_is_not_supported_not_empty():
    import app.availability as av
    av._cache.clear()
    movie = CatalogItem(id="movie:t:noid", medium="movie", title="Whatever")
    result = av.availability_for(movie)
    assert result.status == "not_supported" and "TMDB id" in result.detail

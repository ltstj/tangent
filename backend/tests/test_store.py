from __future__ import annotations


def test_seeded_and_counts(store):
    assert store.count() > 10


def test_search_matches_title_and_medium(store):
    hits = store.search("witcher")
    assert any(h.id == "game:seed:witcher3" for h in hits)
    # medium filter
    movies = store.search("the", medium="movie")
    assert movies and all(m.medium == "movie" for m in movies)


def test_get_roundtrip_and_missing(store):
    it = store.get("movie:seed:heat")
    assert it and it.title == "Heat" and "crime" in it.genres
    assert store.get("nope:0") is None


def test_upsert_updates_not_duplicates(store):
    before = store.count()
    item = store.get("movie:seed:heat")
    item.rating = 9.9
    store.upsert_items([item])
    assert store.count() == before               # no duplicate row
    assert store.get("movie:seed:heat").rating == 9.9

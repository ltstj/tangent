"""Source normalization is pure and unit-tested with fixture payloads (no network)."""
from __future__ import annotations

from app.sources import igdb, openlibrary, tmdb


def test_tmdb_normalize_movie():
    raw = {"id": 603, "title": "The Matrix", "release_date": "1999-03-30",
           "genre_ids": [28, 878], "vote_average": 8.2, "popularity": 84.0,
           "overview": "A hacker learns the truth."}
    gmap = {28: "Action", 878: "Science Fiction"}
    item = tmdb.normalize(raw, "movie", gmap)
    assert item.id == "movie:tmdb:603" and item.medium == "movie" and item.year == 1999
    assert "action" in item.genres and "scifi" in item.genres
    assert item.rating == 8.2


def test_igdb_normalize_game():
    raw = {"id": 1020, "name": "GTA V", "summary": "Crime saga.",
           "genres": [{"name": "Shooter"}, {"name": "Adventure"}],
           "themes": [{"name": "Open world"}],
           "total_rating": 91.0, "total_rating_count": 3000,
           "first_release_date": 1379548800}  # 2013
    item = igdb.normalize(raw)
    assert item.id == "game:igdb:1020" and item.medium == "game"
    assert item.year == 2013
    assert "shooter" in item.genres and "adventure" in item.genres
    assert "openworld" in item.tags
    assert item.rating == 9.1


def test_openlibrary_normalize_book():
    doc = {"key": "/works/OL12345W", "title": "Dune", "first_publish_year": 1965,
           "subject": ["Science Fiction", "Politics", "Desert"], "ratings_average": 4.3}
    item = openlibrary.normalize_doc(doc)
    assert item.id == "book:openlibrary:OL12345W" and item.medium == "book"
    assert "scifi" in item.genres
    assert item.rating == 8.6                       # 4.3 * 2

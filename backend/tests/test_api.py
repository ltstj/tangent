from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import SqliteCatalogStore


@pytest.fixture
def client():
    # Point the app at a fresh in-memory catalog; the lifespan handler seeds it
    # (lifespan only runs when TestClient is used as a context manager).
    main.store = SqliteCatalogStore(":memory:")
    main.refresh_model()
    with TestClient(main.app) as c:
        yield c


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    ready = client.get("/ready").json()
    assert ready["catalog_items"] > 10


def test_search_endpoint(client):
    r = client.get("/api/search", params={"q": "witcher"})
    assert r.status_code == 200
    assert any(i["id"] == "game:seed:witcher3" for i in r.json())


def test_recommend_cross_media(client):
    r = client.post("/api/recommend", json={
        "favorite_ids": ["movie:seed:bladerunner2049"],
        "target_media": ["game"],
        "limit": 5,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert body["results"][0]["item"]["id"] == "game:seed:cyberpunk2077"
    assert all(res["item"]["medium"] == "game" for res in body["results"])


def test_search_augments_from_live_sources(client, monkeypatch):
    from app.models import CatalogItem
    fake = CatalogItem(id="tv:tmdb:99999", medium="tv", title="Severance", year=2022,
                       genres=["scifi", "thriller"], source="tmdb", source_id="99999")
    monkeypatch.setattr(main, "_live_search", lambda q, medium, limit: [fake])
    r = client.get("/api/search", params={"q": "severance"})
    assert r.status_code == 200
    assert any(i["id"] == "tv:tmdb:99999" for i in r.json())
    # the live hit was added to the catalog, so it's now recommendable
    assert client.get("/api/item/tv:tmdb:99999").json()["title"] == "Severance"


def test_recommend_rejects_unknown_ids(client):
    r = client.post("/api/recommend", json={"favorite_ids": ["nope:0"]})
    assert r.status_code == 400


def test_item_lookup_and_404(client):
    assert client.get("/api/item/movie:seed:heat").json()["title"] == "Heat"
    assert client.get("/api/item/nope:0").status_code == 404


def test_genres_endpoint_reports_only_present_genres(client):
    rows = client.get("/api/genres").json()
    assert rows and all(r["count"] > 0 for r in rows)
    assert rows == sorted(rows, key=lambda r: (-r["count"], r["genre"]))
    # Driven by the catalog, so nothing is offered that returns nothing.
    recs = client.post("/api/recommend", json={"seed_genres": [rows[0]["genre"]], "limit": 3})
    assert recs.status_code == 200 and recs.json()["results"]


def test_recommend_requires_a_favorite_or_a_genre(client):
    assert client.post("/api/recommend", json={}).status_code == 400
    assert client.post("/api/recommend", json={"favorite_ids": ["nope:0"]}).status_code == 400


def test_recommend_accepts_genre_controls(client):
    r = client.post("/api/recommend", json={
        "favorite_ids": ["movie:seed:bladerunner2049"],
        "filter_genres": ["rpg"], "genre_weight": 0.8, "limit": 5,
    })
    assert r.status_code == 200
    assert all("rpg" in x["item"]["genres"] for x in r.json()["results"])


def test_offers_endpoint_for_a_book_is_links_only(client):
    """Uses a book on purpose: no network, and it pins the "never invent a
    price" contract."""
    r = client.get("/api/offers/book:seed:neuromancer")
    assert r.status_code == 200
    body = r.json()
    assert body["priced"] is False
    assert body["offers"] and all(o["price"] is None for o in body["offers"])


def test_offers_endpoint_404s_on_an_unknown_item(client):
    assert client.get("/api/offers/nope:0").status_code == 404

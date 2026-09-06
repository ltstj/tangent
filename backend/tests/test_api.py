from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.store import CatalogStore


@pytest.fixture
def client():
    # Point the app at a fresh in-memory catalog; the lifespan handler seeds it
    # (lifespan only runs when TestClient is used as a context manager).
    main.store = CatalogStore(":memory:")
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


def test_recommend_rejects_unknown_ids(client):
    r = client.post("/api/recommend", json={"favorite_ids": ["nope:0"]})
    assert r.status_code == 400


def test_item_lookup_and_404(client):
    assert client.get("/api/item/movie:seed:heat").json()["title"] == "Heat"
    assert client.get("/api/item/nope:0").status_code == 404

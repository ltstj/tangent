"""Things that only matter once the app faces the internet."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main, ratelimit
from app.config import Settings, settings
from app.seed import SEED_ITEMS
from app.store import SqliteCatalogStore


@pytest.fixture(autouse=True)
def _clear_limiter():
    ratelimit._hits.clear()
    yield
    ratelimit._hits.clear()


@pytest.fixture
def client(monkeypatch):
    main.store = SqliteCatalogStore(":memory:")
    main.store.upsert_items(SEED_ITEMS)
    main.refresh_model()
    # A tiny cap so the test does not need dozens of calls.
    monkeypatch.setattr(settings, "rate_limit_search_per_min", 3)
    monkeypatch.setattr(main, "_live_search", lambda q, medium, limit: [])
    with TestClient(main.app) as c:
        yield c


def test_search_is_capped_and_says_when_to_retry(client):
    """Search spends TMDB/IGDB/Open Library quota, which is ours to pay for."""
    for _ in range(3):
        assert client.get("/api/search", params={"q": "dune"}).status_code == 200
    blocked = client.get("/api/search", params={"q": "dune"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert int(blocked.headers["Retry-After"]) >= 1


def test_the_cap_is_per_client_not_global(client):
    for _ in range(3):
        client.get("/api/search", params={"q": "dune"})
    assert client.get("/api/search", params={"q": "dune"}).status_code == 429
    # A different client is unaffected.
    other = client.get("/api/search", params={"q": "dune"},
                       headers={"X-Forwarded-For": "203.0.113.7"})
    assert other.status_code == 200


def test_recommendations_are_not_capped(client):
    """They touch only our own database, so there is no third-party budget to
    protect and throttling them would just make the app feel broken."""
    for _ in range(8):
        r = client.post("/api/recommend",
                        json={"favorite_ids": ["tv:seed:got"], "limit": 2})
        assert r.status_code == 200


def test_a_zero_limit_disables_the_cap(monkeypatch, client):
    monkeypatch.setattr(settings, "rate_limit_search_per_min", 0)
    for _ in range(12):
        assert client.get("/api/search", params={"q": "dune"}).status_code == 200


# --- configuration ------------------------------------------------------------

def test_cors_defaults_to_local_dev_only():
    """The permissive "*" that used to be here lets any website issue
    credentialed requests as a signed-in visitor."""
    s = Settings()
    assert "*" not in s.allowed_origins
    assert all(o.startswith("http://localhost") or o.startswith("http://127.0.0.1")
               for o in s.allowed_origins)


def test_cors_origins_parse_from_a_comma_separated_list():
    s = Settings(cors_origins="https://tangent.app, https://www.tangent.app ")
    assert s.allowed_origins == ["https://tangent.app", "https://www.tangent.app"]


@pytest.mark.parametrize("env,expected", [
    ("dev", False), ("development", False), ("local", False), ("test", False),
    ("production", True), ("prod", True), ("staging", True),
])
def test_production_detection(env, expected):
    assert Settings(app_env=env).is_production is expected

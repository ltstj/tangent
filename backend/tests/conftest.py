from __future__ import annotations

import pytest

from app.recommend import TasteModel
from app.seed import SEED_ITEMS
from app.store import SqliteCatalogStore


@pytest.fixture(autouse=True)
def _no_external_keys(monkeypatch):
    """Blank every external API key for the duration of the suite.

    Tests are meant to be offline and deterministic, but any test exercising a
    code path that reads a key would quietly start making real network calls the
    moment a developer configured one - which is exactly what happened when
    GOOGLE_BOOKS_API_KEY was set: a book test that asserted "link-outs only"
    began fetching a live Play Books price and the suite runtime doubled.

    A test that wants a keyed path should set the key itself, explicitly.
    """
    from app.config import settings

    for field in ("google_books_api_key", "tmdb_api_key",
                  "igdb_client_id", "igdb_client_secret"):
        monkeypatch.setattr(settings, field, "")
    yield


@pytest.fixture(autouse=True)
def _isolate_availability_cache():
    """Clear the offers cache around every test.

    availability._cache is module-global and keyed by (item id, region, limit),
    so without this a test could be served a neighbour's cached result and the
    suite's outcome would depend on its order. One flaky failure was observed
    before this existed and never reproduced, which is the signature of exactly
    that; individual tests calling _cache.clear() themselves was not enough.
    """
    from app import availability

    availability._cache.clear()
    yield
    availability._cache.clear()


@pytest.fixture
def store() -> SqliteCatalogStore:
    s = SqliteCatalogStore(":memory:")
    s.upsert_items(SEED_ITEMS)
    return s


@pytest.fixture
def model() -> TasteModel:
    return TasteModel(SEED_ITEMS)

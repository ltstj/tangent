from __future__ import annotations

import pytest

from app.recommend import TasteModel
from app.seed import SEED_ITEMS
from app.store import SqliteCatalogStore


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

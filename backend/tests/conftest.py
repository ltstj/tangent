from __future__ import annotations

import pytest

from app.recommend import TasteModel
from app.seed import SEED_ITEMS
from app.store import SqliteCatalogStore


@pytest.fixture
def store() -> SqliteCatalogStore:
    s = SqliteCatalogStore(":memory:")
    s.upsert_items(SEED_ITEMS)
    return s


@pytest.fixture
def model() -> TasteModel:
    return TasteModel(SEED_ITEMS)

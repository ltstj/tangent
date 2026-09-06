from __future__ import annotations

import pytest

from app.recommend import TasteModel
from app.seed import SEED_ITEMS
from app.store import CatalogStore


@pytest.fixture
def store() -> CatalogStore:
    s = CatalogStore(":memory:")
    s.upsert_items(SEED_ITEMS)
    return s


@pytest.fixture
def model() -> TasteModel:
    return TasteModel(SEED_ITEMS)

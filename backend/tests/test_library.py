"""The per-user library. Auth is stubbed at the dependency, so these run offline.

The isolation test is the important one: the API connects as the table owner and
therefore bypasses RLS, so a missing user_id predicate would leak one person's
library to another and nothing in the database would stop it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import User, current_user
from app.store import SqliteCatalogStore
from app.seed import SEED_ITEMS

ALICE = User(id="11111111-1111-1111-1111-111111111111", email="alice@example.com")
BOB = User(id="22222222-2222-2222-2222-222222222222", email="bob@example.com")
ITEM = "movie:seed:bladerunner2049"
OTHER = "game:seed:witcher3"


def _client_as(user: User | None) -> TestClient:
    main.store = SqliteCatalogStore(":memory:")
    main.store.upsert_items(SEED_ITEMS)
    main.refresh_model()
    if user is None:
        main.app.dependency_overrides.pop(current_user, None)
    else:
        main.app.dependency_overrides[current_user] = lambda: user
    return TestClient(main.app)


@pytest.fixture
def alice():
    c = _client_as(ALICE)
    with c as client:
        yield client
    main.app.dependency_overrides.clear()


def test_library_starts_empty(alice):
    assert alice.get("/api/library").json() == []


def test_mark_and_read_back(alice):
    r = alice.put(f"/api/library/{ITEM}", json={"status": "finished", "rating": 9.0})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "finished" and body["rating"] == 9.0
    assert body["item"]["id"] == ITEM            # the catalog item comes with it
    assert [e["item"]["id"] for e in alice.get("/api/library").json()] == [ITEM]


def test_marking_twice_updates_rather_than_duplicating(alice):
    alice.put(f"/api/library/{ITEM}", json={"status": "want"})
    alice.put(f"/api/library/{ITEM}", json={"status": "finished", "rating": 7.5})
    entries = alice.get("/api/library").json()
    assert len(entries) == 1
    assert entries[0]["status"] == "finished" and entries[0]["rating"] == 7.5


def test_removing_an_entry(alice):
    alice.put(f"/api/library/{ITEM}", json={"status": "want"})
    assert alice.delete(f"/api/library/{ITEM}").json() == {"removed": True}
    assert alice.get("/api/library").json() == []
    # Removing something absent is not an error, just nothing removed.
    assert alice.delete(f"/api/library/{ITEM}").json() == {"removed": False}


def test_unknown_item_is_rejected(alice):
    assert alice.put("/api/library/nope:0", json={"status": "want"}).status_code == 404


def test_rating_must_be_in_range(alice):
    assert alice.put(f"/api/library/{ITEM}", json={"status": "finished",
                                                   "rating": 11}).status_code == 422
    assert alice.put(f"/api/library/{ITEM}", json={"status": "finished",
                                                   "rating": -1}).status_code == 422


def test_delete_my_data_clears_the_library(alice):
    alice.put(f"/api/library/{ITEM}", json={"status": "want"})
    alice.put(f"/api/library/{OTHER}", json={"status": "finished", "rating": 8})
    assert alice.delete("/api/me/data").json() == {"deleted_rows": 2}
    assert alice.get("/api/library").json() == []


def test_one_user_cannot_see_or_touch_anothers_library():
    """RLS is bypassed by the owner connection, so this is enforced in our SQL.
    A missing user_id predicate would make this test the only thing catching it."""
    shared = SqliteCatalogStore(":memory:")
    shared.upsert_items(SEED_ITEMS)

    main.store = shared
    main.refresh_model()
    main.app.dependency_overrides[current_user] = lambda: ALICE
    with TestClient(main.app) as c:
        c.put(f"/api/library/{ITEM}", json={"status": "finished", "rating": 10})
        assert len(c.get("/api/library").json()) == 1

    main.app.dependency_overrides[current_user] = lambda: BOB
    with TestClient(main.app) as c:
        assert c.get("/api/library").json() == []                  # cannot see it
        assert c.delete(f"/api/library/{ITEM}").json() == {"removed": False}
        assert c.delete("/api/me/data").json() == {"deleted_rows": 0}

    main.app.dependency_overrides[current_user] = lambda: ALICE
    with TestClient(main.app) as c:
        entries = c.get("/api/library").json()
        assert len(entries) == 1 and entries[0]["rating"] == 10     # untouched by Bob
    main.app.dependency_overrides.clear()


def test_library_requires_a_signed_in_user():
    c = _client_as(None)
    with c as client:
        for call in (lambda: client.get("/api/library"),
                     lambda: client.put(f"/api/library/{ITEM}", json={"status": "want"}),
                     lambda: client.delete(f"/api/library/{ITEM}"),
                     lambda: client.delete("/api/me/data")):
            assert call().status_code == 401

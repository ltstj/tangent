"""Verdicts on recommendations, as distinct from ratings of titles.

The distinction is the whole point of the feature, so most of these tests are
about not confusing the two.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import User, current_user, optional_user
from app.seed import SEED_ITEMS
from app.store import SqliteCatalogStore
from app.taste import MATCH_UP_WEIGHT, from_match_feedback

USER = User(id="33333333-3333-3333-3333-333333333333", email="c@example.com")
SOURCE = "tv:seed:got"
REC = "game:seed:witcher3"


@pytest.fixture
def client():
    main.store = SqliteCatalogStore(":memory:")
    main.store.upsert_items(SEED_ITEMS)
    main.refresh_model()
    main.app.dependency_overrides[current_user] = lambda: USER
    main.app.dependency_overrides[optional_user] = lambda: USER
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_a_thumbs_down_suppresses_that_suggestion_only():
    """A rejected match is not a disliked title. Pushing the taste vector away
    would mislearn from a verdict about a pairing, so a down-vote suppresses and
    contributes no weight."""
    weights, suppress = from_match_feedback([{"item_id": REC, "helpful": False}])
    assert weights == {} and suppress == {REC}


def test_a_thumbs_up_pulls_but_less_than_a_rating():
    weights, suppress = from_match_feedback([{"item_id": REC, "helpful": True}])
    assert weights == {REC: MATCH_UP_WEIGHT} and suppress == set()
    # "Good suggestion" is weaker evidence than "I finished it and rated it 9".
    assert MATCH_UP_WEIGHT < 1.0


def test_feedback_round_trips(client):
    r = client.put(f"/api/feedback/{REC}", json={"helpful": False, "source_ids": [SOURCE]})
    assert r.status_code == 200 and r.json()["helpful"] is False
    rows = client.get("/api/feedback").json()
    assert len(rows) == 1
    assert rows[0]["item_id"] == REC and rows[0]["helpful"] is False
    # The source travels with it, or the row is uninterpretable later.
    assert rows[0]["source_ids"] == [SOURCE]


def test_changing_your_mind_updates_rather_than_duplicating(client):
    client.put(f"/api/feedback/{REC}", json={"helpful": False})
    client.put(f"/api/feedback/{REC}", json={"helpful": True})
    rows = client.get("/api/feedback").json()
    assert len(rows) == 1 and rows[0]["helpful"] is True


def test_clearing_feedback(client):
    client.put(f"/api/feedback/{REC}", json={"helpful": True})
    assert client.delete(f"/api/feedback/{REC}").json() == {"cleared": True}
    assert client.get("/api/feedback").json() == []


def test_a_rejected_match_stops_being_recommended(client):
    body = client.post("/api/recommend",
                       json={"favorite_ids": [SOURCE], "target_media": ["game"], "limit": 5}).json()
    assert any(r["item"]["id"] == REC for r in body["results"]), "expected it before rejecting"

    client.put(f"/api/feedback/{REC}", json={"helpful": False, "source_ids": [SOURCE]})
    after = client.post("/api/recommend",
                        json={"favorite_ids": [SOURCE], "target_media": ["game"], "limit": 5}).json()
    assert all(r["item"]["id"] != REC for r in after["results"])
    assert after["suppressed"] == 1


def test_unknown_item_is_rejected(client):
    assert client.put("/api/feedback/nope:0", json={"helpful": True}).status_code == 404


def test_feedback_requires_a_signed_in_user():
    main.store = SqliteCatalogStore(":memory:")
    main.store.upsert_items(SEED_ITEMS)
    main.refresh_model()
    main.app.dependency_overrides.pop(current_user, None)
    main.app.dependency_overrides[optional_user] = lambda: None
    with TestClient(main.app) as c:
        assert c.get("/api/feedback").status_code == 401
        assert c.put(f"/api/feedback/{REC}", json={"helpful": True}).status_code == 401
        assert c.delete(f"/api/feedback/{REC}").status_code == 401
    main.app.dependency_overrides.clear()


def test_delete_my_data_covers_feedback_too(client):
    """Every personal table must be reachable from "delete my data", or the
    promise quietly stops being true as tables are added."""
    client.put(f"/api/library/{REC}", json={"status": "want"})
    client.put(f"/api/feedback/{REC}", json={"helpful": False})
    assert client.delete("/api/me/data").json() == {"deleted_rows": 2}
    assert client.get("/api/feedback").json() == []
    assert client.get("/api/library").json() == []

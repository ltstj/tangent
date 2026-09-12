"""Collaborative filtering, tested against synthetic users.

There is no real interaction data yet - the app has no users - so every test
here constructs its own population. That is a genuine limitation of testing this
feature now, and the reason the privacy thresholds are pinned so tightly: they
are what make the feature safe to ship before anyone has used it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.auth import User, current_user, optional_user
from app.collab import (
    CONFIDENCE_FLOOR,
    FULL_CONFIDENCE_USERS,
    MIN_PAIR_USERS,
    MIN_USERS,
    CollabModel,
    build,
)
from app.seed import SEED_ITEMS
from app.store import SqliteCatalogStore


def _population(n_users: int, items: tuple[str, ...]) -> list[tuple[str, str, float]]:
    return [(f"u{n}", item, 1.0) for n in range(n_users) for item in items]


# --- privacy thresholds -------------------------------------------------------

def test_collaborative_filtering_is_off_below_the_user_threshold():
    """With two users, "people who liked X also liked Y" is not an aggregate -
    it is a readout of the other person's library."""
    model = build(_population(MIN_USERS - 1, ("a", "b")))
    assert model.confidence == 0.0
    assert model.scores_for(["a"]) == {}


def test_a_pair_needs_several_people_before_it_counts():
    """No single person's taste may move a recommendation on its own."""
    shared = _population(MIN_PAIR_USERS - 1, ("a", "b"))
    # Pad with unrelated users so the global threshold is not what blocks it.
    padding = [(f"p{n}", "z", 1.0) for n in range(MIN_USERS + 2)]
    model = build(shared + padding)
    assert model.confidence > 0.0            # enough users overall
    assert model.similarity("a", "b") == 0.0  # but too few share this pair


def test_a_pair_counts_once_enough_people_share_it():
    model = build(_population(max(MIN_USERS, MIN_PAIR_USERS) + 2, ("a", "b")))
    assert model.similarity("a", "b") == pytest.approx(1.0)
    assert model.scores_for(["a"])["b"] > 0


# --- the actual recommendation behaviour --------------------------------------

def test_it_finds_pairings_content_similarity_would_miss():
    """The point of collaborative filtering: a connection with no shared genre,
    tag or synopsis, discovered purely from who liked both."""
    people = _population(8, ("cult-film", "odd-game"))
    model = build(people)
    assert model.scores_for(["cult-film"]).get("odd-game", 0) > 0


def test_dislikes_do_not_build_shared_taste():
    """"We both hated it" is not "we have taste in common" - treating it as such
    recommends more of what people avoided."""
    model = build([(f"u{n}", "bad", -1.0) for n in range(10)])
    assert model.liked_by == {} and model.scores_for(["bad"]) == {}


def test_your_own_seeds_are_not_recommended_back():
    model = build(_population(8, ("a", "b")))
    assert "a" not in model.scores_for(["a"])


def test_confidence_ramps_with_population():
    small = build(_population(MIN_USERS, ("a", "b")))
    large = build(_population(FULL_CONFIDENCE_USERS, ("a", "b")))
    assert 0.0 < small.confidence < large.confidence
    assert large.confidence == pytest.approx(1.0)


def test_switching_on_means_actually_counting_for_something():
    """The first calibration ramped from ~0, so the feature activated and then
    did nothing visible. A signal that survives both privacy gates has to carry
    real weight or it is decoration."""
    just_on = build(_population(MIN_USERS, ("a", "b")))
    assert just_on.confidence >= CONFIDENCE_FLOOR
    assert just_on.scores_for(["a"])["b"] > 0.3


def test_a_large_library_does_not_inflate_scores():
    """Averaged over seeds, so someone with 20 marked titles does not get
    uniformly bigger collaborative scores than someone with two."""
    model = build(_population(8, ("a", "b", "c", "d")))
    one = model.scores_for(["a"])["b"]
    many = model.scores_for(["a", "c", "d"])["b"]
    assert many == pytest.approx(one, rel=0.5)


def test_empty_model_is_harmless():
    assert CollabModel().confidence == 0.0
    assert CollabModel().scores_for(["anything"]) == {}
    assert build([]).scores_for([]) == {}


# --- through the API ----------------------------------------------------------

USER = User(id="44444444-4444-4444-4444-444444444444", email="d@example.com")


@pytest.fixture
def client():
    main.store = SqliteCatalogStore(":memory:")
    main.store.upsert_items(SEED_ITEMS)
    main.refresh_model()
    main._collab_model, main._collab_built_at = None, 0.0
    main.app.dependency_overrides[current_user] = lambda: USER
    main.app.dependency_overrides[optional_user] = lambda: USER
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()
    main._collab_model, main._collab_built_at = None, 0.0


def test_the_api_reports_why_collaborative_filtering_is_inactive(client):
    """A single user's instance must say it is off, not silently do nothing."""
    body = client.post("/api/recommend",
                       json={"favorite_ids": ["tv:seed:got"], "limit": 3}).json()
    c = body["collaborative"]
    assert c["applied"] is False
    assert c["contributing_users"] == 0
    assert c["confidence"] == 0.0
    assert c["min_users"] == MIN_USERS


def test_one_users_marks_do_not_activate_it(client):
    """The threshold has to hold through the real code path, not just the unit."""
    client.put("/api/library/game:seed:witcher3", json={"status": "finished", "rating": 9})
    main._collab_model, main._collab_built_at = None, 0.0
    body = client.post("/api/recommend", json={"limit": 3}).json()
    assert body["collaborative"]["applied"] is False
    assert body["collaborative"]["contributing_users"] == 1

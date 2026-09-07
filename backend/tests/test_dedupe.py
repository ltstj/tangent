from __future__ import annotations

from app.dedupe import plan_seed_merges
from app.models import CatalogItem


def _item(id, title, source, genres=(), tags=(), pop=None, medium="tv"):
    return CatalogItem(id=id, medium=medium, title=title, source=source,
                       source_id=id.split(":")[-1], genres=list(genres),
                       tags=list(tags), popularity=pop)


def test_real_row_wins_and_keeps_the_seeds_curated_tags():
    seed = _item("tv:seed:got", "Game of Thrones", "seed",
                 ["fantasy", "drama"], ["epic", "medieval"], pop=99)
    real = _item("tv:tmdb:1399", "Game of Thrones", "tmdb",
                 ["fantasy", "drama", "action"], ["dragon", "king"], pop=192)
    updated, drop = plan_seed_merges([seed, real])

    assert drop == ["tv:seed:got"]                  # the placeholder goes
    assert [u.id for u in updated] == ["tv:tmdb:1399"]
    kept = updated[0]
    assert kept.tags == ["dragon", "king", "epic", "medieval"]  # real first, seed's extras kept
    assert kept.genres == ["fantasy", "drama", "action"]        # nothing lost either way


def test_seed_without_a_counterpart_is_left_alone():
    """It is still the only copy of that title - dropping it would shrink the
    zero-keys demo catalog."""
    seed = _item("tv:seed:solo", "Solo Show", "seed", ["drama"], ["moody"])
    other = _item("tv:tmdb:9", "Something Else", "tmdb", ["comedy"], [])
    updated, drop = plan_seed_merges([seed, other])
    assert (updated, drop) == ([], [])


def test_most_popular_real_row_wins():
    seed = _item("game:seed:x", "X", "seed", medium="game", tags=["curated"])
    quiet = _item("game:igdb:1", "X", "igdb", medium="game", pop=10)
    loud = _item("game:igdb:2", "X", "igdb", medium="game", pop=5000)
    updated, drop = plan_seed_merges([seed, quiet, loud])
    assert [u.id for u in updated] == ["game:igdb:2"]
    assert "curated" in updated[0].tags
    # Only the seed is retired; two real releases are a separate problem.
    assert drop == ["game:seed:x"]


def test_title_match_ignores_case_and_padding_but_not_medium():
    a = _item("tv:seed:t", "  the thing  ", "seed", tags=["seedy"])
    b = _item("tv:tmdb:t", "The Thing", "tmdb", pop=1)
    c = _item("movie:tmdb:t", "The Thing", "tmdb", medium="movie", pop=1)
    updated, drop = plan_seed_merges([a, b, c])
    assert drop == ["tv:seed:t"]
    assert [u.id for u in updated] == ["tv:tmdb:t"]   # the movie is untouched

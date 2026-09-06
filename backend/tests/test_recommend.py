from __future__ import annotations


def test_same_media_recs_share_taste(model):
    # From a cerebral sci-fi movie, top movie recs should be sci-fi / thriller-ish.
    recs = model.recommend(["movie:seed:bladerunner2049"], target_media=["movie"], limit=3)
    assert recs
    assert all(r["item"].medium == "movie" for r in recs)
    assert any("scifi" in r["item"].genres or "mystery" in r["item"].genres for r in recs)


def test_excludes_the_inputs(model):
    recs = model.recommend(["game:seed:witcher3"], limit=20)
    assert all(r["item"].id != "game:seed:witcher3" for r in recs)


def test_cross_media_jump_movie_to_game(model):
    # "Give me a game like Blade Runner 2049" -> Cyberpunk 2077 should surface.
    recs = model.recommend(["movie:seed:bladerunner2049"], target_media=["game"], limit=5)
    assert recs and all(r["item"].medium == "game" for r in recs)
    assert recs[0]["item"].id == "game:seed:cyberpunk2077"


def test_reasons_explain_the_match(model):
    recs = model.recommend(["tv:seed:got"], target_media=["game"], limit=3)
    top = recs[0]
    # Fantasy show -> Witcher 3, explained by shared fantasy/epic signals.
    assert top["item"].id == "game:seed:witcher3"
    assert any("fantasy" in reason or "epic" in reason for reason in top["reasons"])


def test_scores_are_sorted_desc(model):
    recs = model.recommend(["book:seed:neuromancer"], limit=10)
    scores = [r["score"] for r in recs]
    assert scores == sorted(scores, reverse=True)

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


def test_genre_signal_is_independent_of_tag_count(model):
    """A verbose source must not dilute its own genre match.

    Genres and tags are normalized as separate blocks, so adding noise tags to an
    item leaves the genre contribution to the score untouched. Sharing the whole
    vocabulary (the old single-block layout) made a book with a dozen Open Library
    subjects score far below a tag-less TMDB movie on the same shared genre.
    """
    from app.models import CatalogItem
    from app.recommend import TasteModel

    lean = CatalogItem(id="book:t:lean", medium="book", title="Lean", genres=["scifi"])
    noisy = CatalogItem(
        id="book:t:noisy", medium="book", title="Noisy", genres=["scifi"],
        tags=[f"filler{i}" for i in range(12)],
    )
    probe = CatalogItem(id="movie:t:probe", medium="movie", title="Probe", genres=["scifi"])
    m = TasteModel([lean, noisy, probe])
    scores = {r["item"].id: r["score"] for r in m.recommend(["movie:t:probe"], limit=5)}
    assert scores["book:t:lean"] == scores["book:t:noisy"]

def test_rare_genres_outweigh_ubiquitous_ones():
    """IDF: sharing a rare genre should beat sharing a common one."""
    from app.models import CatalogItem
    from app.recommend import TasteModel

    common = [CatalogItem(id=f"movie:t:c{i}", medium="movie", title=f"C{i}", genres=["action"])
              for i in range(20)]
    rare = CatalogItem(id="game:t:rare", medium="game", title="Rare", genres=["western"])
    probe = CatalogItem(id="tv:t:probe", medium="tv", title="Probe", genres=["action", "western"])
    twin = CatalogItem(id="game:t:common", medium="game", title="Common", genres=["action"])
    m = TasteModel([*common, rare, twin, probe])
    scores = {r["item"].id: r["score"] for r in m.recommend(["tv:t:probe"], target_media=["game"], limit=5)}
    assert scores["game:t:rare"] > scores["game:t:common"]


def test_embedding_block_bridges_disjoint_tag_vocabularies():
    """The point of the embedding block.

    Two titles that share no genre-vocabulary token and no tag token cannot be
    connected by the structured blocks at all - which is why TMDB and IGDB, who
    agree on ~14% of each other's tag vocabulary, could only ever match on broad
    genre. A synopsis vector connects them on meaning instead.
    """
    import numpy as np

    from app.models import CatalogItem
    from app.recommend import TasteModel

    show = CatalogItem(id="tv:t:show", medium="tv", title="Show",
                       genres=["drama"], tags=["dragon", "kingdom"])
    near = CatalogItem(id="game:t:near", medium="game", title="Near",
                       genres=["rpg"], tags=["medieval", "sword"])
    far = CatalogItem(id="game:t:far", medium="game", title="Far",
                      genres=["rpg"], tags=["spreadsheet"])
    assert not (set(show.tags) & set(near.tags))  # nothing for the tag block to match

    # Hand-built vectors: `near` points with the show, `far` points away.
    vecs = {
        "tv:t:show": np.array([1.0, 0.0], dtype=np.float32),
        "game:t:near": np.array([0.94, 0.34], dtype=np.float32),
        "game:t:far": np.array([0.0, 1.0], dtype=np.float32),
    }
    without = TasteModel([show, near, far])
    with_embed = TasteModel([show, near, far], vecs)

    def score(model, item_id):
        return next(r["score"] for r in model.recommend(["tv:t:show"], limit=5)
                    if r["item"].id == item_id)

    # Structurally the two games are interchangeable; only meaning separates them.
    assert score(without, "game:t:near") == score(without, "game:t:far")
    assert score(with_embed, "game:t:near") > score(with_embed, "game:t:far")


def test_missing_embeddings_degrade_gracefully():
    """Partial coverage must not skew ranking: 56 books have no synopsis at all."""
    import numpy as np

    from app.models import CatalogItem
    from app.recommend import TasteModel

    a = CatalogItem(id="movie:t:a", medium="movie", title="A", genres=["scifi"])
    b = CatalogItem(id="book:t:b", medium="book", title="B", genres=["scifi"])
    model = TasteModel([a, b], {"movie:t:a": np.ones(4, dtype=np.float32) / 2})
    recs = model.recommend(["movie:t:a"], limit=5)
    assert recs and recs[0]["item"].id == "book:t:b"   # un-embedded item still ranks

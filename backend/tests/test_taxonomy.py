from __future__ import annotations

from app.taxonomy import normalize_genre, split_genres_tags


def test_maps_known_source_labels_to_unified():
    assert normalize_genre("Science Fiction") == "scifi"
    assert normalize_genre("Role-playing (RPG)") == "rpg"
    assert normalize_genre("Sci-Fi & Fantasy") == "scifi"


def test_passthrough_and_non_genre():
    # already-unified label
    assert normalize_genre("Horror") == "horror"
    # not a unified genre -> None (handled as a tag by split_genres_tags)
    assert normalize_genre("Neo-noir vibes") is None


def test_split_partitions_and_dedupes():
    genres, tags = split_genres_tags(["Science Fiction", "Cyberpunk", "scifi", "Dystopia"])
    assert genres == ["scifi"]                 # deduped
    assert "cyberpunk" in tags and "dystopia" in tags
    assert "scifi" not in tags

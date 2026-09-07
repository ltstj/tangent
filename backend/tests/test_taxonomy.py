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


def test_compound_open_library_subject_yields_its_genres():
    # OL ships BISAC-style compound subjects. Left unsplit these slugged into one
    # unmatchable token ("fictionsciencefictiongeneral") and the genre was lost.
    genres, tags = split_genres_tags(["Fiction, science fiction, general"])
    assert genres == ["scifi"]
    assert not any("fictionscience" in t for t in tags)


def test_fiction_is_not_a_drama():
    # "Fiction" tags nearly every OL book; mapping it to drama made 76% of the
    # book catalog look like dramas and swamped their real genres.
    genres, _ = split_genres_tags(["Fiction"])
    assert genres == []


def test_shelf_metadata_is_dropped():
    _, tags = split_genres_tags(
        ["Large type books", "New York Times bestseller", "Accessible book", "Murder"]
    )
    assert tags == ["murder"]


def test_qualifier_and_accent_folding():
    assert normalize_genre("Fantasy fiction") == "fantasy"
    assert normalize_genre("Horror stories") == "horror"
    assert normalize_genre("Science-fiction") == "scifi"
    _, tags = split_genres_tags(["Littérature américaine"])
    assert tags == ["litteratureamericaine"]


def test_tag_forms_are_canonicalized_across_sources():
    # IGDB says "dragons"/"monsters", TMDB says "dragon"/"monster". As exact
    # tokens those never matched, so a game could not share a theme with a show.
    from app.taxonomy import normalize_tag

    assert normalize_tag("dragons") == normalize_tag("dragon") == "dragon"
    assert normalize_tag("zombies") == "zombie"
    assert normalize_tag("dystopian") == "dystopia"
    assert normalize_tag("darkfantasy") == normalize_tag("highfantasy") == "fantasyworld"
    # Words that merely end in s must survive intact.
    assert normalize_tag("chess") == "chess"
    assert normalize_tag("princess") == "princess"

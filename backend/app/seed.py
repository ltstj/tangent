"""A small, hand-built seed catalog so Tangent runs (and demos cross-media) with
zero API keys. Real ingestion (TMDB/IGDB/Open Library) replaces/augments this;
see ingest.py. Genres/tags use the unified vocabulary from taxonomy.py.
"""
from __future__ import annotations

from .models import CatalogItem


def _item(id, medium, title, year, genres, tags, rating, pop, overview) -> CatalogItem:
    return CatalogItem(
        id=id, medium=medium, title=title, year=year, genres=genres, tags=tags,
        rating=rating, popularity=pop, overview=overview, source="seed", source_id=id.split(":")[-1],
    )


SEED_ITEMS: list[CatalogItem] = [
    # --- dark / cerebral sci-fi (cross-media cluster) ---
    _item("movie:seed:bladerunner2049", "movie", "Blade Runner 2049", 2017,
          ["scifi", "drama", "mystery"], ["dystopia", "noir", "androids", "slowburn"], 8.0, 90,
          "A young blade runner uncovers a secret that could plunge society into chaos."),
    _item("tv:seed:westworld", "tv", "Westworld", 2016,
          ["scifi", "drama", "mystery"], ["androids", "dystopia", "philosophical"], 8.5, 88,
          "Guests indulge their fantasies in a violent, AI-run frontier theme park."),
    _item("game:seed:cyberpunk2077", "game", "Cyberpunk 2077", 2020,
          ["scifi", "rpg", "action"], ["dystopia", "noir", "openworld", "cybernetics"], 8.1, 95,
          "A mercenary navigates a sprawling neon dystopia of implants and intrigue."),
    _item("book:seed:neuromancer", "book", "Neuromancer", 1984,
          ["scifi"], ["dystopia", "noir", "cyberpunk", "ai"], 8.2, 70,
          "A washed-up hacker is hired for one last job against a powerful AI."),

    # --- epic fantasy cluster ---
    _item("tv:seed:got", "tv", "Game of Thrones", 2011,
          ["fantasy", "drama", "action"], ["politics", "dragons", "medieval", "epic"], 9.0, 99,
          "Noble families vie for control of the Iron Throne."),
    _item("game:seed:witcher3", "game", "The Witcher 3: Wild Hunt", 2015,
          ["rpg", "fantasy", "adventure"], ["monsters", "openworld", "medieval", "epic"], 9.3, 97,
          "A monster hunter searches a war-torn world for his adopted daughter."),
    _item("book:seed:nameofthewind", "book", "The Name of the Wind", 2007,
          ["fantasy"], ["magic", "epic", "comingofage"], 8.6, 65,
          "A gifted young man grows into the most notorious wizard of his age."),
    _item("movie:seed:lotrfellowship", "movie", "The Lord of the Rings: The Fellowship of the Ring", 2001,
          ["fantasy", "adventure", "action"], ["epic", "medieval", "quest"], 8.9, 96,
          "A hobbit sets out to destroy a powerful ring and save Middle-earth."),

    # --- tense heist / crime thrillers ---
    _item("movie:seed:heat", "movie", "Heat", 1995,
          ["crime", "thriller", "drama"], ["heist", "noir", "cops"], 8.3, 80,
          "A master thief and a relentless detective circle each other in LA."),
    _item("game:seed:gtav", "game", "Grand Theft Auto V", 2013,
          ["action", "adventure"], ["heist", "openworld", "crime"], 9.0, 98,
          "Three criminals scheme through a satirical Southern California."),
    _item("tv:seed:breakingbad", "tv", "Breaking Bad", 2008,
          ["crime", "drama", "thriller"], ["antihero", "drugs", "transformation"], 9.4, 97,
          "A chemistry teacher turns to making meth after a cancer diagnosis."),
    _item("book:seed:gonegirl", "book", "Gone Girl", 2012,
          ["thriller", "mystery", "crime"], ["twist", "marriage", "unreliable"], 8.0, 72,
          "A woman disappears on her anniversary and nothing is what it seems."),

    # --- cozy / feel-good ---
    _item("tv:seed:tedlasso", "tv", "Ted Lasso", 2020,
          ["comedy", "drama", "sport"], ["heartwarming", "underdog", "wholesome"], 8.8, 85,
          "An American football coach takes charge of an English soccer team."),
    _item("game:seed:stardew", "game", "Stardew Valley", 2016,
          ["simulation", "rpg", "indie"], ["farming", "wholesome", "relaxing"], 8.9, 90,
          "You inherit a run-down farm and build a new life in a small town."),
    _item("movie:seed:paddington2", "movie", "Paddington 2", 2017,
          ["comedy", "family", "adventure"], ["heartwarming", "wholesome"], 8.2, 78,
          "A polite bear brings warmth and mayhem to a London neighborhood."),

    # --- horror ---
    _item("game:seed:residentevil2", "game", "Resident Evil 2", 2019,
          ["horror", "action", "shooter"], ["zombies", "survival", "tense"], 8.6, 84,
          "Survivors fight to escape a city overrun by the undead."),
    _item("movie:seed:hereditary", "movie", "Hereditary", 2018,
          ["horror", "drama", "mystery"], ["occult", "family", "dread"], 7.9, 76,
          "A grieving family is haunted by sinister and tragic occurrences."),
]

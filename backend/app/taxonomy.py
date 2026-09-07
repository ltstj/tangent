"""Unified taste vocabulary.

Each source speaks its own genre language. We fold them into one shared set so a
sci-fi movie, a sci-fi game, and a sci-fi novel share the token "scifi" and can
be compared. Unknown labels pass through as lowercased slugs (still useful as
tags), so nothing is lost when a mapping is missing.

Open Library is the awkward one: its "subjects" are BISAC-style compound phrases
("Fiction, science fiction, general") mixed with library shelf metadata ("Large
type books", "New York Times bestseller"). Left alone, a compound phrase slugs
into one unmatchable token and the shelf metadata crowds out real taste signal,
so books stop matching anything outside their own medium. We therefore split
compound labels into parts, map each part, and drop the cataloging noise.
"""
from __future__ import annotations

import re
import unicodedata

# The shared genre vocabulary the app reasons about.
UNIFIED_GENRES = {
    "action", "adventure", "animation", "comedy", "crime", "documentary",
    "drama", "family", "fantasy", "history", "horror", "music", "mystery",
    "romance", "scifi", "sport", "thriller", "war", "western", "rpg",
    "strategy", "shooter", "puzzle", "platformer", "simulation", "indie",
    "nonfiction",
}

# Source-label -> unified genre. Lowercased keys.
_MAP = {
    # TMDB (movies + TV)
    "science fiction": "scifi", "sci-fi & fantasy": "scifi", "action & adventure": "action",
    "tv movie": "drama", "kids": "family", "reality": "documentary", "news": "documentary",
    "soap": "drama", "talk": "documentary", "war & politics": "war",
    # IGDB (games)
    "role-playing (rpg)": "rpg", "role playing": "rpg", "turn-based strategy (tbs)": "strategy",
    "real time strategy (rts)": "strategy", "hack and slash/beat 'em up": "action",
    "shooter": "shooter", "platform": "platformer", "puzzle": "puzzle", "racing": "sport",
    "sport": "sport", "fighting": "action", "adventure": "adventure", "indie": "indie",
    "simulator": "simulation", "strategy": "strategy", "tactical": "strategy",
    # Open Library (books) subjects (best-effort)
    "juvenile fiction": "family", "fantasy fiction": "fantasy",
    "detective and mystery stories": "mystery", "biography": "nonfiction",
    "history": "history", "romance fiction": "romance", "thrillers": "thriller",
    "horror tales": "horror",
}

# Punctuation-insensitive lookups, so "Science-fiction", "Science fiction." and
# "SCIENCE FICTION" all land on the same unified genre.
_SLUG_MAP = {re.sub(r"[^a-z0-9]+", "", k): v for k, v in _MAP.items()}
_SLUG_MAP.update({
    "sciencefiction": "scifi", "sciencefictions": "scifi", "sf": "scifi",
    "horrorstories": "horror", "horrortales": "horror", "ghoststories": "horror",
    "detectiveandmysterystories": "mystery", "mysteryanddetectivestories": "mystery",
    "detectivestories": "mystery", "suspensefiction": "thriller",
    "thrillersuspense": "thriller", "lovestories": "romance",
    "adventurestories": "adventure", "adventureandadventurers": "adventure",
    "historicalfiction": "history", "biographies": "nonfiction",
    "autobiography": "nonfiction", "humor": "comedy", "humorous": "comedy",
    "comics": "animation", "graphicnovels": "animation",
})

# Labels that describe a shelf, a format, or an accolade - not a taste. Dropping
# them matters because they are numerous on Open Library records and every extra
# token dilutes the genuine signal when the vector is normalized.
_NOISE = {
    "fiction", "nonfiction", "general", "literature", "novel", "novels",
    "americanliterature", "englishliterature", "englishfiction", "americanfiction",
    "largetypebooks", "accessiblebook", "protecteddaisy", "inlibrary",
    "internetarchivewishlist", "overdrive", "newyorktimesbestseller",
    "newyorktimesbestsellers", "bestsellers", "openlibrarystaffpicks",
    "textbook", "textbooks", "readingmaterials", "translations",
    "popularprint", "lendinglibrary", "paperback", "hardcover", "ebook",
    "audiobook", "booksandreading", "literarycollections",
    # IGDB keywords carry storefront, platform and awards metadata alongside
    # real themes. Listed explicitly rather than pattern-matched, because
    # "steampunk" is a genuine taste tag and any /steam/ rule eats it.
    "steam", "steamachievement", "steamtradingcard", "steamcloud",
    "steamworkshop", "steamearlyaccess", "achievement", "retroachievement",
    "playstationtrophie", "playstationtrophies", "playstationplus",
    "playstationnetwork", "nintendosupersystem", "nintendoswitchonline",
    "xboxcontrollersupportforpc", "xboxlive", "singleplayeronly",
    "licensedgame", "censoredversion", "yearinthetitle", "availableonlunaplus",
    "gamecriticsaward", "gamecriticsawards", "digitaldistribution",
}
# Prefixes for machine-generated collection ids ("collectionid...", "nyt:...").
_NOISE_PREFIXES = (
    "collectionid", "nyt", "lccn", "isbn", "ddc", "lcc",
    # Awards and expo families: "thegameawardsbestaudiodesignnominee" and a
    # dozen siblings. Safe as prefixes - no real theme starts this way.
    "thegameawards", "playstationexperience",
)

# Sources describe the same idea in different words, and by far the commonest
# split is plain plurality: IGDB says "dragons", "monsters", "zombies" where TMDB
# says "dragon", "monster", "zombie". Tags are matched as exact tokens, so those
# pairs never met and only 11% of the TMDB and IGDB tag vocabularies overlapped.
# Folding both sides through one canonical form is what lets a game share a theme
# with a show. Correctness of the singular matters less than applying the same
# rule everywhere: "stories" -> "storie" is fine as long as it is consistent.
_TAG_SYNONYMS = {
    "dystopian": "dystopia", "postapocalyptic": "postapocalypse",
    "postapocalypticfuture": "postapocalypse", "apocalyptic": "apocalypse",
    "artificialintelligenceai": "artificialintelligence", "ai": "artificialintelligence",
    "mech": "mecha", "basedoncomics": "basedoncomic",
    "basedonnovelorbook": "basedonnovel", "basedonbook": "basedonnovel",
    "basedonanovel": "basedonnovel", "animeinspired": "anime",
    "timetravelling": "timetravel", "timetraveling": "timetravel",
    "supernaturalhorror": "supernatural", "psychologicalhorror": "psychological",
    "psychologicalthriller": "psychological", "conspiracythriller": "conspiracy",
    "spaceships": "spaceship", "alieninvasion": "alien", "aliencontact": "alien",
    "humanalienencounters": "alien", "swordplay": "sword", "swordsman": "sword",
    "murdermystery": "murder", "murderinvestigation": "murder",
    "detectiveandmysterystories": "detective", "privateinvestigators": "detective",
    "highfantasy": "fantasyworld", "darkfantasy": "fantasyworld",
    "epicfantasy": "fantasyworld", "magicsystem": "magic", "wizards": "magic",
    "kings": "king", "kingdoms": "kingdom", "knights": "knight",
    "medievalfantasy": "medieval", "middleages": "medieval",
}


def normalize_tag(slug: str) -> str:
    """Canonical form of a theme tag: synonym-folded, then de-pluralized."""
    slug = _TAG_SYNONYMS.get(slug, slug)
    if len(slug) > 4 and slug.endswith("s") and not slug.endswith(("ss", "us", "is")):
        singular = slug[:-1]
        slug = _TAG_SYNONYMS.get(singular, singular)
    return slug


# Compound labels arrive comma/slash/ampersand separated, or with an em-dash
# subdivision ("Horror -- England"). Split on all of them.
_SPLIT_RE = re.compile(r"\s*(?:,|;|/|\||&|--|—)\s*")


def _deaccent(text: str) -> str:
    """Fold accents so "littérature américaine" doesn't slug to a novel token."""
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _deaccent(label).strip().lower())


def _is_noise(slug: str) -> bool:
    return slug in _NOISE or slug.startswith(_NOISE_PREFIXES)


def _strip_qualifier(part: str) -> str:
    """Open Library pins "fiction" onto genre words ("fantasy fiction",
    "fiction horror"). Strip it so the genre underneath is findable."""
    words = [w for w in re.split(r"\s+", part.strip().lower()) if w]
    if len(words) > 1:
        words = [w for w in words if w not in ("fiction", "fictional", "stories", "general")]
    return " ".join(words) or part


def _split_compound(label: str) -> list[str]:
    """One raw label -> its constituent parts, longest-first is not needed since
    every part is looked up independently."""
    return [p for p in _SPLIT_RE.split(label) if p and p.strip()]


def normalize_genre(label: str) -> str | None:
    """Map a raw source genre to a unified genre, or None if it isn't one.

    Single-label semantics: compound phrases are handled by split_genres_tags.
    """
    low = label.strip().lower()
    if low in _MAP:
        return _MAP[low]
    slug = _slug(label)
    if slug in _SLUG_MAP:
        return _SLUG_MAP[slug]
    if slug in UNIFIED_GENRES:
        return slug
    # "Fantasy fiction" / "Horror stories" -> retry on the bare genre word.
    stripped = _strip_qualifier(low)
    if stripped != low:
        s = _slug(stripped)
        if s in _SLUG_MAP:
            return _SLUG_MAP[s]
        if s in UNIFIED_GENRES:
            return s
    return None


def split_genres_tags(labels: list[str]) -> tuple[list[str], list[str]]:
    """Partition raw labels into (unified genres, leftover tags). Deduped, order-stable.

    A compound label contributes every genre it names: "Fiction, science fiction,
    general" yields ["scifi"], with the shelf words dropped rather than mashed
    into an unmatchable "fictionsciencefictiongeneral" token.
    """
    genres: list[str] = []
    tags: list[str] = []
    seen_g: set[str] = set()
    seen_t: set[str] = set()

    def add_genre(g: str) -> None:
        if g not in seen_g:
            seen_g.add(g)
            genres.append(g)

    def add_tag(slug: str) -> None:
        if not slug or _is_noise(slug):
            return
        slug = normalize_tag(slug)
        if slug and slug not in seen_t and not _is_noise(slug):
            seen_t.add(slug)
            tags.append(slug)

    for label in labels:
        if not label:
            continue
        # Whole-label mapping wins: it is the curated, source-specific reading.
        whole = normalize_genre(label)
        if whole:
            add_genre(whole)
        parts = _split_compound(label)
        matched_any = whole is not None
        for part in parts:
            g = normalize_genre(part)
            if g:
                add_genre(g)
                matched_any = True
        if matched_any:
            # Keep the non-genre parts of a compound label as themes.
            if len(parts) > 1:
                for part in parts:
                    if not normalize_genre(part):
                        add_tag(_slug(part))
            continue
        # Nothing in the label is a genre: keep its parts as tags.
        for part in (parts if len(parts) > 1 else [label]):
            add_tag(_slug(part))
    return genres, tags

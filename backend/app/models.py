"""The unified catalog item: one shape for movies, TV, games, and books.

Every source (TMDB, IGDB, Open Library) is normalized into this, so the
recommender never has to care what medium a title is until the caller asks to
filter by one. That single shared shape is what makes cross-media work.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Medium = Literal["movie", "tv", "game", "book"]

# How you actually get hold of a title. "link" is an honest pointer with no price
# attached - a bookshop or a ticket aggregator - and exists so books and theater
# are never given invented numbers just to fill the field.
OfferKind = Literal["buy", "rent", "subscription", "free", "link"]


# Why a status and not just an empty list: "we could not reach the price source"
# and "this genuinely has no offers" are different facts, and a UI that renders
# them identically tells the reader something we do not know. Same reasoning as
# `cheapest_subscription` being absent rather than zero.
AvailabilityStatus = Literal[
    "ok",                  # offers found
    "none_listed",         # source answered, nothing available
    "source_unavailable",  # we could not ask; say so rather than imply absence
    "not_supported",       # we have no source for this medium/item yet
]


class Offer(BaseModel):
    """One way to get one title, from one place."""

    kind: OfferKind
    store: str
    url: str
    price: float | None = None      # None for subscriptions and bare links
    currency: str = "USD"
    was: float | None = None        # list price, when this is a discount
    note: str = ""                  # "historical low", "on Game Pass", ...

    @property
    def savings_pct(self) -> int | None:
        if self.price is None or not self.was or self.was <= self.price:
            return None
        return round((self.was - self.price) / self.was * 100)


LibraryStatus = Literal["want", "in_progress", "finished"]


class LibraryEntry(BaseModel):
    """One title in one person's library."""

    item: CatalogItem
    status: LibraryStatus = "want"
    rating: float | None = None      # 0..10, same scale as catalog ratings
    note: str = ""
    updated_at: str | None = None


class Availability(BaseModel):
    """Everything we know about getting hold of one title."""

    offers: list[Offer] = Field(default_factory=list)
    status: AvailabilityStatus = "ok"
    detail: str = ""            # why, when status is not "ok"
    price_region: str | None = None   # the region these prices actually apply to
    notes: list[str] = Field(default_factory=list)  # e.g. a cheaper edition


class CatalogItem(BaseModel):
    id: str                       # stable "<medium>:<source>:<source_id>", e.g. "movie:tmdb:603"
    medium: Medium
    title: str
    year: int | None = None
    genres: list[str] = Field(default_factory=list)  # unified genre vocabulary
    tags: list[str] = Field(default_factory=list)     # extra themes / keywords (unified where possible)
    rating: float | None = None   # normalized to 0..10 at ingest
    popularity: float | None = None
    overview: str = ""
    image: str | None = None      # poster / cover art URL
    source: str = ""              # "tmdb" | "igdb" | "openlibrary" | "seed"
    source_id: str = ""

    def genre_tokens(self) -> list[str]:
        """Unified-genre tokens: the dominant, cross-media-comparable signal."""
        return [f"g:{g}" for g in self.genres]

    def tag_tokens(self) -> list[str]:
        """Theme/keyword tokens: finer-grained, and far noisier per source."""
        return [f"t:{t}" for t in self.tags]

    def taste_tokens(self) -> list[str]:
        """Genres + tags as the categorical feature tokens for similarity."""
        return [*self.genre_tokens(), *self.tag_tokens()]

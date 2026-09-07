"""The unified catalog item: one shape for movies, TV, games, and books.

Every source (TMDB, IGDB, Open Library) is normalized into this, so the
recommender never has to care what medium a title is until the caller asks to
filter by one. That single shared shape is what makes cross-media work.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Medium = Literal["movie", "tv", "game", "book"]


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

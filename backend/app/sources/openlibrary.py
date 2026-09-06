"""Open Library (books). No API key required.

We pull by subject (a decent proxy for "popular in a genre") and normalize each
doc into a CatalogItem. normalize_doc() is pure, so it's unit-tested without network.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..models import CatalogItem
from ..taxonomy import split_genres_tags

BASE = "https://openlibrary.org"
# Subjects we seed the book catalog from.
DEFAULT_SUBJECTS = ["science_fiction", "fantasy", "thriller", "mystery", "romance", "horror"]


def normalize_doc(doc: dict[str, Any], subject_hint: str = "") -> CatalogItem | None:
    key = doc.get("key") or doc.get("cover_edition_key") or ""
    title = doc.get("title")
    if not key or not title:
        return None
    source_id = str(key).rsplit("/", 1)[-1]
    raw_subjects = list(doc.get("subject", []) or [])
    if subject_hint:
        raw_subjects.append(subject_hint.replace("_", " "))
    genres, tags = split_genres_tags(raw_subjects)
    rating = doc.get("ratings_average")
    cover_i = doc.get("cover_i")
    return CatalogItem(
        id=f"book:openlibrary:{source_id}",
        medium="book",
        title=title,
        year=doc.get("first_publish_year"),
        genres=genres or ["nonfiction"] if "biography" in raw_subjects else genres,
        tags=tags[:12],
        rating=round(float(rating) * 2, 1) if rating else None,  # OL is 0..5 -> 0..10
        popularity=float(doc.get("want_to_read_count") or doc.get("readinglog_count") or 0) or None,
        overview="",
        image=f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else None,
        source="openlibrary",
        source_id=source_id,
    )


def fetch_subject(subject: str, limit: int = 25) -> list[CatalogItem]:
    url = f"{BASE}/search.json"
    params = {"subject": subject, "limit": limit, "fields": "key,title,first_publish_year,subject,ratings_average,want_to_read_count,cover_i"}
    with httpx.Client(timeout=30) as client:
        data = client.get(url, params=params).json()
    out = [normalize_doc(d, subject) for d in data.get("docs", [])]
    return [i for i in out if i]


def fetch_default(limit_per_subject: int = 25) -> list[CatalogItem]:
    items: list[CatalogItem] = []
    for subject in DEFAULT_SUBJECTS:
        items.extend(fetch_subject(subject, limit_per_subject))
    return items


def search(query: str, limit: int = 10) -> list[CatalogItem]:
    with httpx.Client(timeout=30) as client:
        data = client.get(f"{BASE}/search.json", params={"q": query, "limit": limit,
            "fields": "key,title,first_publish_year,subject,ratings_average,cover_i"}).json()
    out = [normalize_doc(d) for d in data.get("docs", [])]
    return [i for i in out if i]

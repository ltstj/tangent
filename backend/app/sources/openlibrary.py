"""Open Library (books). No API key required.

We pull by subject (a decent proxy for "popular in a genre") and normalize each
doc into a CatalogItem. normalize_doc() is pure, so it's unit-tested without network.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


def _description(work: dict[str, Any]) -> str:
    """Pull a synopsis out of a works record.

    Open Library returns `description` as either a plain string or a
    {"type": ..., "value": ...} object depending on how the record was edited,
    and plenty of works have neither.
    """
    desc = work.get("description")
    if isinstance(desc, dict):
        desc = desc.get("value")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    first = work.get("first_sentence")
    if isinstance(first, dict):
        first = first.get("value")
    return first.strip() if isinstance(first, str) else ""


def fetch_descriptions(items: list[CatalogItem], max_workers: int = 6) -> list[CatalogItem]:
    """Fill in `overview` for book items, in place.

    The search endpoint carries no synopsis, so every book arrived with
    overview="" - which would leave the largest medium in the catalog with a null
    synopsis embedding, i.e. Phase 2 improving everything except books. One
    request per work, so this is fanned out but deliberately modest: Open
    Library is a free service and already the slowest of the three.
    """
    def one(item: CatalogItem) -> None:
        with httpx.Client(timeout=20) as client:
            work = client.get(f"{BASE}/works/{item.source_id}.json").json()
        text = _description(work)
        if text:
            item.overview = text

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for fut in [pool.submit(one, i) for i in items if i.source == "openlibrary"]:
            try:
                fut.result()
            except Exception:
                pass
    return items


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
    # Descriptions come from a per-work endpoint, so ingest has to ask for them
    # explicitly or every book lands with an empty synopsis to embed.
    return fetch_descriptions(items)


def search(query: str, limit: int = 10) -> list[CatalogItem]:
    # Runs off the request path (see _live_search), so a generous but bounded timeout.
    with httpx.Client(timeout=8) as client:
        data = client.get(f"{BASE}/search.json", params={"q": query, "limit": limit,
            "fields": "key,title,first_publish_year,subject,ratings_average,cover_i"}).json()
    out = [normalize_doc(d) for d in data.get("docs", [])]
    return [i for i in out if i]

# Tangent

**Find your next favorite across movies, TV, games, and books.**

Tangent recommends entertainment by the *taste* underneath it, not just the label
on it. Tell it what you love and it breaks those titles down into shared "taste
metrics" (genre, theme, mood/tone, pacing, era, ratings) plus a semantic read of
their description, then finds more you'll like. Its signature move is cross-media
recommendation: give it a TV show and ask for a game (or a book, or a movie) that
hits the same way.

> Status: early scaffold. See **[ROADMAP.md](ROADMAP.md)** for the full plan.

## What it does (vision)
- **Search and autocomplete** across a catalog of movies, TV, games, and books.
- **"More like this"** recommendations from one or more favorites.
- **Cross-media jump**: recommend across formats (show to game, book to movie, and so on).
- **Genre controls**: filter, pick favorite genres as a starting point, or weight
  how much genre matters versus tone/vibe.
- **"Where to get it" and best price**: game deals, cheapest streaming subscription
  or rent/buy for movies and TV, and honest link-outs for books and theater tickets.
- **Accounts and library**: mark titles *want*, *in progress*, or *finished*, rate
  them, and have Tangent learn your taste (and improve for people with similar taste).

## Stack
- **Backend:** Python and FastAPI (the recommendation engine: embeddings and vector math).
- **Data and auth:** Postgres with `pgvector` via **Supabase** (catalog, user library, similarity search, auth).
- **Frontend:** React (Vite). *(swappable to Vue)*
- **Sources:** TMDB (movies/TV), IGDB (games), Open Library (books), CheapShark (game deals).

## Data sources and keys
All API keys live in a local, **gitignored** `.env` (copy `.env.example`). No keys
are committed. CheapShark needs none; TMDB, IGDB, and Supabase do. Respect each
provider's terms (TMDB and IGDB require attribution; use official APIs, never scraping).

## Run it locally (no keys needed)
The catalog is seeded on first run, so recommendations (including the cross-media
jump) work immediately. Add TMDB/IGDB keys later to ingest real data.
```bash
# 1) API
cd backend
python -m venv .venv && . .venv/Scripts/activate   # macOS/Linux: . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload                       # http://localhost:8000

# 2) UI (separate terminal)
cd frontend
npm install
npm run dev                                         # http://localhost:5173
```
Optional: `python -m app.ingest` pulls real titles from any source whose keys are
set (plus Open Library, which needs none).

## Repo layout
```
backend/    FastAPI app, recommender (SQLite + numpy), data ingest, tests
frontend/   React + Vite SPA (search, favorites, cross-media recommendations)
ROADMAP.md  the full phased plan
```

## License
MIT, see [LICENSE](LICENSE). Free for anyone to use.

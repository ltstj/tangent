# Tangent roadmap

The full vision, phased so we ship something usable early and layer the rest on
top. Content-based recommendations work from day one (no cold-start); the social
and collaborative features get better as people use it.

## The core idea: one shared "taste space"
Movies, TV, games, and books each have their own metadata vocabularies. Tangent
maps them all into one shared taste space, so recommendations (including
cross-media ones) are just "find the nearest neighbors, filtered to the medium
you asked for." Two signals combine:

1. **Structured metrics**: a unified vocabulary of genre, theme, mood/tone,
   pacing, era, rating, and length/popularity, mapped from each source's tags.
2. **Semantic embedding** of each title's synopsis, so *meaning* becomes a vector
   and similar vibes sit near each other regardless of medium. This is what makes
   "a game like this show" work.

**Score** = weighted blend of tag overlap, metric closeness, and embedding cosine.
A user's **taste vector** is the centroid of their favorites (later: liked items
pull it closer, disliked items push it away).

## Phase 0: scaffold (this commit)
- Repo, README, this roadmap, license, `.gitignore`, `.env.example`.
- FastAPI skeleton with `/health`; config reads keys from env (never committed).

## Phase 1: catalog, search, same-media recs (MVP)
- **Ingest** from TMDB (movies/TV), IGDB (games), and Open Library (books) into
  Postgres; normalize each into the shared metric vocabulary.
- **Autocomplete search** (as-you-type) against the catalog.
- **Content-based recs**: enter favorite(s) and get "more like this" within a
  medium, ranked by tag and metric similarity.

## Phase 2: cross-media, embeddings, genre controls
- Add **synopsis embeddings** (`pgvector`) for a hybrid score.
- **Cross-media jump**: pick input title(s) plus desired output medium(s).
- **Genre options**: filter results by genre, choose favorite genres as a
  cold-start input, and a "genre versus tone" weighting lever.
- **"Why this?"** explanations (shared genre, tone, pacing).

## Phase 3: "where to get it" and best price
- **Games:** CheapShark (current deals across stores) plus IsThereAnyDeal (historical low).
- **Movies and TV:** TMDB watch-providers (JustWatch) for stream/rent/buy, plus a
  maintained subscription-price table to compute the cheapest subscription that has it.
- **Books and theater tickets:** honest link-outs (price comparison, "check your
  library," a tickets aggregator). No scraping, no fabricated prices.

## Phase 4: accounts, library, feedback
- **Auth** (Supabase or social login; never roll our own password storage).
- **Library**: mark titles *want*, *in progress*, *finished*; rate on finish.
- Feedback feeds the **personal** taste vector (likes pull, dislikes push).
- Responsible data handling: hashed credentials, secrets in env, "delete my data."

## Phase 5: collaborative filtering (gets smarter for everyone)
- Item-item collaborative filtering from the interaction matrix ("people whose
  favorites overlap with yours also loved X").
- **Hybrid**: content-based early, weighting in collaborative filtering as data grows.

## Later / stretch
- Shareable taste profiles, mood-based discovery, more media (podcasts, anime),
  regional pricing, affiliate links, a public API.

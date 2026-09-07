// Tiny typed client for the Tangent API.
const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type Medium = "movie" | "tv" | "game" | "book";

export interface CatalogItem {
  id: string;
  medium: Medium;
  title: string;
  year: number | null;
  genres: string[];
  tags: string[];
  rating: number | null;
  overview: string;
  image: string | null;
}

export interface Recommendation {
  item: CatalogItem;
  score: number;
  reasons: string[];
}

export async function searchTitles(q: string, medium?: Medium): Promise<CatalogItem[]> {
  const params = new URLSearchParams({ q, limit: "8" });
  if (medium) params.set("medium", medium);
  const res = await fetch(`${BASE}/api/search?${params}`);
  if (!res.ok) throw new Error(`search failed: ${res.status}`);
  return res.json();
}

export async function getShowcase(limit = 48): Promise<CatalogItem[]> {
  const res = await fetch(`${BASE}/api/showcase?limit=${limit}`);
  if (!res.ok) return [];
  return res.json();
}

export interface GenreCount {
  genre: string;
  count: number;
}

export async function getGenres(): Promise<GenreCount[]> {
  const res = await fetch(`${BASE}/api/genres`);
  if (!res.ok) return [];
  return res.json();
}

export interface RecommendOptions {
  targetMedia?: Medium[] | null;
  /** Cold start: taste from genre names, when there are no favorites yet. */
  seedGenres?: string[];
  /** Restrict which results come back. Never affects their scores. */
  filterGenres?: string[];
  /** 0 = lean on tone (themes + synopsis meaning), 1 = lean on genre, 0.5 = default. */
  genreWeight?: number;
}

export async function recommend(
  favoriteIds: string[],
  opts: RecommendOptions = {},
): Promise<Recommendation[]> {
  const res = await fetch(`${BASE}/api/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      favorite_ids: favoriteIds,
      target_media: opts.targetMedia ?? null,
      seed_genres: opts.seedGenres?.length ? opts.seedGenres : null,
      filter_genres: opts.filterGenres?.length ? opts.filterGenres : null,
      genre_weight: opts.genreWeight ?? null,
      limit: 12,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `recommend failed: ${res.status}`);
  }
  const data = await res.json();
  return data.results as Recommendation[];
}

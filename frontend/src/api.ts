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

export type OfferKind = "buy" | "rent" | "subscription" | "free" | "link";

export interface Offer {
  kind: OfferKind;
  store: string;
  url: string;
  price: number | null;
  currency: string;
  was: number | null;
  note: string;
}

/**
 * "none_listed" and "source_unavailable" are deliberately distinct: one means
 * nothing is available, the other means we could not find out. Rendering them
 * the same way would tell the reader something we do not know.
 */
export type AvailabilityStatus =
  | "ok"
  | "none_listed"
  | "source_unavailable"
  | "not_supported";

export interface OffersResponse {
  item_id: string;
  medium: Medium;
  title: string;
  region: string;
  offers: Offer[];
  /** True when at least one offer carries a real price. */
  priced: boolean;
  status: AvailabilityStatus;
  /** Why, when status is not "ok". */
  detail: string;
  /** The region these prices actually apply to — not always the one requested. */
  price_region: string | null;
  /** Caveats and finds, e.g. a cheaper edition, or that prices are US-only. */
  notes: string[];
  /** Absent means "we could not price one" — never "it isn't streaming anywhere". */
  cheapest_subscription?: { store: string; price: number; currency: string };
  /** TMDB's terms require showing this whenever streaming data is displayed. */
  attribution?: string;
}

export async function getOffers(itemId: string, region = "US"): Promise<OffersResponse> {
  const res = await fetch(`${BASE}/api/offers/${encodeURI(itemId)}?region=${region}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `offers failed: ${res.status}`);
  }
  return res.json();
}

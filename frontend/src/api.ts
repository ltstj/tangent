// Tiny typed client for the Tangent API.
import { accessToken } from "./supabase";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/**
 * Attach the signed-in user's token when there is one.
 *
 * The API decides what a request may see from this token alone — it never
 * trusts a user id sent in a body or query — so an absent token simply means
 * "signed out", not "unauthorized".
 */
async function authHeaders(): Promise<Record<string, string>> {
  const token = await accessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

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

export interface RecommendResult {
  results: Recommendation[];
  /** True when the caller's library shaped these. */
  personalized: boolean;
  library_signals: number;
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
): Promise<RecommendResult> {
  const res = await fetch(`${BASE}/api/recommend`, {
    method: "POST",
    // With a token the API folds the caller's library into the taste vector and
    // filters out what they have already seen.
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
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
  return {
    results: (data.results ?? []) as Recommendation[],
    personalized: Boolean(data.personalized),
    library_signals: Number(data.library_signals ?? 0),
  };
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

export type LibraryStatus = "want" | "in_progress" | "finished";

export interface LibraryEntry {
  item: CatalogItem;
  status: LibraryStatus;
  rating: number | null;
  note: string;
  updated_at: string | null;
}

export async function getLibrary(): Promise<LibraryEntry[]> {
  const res = await fetch(`${BASE}/api/library`, { headers: await authHeaders() });
  if (res.status === 401) return [];
  if (!res.ok) throw new Error(`library failed: ${res.status}`);
  return res.json();
}

export async function setLibraryEntry(
  itemId: string,
  status: LibraryStatus,
  rating: number | null = null,
): Promise<LibraryEntry> {
  const res = await fetch(`${BASE}/api/library/${encodeURI(itemId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ status, rating, note: "" }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `save failed: ${res.status}`);
  }
  return res.json();
}

export async function removeLibraryEntry(itemId: string): Promise<void> {
  const res = await fetch(`${BASE}/api/library/${encodeURI(itemId)}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`remove failed: ${res.status}`);
}

export async function deleteMyData(): Promise<number> {
  const res = await fetch(`${BASE}/api/me/data`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  if (!res.ok) throw new Error(`delete failed: ${res.status}`);
  return (await res.json()).deleted_rows ?? 0;
}

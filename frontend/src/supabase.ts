import { createClient } from "@supabase/supabase-js";

/**
 * Supabase client, used only for authentication.
 *
 * Library reads and writes deliberately go through our own API rather than
 * straight to Supabase: the recommender needs the library server-side to build
 * a personal taste vector, so one API surface beats two data paths to the same
 * rows.
 *
 * Both values below are safe in a browser bundle. The URL is public and the
 * publishable key identifies the project, not a person — what protects data is
 * row-level security plus our API verifying the signed-in user's token. The
 * service-role key must never appear here.
 */
const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const authConfigured = Boolean(url && anonKey);

export const supabase = authConfigured
  ? createClient(url as string, anonKey as string, {
      auth: { persistSession: true, autoRefreshToken: true },
    })
  : null;

/** The current access token, or null when signed out. */
export async function accessToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

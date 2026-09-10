import { useEffect, useMemo, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import Auth from "./Auth";
import Library from "./Library";
import LibraryControls from "./LibraryControls";
import Offers from "./Offers";
import PosterWall from "./PosterWall";
import { supabase } from "./supabase";
import {
  getGenres,
  getLibrary,
  recommend,
  searchTitles,
  type CatalogItem,
  type GenreCount,
  type LibraryEntry,
  type Medium,
  type Recommendation,
} from "./api";

const MEDIA: Medium[] = ["movie", "tv", "game", "book"];
const MEDIUM_LABEL: Record<Medium, string> = { movie: "Movie", tv: "TV", game: "Game", book: "Book" };
const GENRES_COLLAPSED = 12;

export default function App() {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<CatalogItem[]>([]);
  const [favorites, setFavorites] = useState<CatalogItem[]>([]);
  const [target, setTarget] = useState<"any" | Medium>("any");
  const [results, setResults] = useState<Recommendation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);

  const [allGenres, setAllGenres] = useState<GenreCount[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [showAllGenres, setShowAllGenres] = useState(false);
  // The genre-versus-tone lever. 0.5 is the tuned default, so the slider starts
  // centred and only departs from the default when someone moves it.
  const [genreWeight, setGenreWeight] = useState(0.5);

  const [session, setSession] = useState<Session | null>(null);
  const [view, setView] = useState<"discover" | "library">("discover");
  const [library, setLibrary] = useState<LibraryEntry[]>([]);
  const [personalized, setPersonalized] = useState(false);

  const [active, setActive] = useState(-1); // keyboard cursor in the suggestion list
  const debounce = useRef<number | undefined>(undefined);
  const reqSeq = useRef(0); // guards against out-of-order responses
  const inputRef = useRef<HTMLInputElement>(null);

  // With no favorites the picked genres *are* the taste (cold start); with
  // favorites they narrow the results instead. Same control, two honest roles.
  const genresAreSeed = favorites.length === 0;

  useEffect(() => {
    getGenres().then(setAllGenres).catch(() => setAllGenres([]));
  }, []);

  // Track the session, and reload the library whenever it changes: signing out
  // must not leave the previous account's entries on screen.
  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, next) => setSession(next));
    return () => sub.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session) {
      setLibrary([]);
      setView("discover");
      return;
    }
    getLibrary().then(setLibrary).catch(() => setLibrary([]));
  }, [session]);

  // Search-as-you-type (debounced). Live source lookups make this a real request,
  // so wait a beat and require a couple of characters.
  useEffect(() => {
    const term = query.trim();
    if (term.length < 2) {
      setSuggestions([]);
      setActive(-1);
      return;
    }
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => {
      const seq = ++reqSeq.current;
      setSearching(true);
      searchTitles(term)
        .then((items) => {
          if (seq !== reqSeq.current) return; // a newer keystroke already won
          setSuggestions(items.filter((i) => !favorites.some((f) => f.id === i.id)));
          setActive(-1);
        })
        .catch(() => {
          if (seq === reqSeq.current) setSuggestions([]);
        })
        .finally(() => {
          if (seq === reqSeq.current) setSearching(false);
        });
    }, 300);
    return () => window.clearTimeout(debounce.current);
  }, [query, favorites]);

  function addFavorite(item: CatalogItem) {
    setFavorites((f) => [...f, item]);
    setQuery("");
    setSuggestions([]);
    setActive(-1);
    inputRef.current?.focus();
  }
  function removeFavorite(id: string) {
    setFavorites((f) => f.filter((x) => x.id !== id));
  }
  /** Apply one entry change everywhere the library is shown. */
  function applyEntry(itemId: string, entry: LibraryEntry | null) {
    setLibrary((prev) => {
      const rest = prev.filter((e) => e.item.id !== itemId);
      return entry ? [entry, ...rest] : rest;
    });
  }

  function toggleGenre(g: string) {
    setPicked((p) => (p.includes(g) ? p.filter((x) => x !== g) : [...p, g]));
  }

  /** Arrow keys / Enter / Escape over the suggestion list. */
  function onSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!suggestions.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      addFavorite(suggestions[active >= 0 ? active : 0]);
    } else if (e.key === "Escape") {
      setSuggestions([]);
      setActive(-1);
    }
  }

  const canRecommend = favorites.length > 0 || picked.length > 0 || library.length > 0;

  async function getRecommendations() {
    setError(null);
    setLoading(true);
    try {
      const res = await recommend(favorites.map((f) => f.id), {
        targetMedia: target === "any" ? null : [target],
        seedGenres: genresAreSeed ? picked : undefined,
        filterGenres: genresAreSeed ? undefined : picked,
        genreWeight,
      });
      setResults(res.results);
      setPersonalized(res.personalized);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  const visibleGenres = useMemo(
    () => (showAllGenres ? allGenres : allGenres.slice(0, GENRES_COLLAPSED)),
    [allGenres, showAllGenres],
  );

  return (
    <>
      <PosterWall />
      <div className="app">
        <header>
          <h1>Tangent</h1>
          <p className="tag">Find your next favorite across movies, TV, games, and books.</p>
          {session && (
            <nav className="views">
              <button
                className={`view-tab${view === "discover" ? " on" : ""}`}
                onClick={() => setView("discover")}
              >
                Discover
              </button>
              <button
                className={`view-tab${view === "library" ? " on" : ""}`}
                onClick={() => setView("library")}
              >
                My library<span className="gcount">{library.length}</span>
              </button>
            </nav>
          )}
          <Auth session={session} onChange={() => {
            if (supabase) supabase.auth.getSession().then(({ data }) => setSession(data.session));
          }} />
        </header>

        {view === "library" ? (
          <Library entries={library} onChange={applyEntry} />
        ) : (
        <>
        <section className="panel">
          <div className={`search${suggestions.length ? " open" : ""}`}>
            <svg className="search-icon" viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="11" cy="11" r="7" />
              <path d="M16.5 16.5 21 21" />
            </svg>
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onSearchKeyDown}
              placeholder="Search a movie, show, game, or book…"
              aria-label="Search for a title to add as a favorite"
              role="combobox"
              aria-expanded={suggestions.length > 0}
              aria-controls="suggest-list"
              aria-autocomplete="list"
              autoComplete="off"
              spellCheck={false}
            />
            {searching && <span className="spinner" aria-label="searching" />}
            {!searching && query && (
              <button className="clear" onClick={() => setQuery("")} aria-label="Clear search">
                ×
              </button>
            )}

            {suggestions.length > 0 && (
              <ul className="suggest" id="suggest-list" role="listbox">
                {suggestions.map((s, i) => (
                  <li
                    key={s.id}
                    role="option"
                    aria-selected={i === active}
                    className={i === active ? "active" : undefined}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => addFavorite(s)}
                  >
                    {s.image ? (
                      <img className="thumb" src={s.image} alt="" />
                    ) : (
                      <span className="thumb thumb-blank">{MEDIUM_LABEL[s.medium][0]}</span>
                    )}
                    <span className="s-main">
                      <span className="s-title">{s.title}</span>
                      {s.genres.length > 0 && (
                        <span className="s-sub">{s.genres.slice(0, 3).join(" · ")}</span>
                      )}
                    </span>
                    <span className="badge">
                      {MEDIUM_LABEL[s.medium]}
                      {s.year ? ` · ${s.year}` : ""}
                    </span>
                  </li>
                ))}
                <li className="suggest-hint" aria-hidden="true">
                  ↑↓ to browse · ↵ to add · esc to dismiss
                </li>
              </ul>
            )}
          </div>

          {favorites.length > 0 && (
            <div className="chips">
              {favorites.map((f) => (
                <span key={f.id} className="chip">
                  {f.image && <img className="chip-thumb" src={f.image} alt="" />}
                  {f.title}
                  <button onClick={() => removeFavorite(f.id)} aria-label={`Remove ${f.title}`}>
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className="genre-block">
            <div className="genre-head">
              <span className="lbl">
                {genresAreSeed ? "Or start from genres" : "Only show"}
              </span>
              <span className="hint">
                {genresAreSeed
                  ? "no favorites needed — pick a few and go"
                  : "filters results, doesn't change the ranking"}
              </span>
            </div>
            <div className="genre-chips">
              {visibleGenres.map((g) => (
                <button
                  key={g.genre}
                  className={`gchip${picked.includes(g.genre) ? " on" : ""}`}
                  onClick={() => toggleGenre(g.genre)}
                  aria-pressed={picked.includes(g.genre)}
                >
                  {g.genre}
                  <span className="gcount">{g.count}</span>
                </button>
              ))}
              {allGenres.length > GENRES_COLLAPSED && (
                <button className="gchip more" onClick={() => setShowAllGenres((v) => !v)}>
                  {showAllGenres ? "less" : `+${allGenres.length - GENRES_COLLAPSED} more`}
                </button>
              )}
            </div>
          </div>

          <div className="lever">
            <span className="lbl">Match on</span>
            <div className="lever-row">
              <span className={`lever-end${genreWeight < 0.5 ? " lit" : ""}`}>Tone</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={genreWeight}
                onChange={(e) => setGenreWeight(Number(e.target.value))}
                aria-label="Weight results towards tone or genre"
              />
              <span className={`lever-end${genreWeight > 0.5 ? " lit" : ""}`}>Genre</span>
            </div>
            <p className="lever-note">
              {genreWeight < 0.4
                ? "Leaning on vibe — themes and what a story is actually about."
                : genreWeight > 0.6
                  ? "Leaning on genre — sticks close to the same shelf."
                  : "Balanced (the tuned default)."}
            </p>
          </div>

          <div className="controls">
            <div className="control">
              <label className="lbl" htmlFor="target">Recommend</label>
              <select
                id="target"
                value={target}
                onChange={(e) => setTarget(e.target.value as "any" | Medium)}
              >
                <option value="any">Anything (cross-media)</option>
                {MEDIA.map((m) => (
                  <option key={m} value={m}>{MEDIUM_LABEL[m]}s</option>
                ))}
              </select>
            </div>
            <button className="go" disabled={!canRecommend || loading} onClick={getRecommendations}>
              {loading ? "Thinking…" : "Get recommendations"}
            </button>
          </div>
          {!canRecommend && (
            <p className="nudge">Add a favorite above, or pick a genre to start from.</p>
          )}
          {library.length > 0 && (
            <p className="nudge">
              Your library has {library.length}{" "}
              {library.length === 1 ? "title" : "titles"} — recommendations use it
              and skip what you have already marked.
            </p>
          )}
          {error && <p className="error">{error}</p>}
        </section>

        <section className="results">
          {personalized && results.length > 0 && (
            <p className="personal-note">Shaped by your library.</p>
          )}
          {results.map((r) => (
            <article key={r.item.id} className="card">
              {r.item.image ? (
                <img className="poster" src={r.item.image} alt="" loading="lazy" />
              ) : (
                <div className="poster poster-blank">{MEDIUM_LABEL[r.item.medium]}</div>
              )}
              <div className="card-body">
                <div className="card-head">
                  <h3>{r.item.title}</h3>
                  <span className="badge">
                    {MEDIUM_LABEL[r.item.medium]}
                    {r.item.year ? ` · ${r.item.year}` : ""}
                  </span>
                </div>
                <div className="meta">
                  <span className="match">{Math.round(r.score * 100)}% match</span>
                  {r.item.rating != null && <span> · {r.item.rating.toFixed(1)}/10</span>}
                </div>
                {r.item.genres.length > 0 && <p className="genres">{r.item.genres.join(", ")}</p>}
                {r.reasons.length > 0 && <p className="why">{r.reasons.join(" · ")}</p>}
                {r.item.overview && <p className="overview">{r.item.overview}</p>}
                {session && (
                  <LibraryControls
                    item={r.item}
                    entry={library.find((e) => e.item.id === r.item.id)}
                    onChange={(entry) => applyEntry(r.item.id, entry)}
                  />
                )}
                <Offers item={r.item} />
              </div>
            </article>
          ))}
        </section>
        </>
        )}
      </div>
    </>
  );
}

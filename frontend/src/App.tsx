import { useEffect, useRef, useState } from "react";
import {
  recommend,
  searchTitles,
  type CatalogItem,
  type Medium,
  type Recommendation,
} from "./api";

const MEDIA: Medium[] = ["movie", "tv", "game", "book"];
const MEDIUM_LABEL: Record<Medium, string> = { movie: "Movie", tv: "TV", game: "Game", book: "Book" };

export default function App() {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<CatalogItem[]>([]);
  const [favorites, setFavorites] = useState<CatalogItem[]>([]);
  const [target, setTarget] = useState<"any" | Medium>("any");
  const [results, setResults] = useState<Recommendation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const debounce = useRef<number | undefined>(undefined);

  // Search-as-you-type (debounced).
  useEffect(() => {
    if (!query.trim()) {
      setSuggestions([]);
      return;
    }
    window.clearTimeout(debounce.current);
    debounce.current = window.setTimeout(() => {
      searchTitles(query.trim())
        .then((items) => setSuggestions(items.filter((i) => !favorites.some((f) => f.id === i.id))))
        .catch(() => setSuggestions([]));
    }, 180);
    return () => window.clearTimeout(debounce.current);
  }, [query, favorites]);

  function addFavorite(item: CatalogItem) {
    setFavorites((f) => [...f, item]);
    setQuery("");
    setSuggestions([]);
  }
  function removeFavorite(id: string) {
    setFavorites((f) => f.filter((x) => x.id !== id));
  }

  async function getRecommendations() {
    setError(null);
    setLoading(true);
    try {
      const media = target === "any" ? null : [target];
      setResults(await recommend(favorites.map((f) => f.id), media));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>Tangent</h1>
        <p className="tag">Find your next favorite across movies, TV, games, and books.</p>
      </header>

      <section className="panel">
        <label className="lbl">Add favorites</label>
        <div className="search">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a movie, show, game, or book..."
          />
          {suggestions.length > 0 && (
            <ul className="suggest">
              {suggestions.map((s) => (
                <li key={s.id} onClick={() => addFavorite(s)}>
                  <span>{s.title}</span>
                  <span className="badge">{MEDIUM_LABEL[s.medium]}{s.year ? ` · ${s.year}` : ""}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {favorites.length > 0 && (
          <div className="chips">
            {favorites.map((f) => (
              <span key={f.id} className="chip">
                {f.title}
                <button onClick={() => removeFavorite(f.id)} aria-label="remove">x</button>
              </span>
            ))}
          </div>
        )}

        <div className="controls">
          <label className="lbl">Recommend</label>
          <select value={target} onChange={(e) => setTarget(e.target.value as "any" | Medium)}>
            <option value="any">Anything (cross-media)</option>
            {MEDIA.map((m) => (
              <option key={m} value={m}>{MEDIUM_LABEL[m]}s</option>
            ))}
          </select>
          <button className="go" disabled={!favorites.length || loading} onClick={getRecommendations}>
            {loading ? "Thinking..." : "Get recommendations"}
          </button>
        </div>
        {error && <p className="error">{error}</p>}
      </section>

      <section className="results">
        {results.map((r) => (
          <article key={r.item.id} className="card">
            <div className="card-head">
              <h3>{r.item.title}</h3>
              <span className="badge">{MEDIUM_LABEL[r.item.medium]}{r.item.year ? ` · ${r.item.year}` : ""}</span>
            </div>
            <div className="meta">
              <span className="match">{Math.round(r.score * 100)}% match</span>
              {r.item.rating != null && <span> · {r.item.rating.toFixed(1)}/10</span>}
            </div>
            {r.item.genres.length > 0 && <p className="genres">{r.item.genres.join(", ")}</p>}
            {r.reasons.length > 0 && <p className="why">{r.reasons.join(" · ")}</p>}
            {r.item.overview && <p className="overview">{r.item.overview}</p>}
          </article>
        ))}
      </section>
    </div>
  );
}

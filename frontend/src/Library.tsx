import { useMemo, useState } from "react";
import LibraryControls from "./LibraryControls";
import type { LibraryEntry, LibraryStatus, Medium } from "./api";

const MEDIUM_LABEL: Record<Medium, string> = {
  movie: "Movie",
  tv: "TV",
  game: "Game",
  book: "Book",
};

type Filter = "all" | LibraryStatus;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "want", label: "Want" },
  { value: "in_progress", label: "Watching" },
  { value: "finished", label: "Finished" },
];

/**
 * Everything you have saved.
 *
 * Ordered by when you last touched an entry rather than by title or rating:
 * the thing you just marked is the thing you are most likely looking for.
 */
export default function Library({
  entries,
  onChange,
}: {
  entries: LibraryEntry[];
  onChange: (itemId: string, entry: LibraryEntry | null) => void;
}) {
  const [filter, setFilter] = useState<Filter>("all");

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: entries.length, want: 0, in_progress: 0, finished: 0 };
    for (const e of entries) c[e.status] += 1;
    return c;
  }, [entries]);

  const shown = useMemo(
    () => (filter === "all" ? entries : entries.filter((e) => e.status === filter)),
    [entries, filter],
  );

  if (entries.length === 0) {
    return (
      <section className="panel lib-empty">
        <p>Nothing saved yet.</p>
        <p className="hint">
          Mark anything from your recommendations as want, watching or finished, and it
          shows up here. Ratings you give here steer what gets recommended next.
        </p>
      </section>
    );
  }

  return (
    <>
      <div className="lib-filters">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            className={`gchip${filter === f.value ? " on" : ""}`}
            onClick={() => setFilter(f.value)}
            aria-pressed={filter === f.value}
            /* A filter that would show nothing is disabled rather than hidden,
               so the set of options stays stable as you mark things. */
            disabled={counts[f.value] === 0 && f.value !== "all"}
          >
            {f.label}
            <span className="gcount">{counts[f.value]}</span>
          </button>
        ))}
      </div>

      <section className="results">
        {shown.map((e) => (
          <article key={e.item.id} className="card">
            {e.item.image ? (
              <img className="poster" src={e.item.image} alt="" loading="lazy" />
            ) : (
              <div className="poster poster-blank">{MEDIUM_LABEL[e.item.medium]}</div>
            )}
            <div className="card-body">
              <div className="card-head">
                <h3>{e.item.title}</h3>
                <span className="badge">
                  {MEDIUM_LABEL[e.item.medium]}
                  {e.item.year ? ` · ${e.item.year}` : ""}
                </span>
              </div>
              <div className="meta">
                {/* Your score, not the catalog's — labelled, because a card
                    elsewhere shows the catalog's rating in the same spot. */}
                {e.rating !== null ? (
                  <span className="match">You rated {e.rating.toFixed(1)}</span>
                ) : (
                  <span>{FILTERS.find((f) => f.value === e.status)?.label}</span>
                )}
                {e.item.rating != null && <span> · catalog {e.item.rating.toFixed(1)}/10</span>}
              </div>
              {e.item.genres.length > 0 && <p className="genres">{e.item.genres.join(", ")}</p>}
              <LibraryControls
                item={e.item}
                entry={e}
                onChange={(next) => onChange(e.item.id, next)}
              />
            </div>
          </article>
        ))}
      </section>
    </>
  );
}

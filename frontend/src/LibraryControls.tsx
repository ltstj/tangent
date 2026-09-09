import { useState } from "react";
import {
  removeLibraryEntry,
  setLibraryEntry,
  type CatalogItem,
  type LibraryEntry,
  type LibraryStatus,
} from "./api";

const STATUSES: { value: LibraryStatus; label: string }[] = [
  { value: "want", label: "Want" },
  { value: "in_progress", label: "Watching" },
  { value: "finished", label: "Finished" },
];

/**
 * Mark one title, and rate it once finished.
 *
 * The rating only appears for `finished`, per ROADMAP's "rate on finish" — a
 * score for something you haven't seen isn't feedback. Ratings run 0–10 to match
 * the catalog's own scale, and 5 is neutral: the recommender treats above-5 as a
 * pull and below-5 as a push, so the midpoint genuinely means "no opinion".
 */
export default function LibraryControls({
  item,
  entry,
  onChange,
}: {
  item: CatalogItem;
  entry: LibraryEntry | undefined;
  onChange: (entry: LibraryEntry | null) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function mark(status: LibraryStatus) {
    setBusy(true);
    try {
      // Clicking the active status clears the entry, so a misclick is undoable.
      if (entry?.status === status) {
        await removeLibraryEntry(item.id);
        onChange(null);
      } else {
        onChange(await setLibraryEntry(item.id, status, entry?.rating ?? null));
      }
    } finally {
      setBusy(false);
    }
  }

  async function rate(value: number) {
    setBusy(true);
    try {
      onChange(await setLibraryEntry(item.id, entry?.status ?? "finished", value));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="lib">
      <div className="lib-row">
        {STATUSES.map((s) => (
          <button
            key={s.value}
            className={`lib-btn${entry?.status === s.value ? " on" : ""}`}
            onClick={() => mark(s.value)}
            disabled={busy}
            aria-pressed={entry?.status === s.value}
            title={entry?.status === s.value ? "Click again to remove" : undefined}
          >
            {s.label}
          </button>
        ))}
      </div>

      {entry?.status === "finished" && (
        <div className="lib-rate">
          <input
            type="range"
            min={0}
            max={10}
            step={0.5}
            value={entry.rating ?? 5}
            onChange={(e) => rate(Number(e.target.value))}
            disabled={busy}
            aria-label={`Your rating for ${item.title}`}
          />
          <span className="lib-score">
            {entry.rating === null ? "—" : entry.rating.toFixed(1)}
          </span>
          {/* Say what the number does, so 5 doesn't look like a bad score. */}
          <span className="lib-hint">
            {entry.rating === null || entry.rating === 5
              ? "5 = no opinion"
              : entry.rating > 5
                ? "more like this"
                : "less like this"}
          </span>
        </div>
      )}
    </div>
  );
}

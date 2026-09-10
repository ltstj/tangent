import { useState } from "react";
import { clearFeedback, setFeedback } from "./api";

/**
 * "Was this a good match?" — a verdict on the *suggestion*, not the title.
 *
 * Deliberately separate from the library's rating. "I liked this show" and "this
 * was a good answer to 'give me something like Blade Runner'" are different
 * claims, and only the second says whether the matching is working. A thumbs
 * down hides the suggestion rather than marking the title disliked.
 */
export default function MatchFeedback({
  itemId,
  sourceIds,
  current,
  onChange,
}: {
  itemId: string;
  sourceIds: string[];
  current: boolean | undefined;
  onChange: (helpful: boolean | undefined) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function vote(helpful: boolean) {
    setBusy(true);
    try {
      // Clicking the active verdict clears it, so a misclick is undoable.
      if (current === helpful) {
        await clearFeedback(itemId);
        onChange(undefined);
      } else {
        await setFeedback(itemId, helpful, sourceIds);
        onChange(helpful);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mfb">
      <span className="mfb-q">Good match?</span>
      <button
        className={`mfb-btn${current === true ? " on-up" : ""}`}
        onClick={() => vote(true)}
        disabled={busy}
        aria-pressed={current === true}
        title="Good suggestion"
      >
        ↑
      </button>
      <button
        className={`mfb-btn${current === false ? " on-down" : ""}`}
        onClick={() => vote(false)}
        disabled={busy}
        aria-pressed={current === false}
        title="Not what I was after — hide this suggestion"
      >
        ↓
      </button>
      {current === false && <span className="mfb-note">hidden next time</span>}
    </div>
  );
}

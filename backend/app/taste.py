"""Turning a library into taste weights.

ROADMAP.md: "Feedback feeds the personal taste vector (likes pull, dislikes
push)." This module is the mapping from what someone recorded to how much it
should pull - and in which direction.

The rating scale is 0-10 with 5 as neutral, so a rating becomes a signed weight
around that midpoint: 10 pulls hardest, 5 says nothing, 0 pushes hardest. An
entry with no rating still carries intent - marking something *want* is a
statement about taste even before you have seen it - so status supplies a
smaller positive weight.
"""
from __future__ import annotations

# Unrated entries: intent, weighted below anything explicitly rated. Finishing
# something says more than wanting it.
_STATUS_WEIGHT = {"finished": 0.5, "in_progress": 0.4, "want": 0.3}

NEUTRAL_RATING = 5.0


def weight_for(status: str, rating: float | None) -> float:
    """Signed pull for one library entry. Negative pushes away."""
    if rating is not None:
        # 10 -> +1.0, 5 -> 0.0, 0 -> -1.0
        return (float(rating) - NEUTRAL_RATING) / NEUTRAL_RATING
    return _STATUS_WEIGHT.get(status, 0.0)


def weights_from_library(rows: list[dict]) -> dict[str, float]:
    """Library rows -> {item_id: signed weight}, dropping the ones that say
    nothing (a rating of exactly 5 is a shrug, not a signal)."""
    out: dict[str, float] = {}
    for row in rows:
        item_id = row.get("lib_item_id") or row.get("item_id")
        if not item_id:
            continue
        w = weight_for(row.get("lib_status") or row.get("status") or "want",
                       row.get("lib_rating") if "lib_rating" in row else row.get("rating"))
        if abs(w) > 1e-9:
            out[item_id] = w
    return out


# A rejected *match* is not a disliked *title*: "that was a bad answer to my
# question" says nothing about whether the thing is good. So a thumbs-down
# suppresses that suggestion for that person rather than pushing their taste
# vector away from it - pushing would mislearn from a verdict about a pairing.
#
# A thumbs-up is weighted well below a real rating for the mirror-image reason:
# "good suggestion" is weaker evidence about taste than "I finished this and
# rated it 9".
MATCH_UP_WEIGHT = 0.35


def from_match_feedback(rows: list[dict]) -> tuple[dict[str, float], set[str]]:
    """Feedback rows -> (weights to add, ids to suppress)."""
    weights: dict[str, float] = {}
    suppress: set[str] = set()
    for row in rows:
        item_id = row.get("item_id")
        if not item_id:
            continue
        if row.get("helpful"):
            weights[item_id] = MATCH_UP_WEIGHT
        else:
            suppress.add(item_id)
    return weights, suppress

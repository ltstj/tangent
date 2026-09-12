"""Item-item collaborative filtering.

ROADMAP.md Phase 5: "people whose favorites overlap with yours also loved X",
blended in as data grows. Content-based scoring answers "what is this like?";
this answers "who else liked both?", which catches pairings no amount of genre
or synopsis similarity would - a cult film and an unrelated-looking game that
the same people love.

Two thresholds exist for privacy rather than for accuracy, and they matter most
exactly when the app is small:

- **MIN_USERS**: below this many contributing accounts, collaborative filtering
  is off entirely. With two users, "people who liked X also liked Y" is not an
  aggregate - it is a readout of the other person's library.
- **MIN_PAIR_USERS**: a pair of titles must be liked together by at least this
  many people before it can influence anything, so no single person's taste can
  move a recommendation on its own.

Neither threshold protects against a determined attacker with many accounts;
they are here so the ordinary behaviour of a small instance does not leak.

The weight also ramps with data volume (see confidence), which is what the
roadmap means by "content-based early, weighting in collaborative filtering as
data grows": early signals are noise, and should count like noise.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

MIN_USERS = 5
MIN_PAIR_USERS = 3
# Distinct contributing users at which collaborative filtering reaches full
# weight, and the share of it that applies the moment it switches on.
#
# The floor exists because the first calibration had none, and the result was a
# feature that activated and then did nothing: with seven users a *perfect*
# co-occurrence signal contributed 0.047 against scores in the 1.2-1.4 range.
# Caution was already covered twice over - MIN_USERS gates the feature off and
# MIN_PAIR_USERS rejects thin pairs - so scaling a survivor of both down to near
# zero was a third layer that bought nothing and hid the signal entirely.
FULL_CONFIDENCE_USERS = 25
CONFIDENCE_FLOOR = 0.35


@dataclass
class CollabModel:
    """Item-item similarity over who liked what."""

    liked_by: dict[str, set[str]] = field(default_factory=dict)
    users: int = 0

    @property
    def confidence(self) -> float:
        """0 below MIN_USERS, then CONFIDENCE_FLOOR ramping to 1.0 at
        FULL_CONFIDENCE_USERS."""
        if self.users < MIN_USERS:
            return 0.0
        span = max(1, FULL_CONFIDENCE_USERS - MIN_USERS)
        progress = min(1.0, (self.users - MIN_USERS) / span)
        return CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * progress

    def similarity(self, a: str, b: str) -> float:
        """Cosine over the sets of users who liked each, or 0 if too few share both."""
        ua, ub = self.liked_by.get(a), self.liked_by.get(b)
        if not ua or not ub:
            return 0.0
        shared = len(ua & ub)
        if shared < MIN_PAIR_USERS:
            return 0.0
        return shared / math.sqrt(len(ua) * len(ub))

    def scores_for(self, liked_ids: list[str]) -> dict[str, float]:
        """Candidate item -> collaborative score, given what this person liked.

        Averaged over the seed items so someone with a large library does not
        get uniformly larger scores than someone with two.
        """
        if not liked_ids or self.confidence <= 0.0:
            return {}
        seeds = [i for i in liked_ids if i in self.liked_by]
        if not seeds:
            return {}
        out: dict[str, float] = defaultdict(float)
        seed_set = set(seeds)
        for seed in seeds:
            for candidate in self.liked_by:
                if candidate in seed_set:
                    continue
                sim = self.similarity(seed, candidate)
                if sim > 0.0:
                    out[candidate] += sim
        return {k: v / len(seeds) for k, v in out.items()}


def build(interactions: list[tuple[str, str, float]]) -> CollabModel:
    """(user_id, item_id, weight) -> CollabModel. Pure.

    Only positive interactions build the co-occurrence sets. A shared dislike is
    a real signal but a different one, and treating "we both hated it" as "we
    have taste in common" is how you get recommended more of what you avoided.
    """
    liked_by: dict[str, set[str]] = defaultdict(set)
    users: set[str] = set()
    for user_id, item_id, weight in interactions:
        if weight <= 0.0:
            continue
        liked_by[item_id].add(user_id)
        users.add(user_id)
    return CollabModel(liked_by=dict(liked_by), users=len(users))

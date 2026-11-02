"""Does a paper cover a topic? Judged from how well its best passage matches the request.

The cut-offs come from the retrieval evaluation (docs/superpowers/results/2026-11-03-retrieval-evaluation.md):
passages answering a question scored 0.62-0.85 (median about 0.75) while questions the paper cannot answer still
reached 0.59-0.73, so no value separates them cleanly. These lean toward "not fully covered", as the design asks;
the middle band lets the person choose.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from retrieval.evidence import Evidence

COVERED_AT = 0.75
ABSENT_BELOW = 0.60

Level = Literal["covered", "weak", "absent"]


@dataclass(frozen=True)
class Coverage:
    level: Level
    best_similarity: float | None


def assess_coverage(evidence: Sequence[Evidence]) -> Coverage:
    similarities = [item.vector_similarity for item in evidence if item.vector_similarity is not None]
    if not similarities:
        return Coverage("absent", None)
    best = max(similarities)
    if best >= COVERED_AT:
        return Coverage("covered", best)
    if best >= ABSENT_BELOW:
        return Coverage("weak", best)
    return Coverage("absent", best)

"""Reciprocal rank fusion: merge several ranked lists using only the rank positions.

Raw scores from different searches (cosine similarity, text-search rank) are not
comparable, so they are never added together; each list only says "this came 1st, 2nd...".
"""

from __future__ import annotations

from typing import Sequence


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Each item scores the sum over rankings of 1 / (k + rank), ranks starting at 1.

    A repeated item inside one ranking counts once, at its best position. Returns
    (item, score) best first; ties keep the order in which items were first seen.
    """
    if k < 1:
        raise ValueError("k must be at least 1")

    scores: dict[str, float] = {}          # insertion order = first-seen order
    for ranking in rankings:
        seen: set[str] = set()
        rank = 0
        for item in ranking:
            if item in seen:
                continue
            seen.add(item)
            rank += 1
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)

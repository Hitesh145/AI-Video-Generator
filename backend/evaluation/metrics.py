"""Scoring for the retrieval evaluation. Pure functions, no I/O."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Sequence

# Hyphens and dashes of every kind, and the minus sign, all read as word breaks:
# PDF text mixes "multi-head", "multi‐head" and "multi-\nhead" for the same words.
_DASHES = "-‐‑‒–—―−"
_SOFT_HYPHEN = "­"


def normalize(text: str) -> str:
    """Lower-case, fold ligatures ("ﬁ" -> "fi"), drop soft hyphens, treat dashes as spaces, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).replace(_SOFT_HYPHEN, "")
    text = "".join(" " if character in _DASHES else character for character in text)
    return " ".join(text.casefold().split())


def is_relevant(passage_text: str, phrases: Sequence[str]) -> bool:
    """True when the passage contains any of the phrases (after normalising both). Blank phrases never match."""
    passage = normalize(passage_text)
    for phrase in phrases:
        wanted = normalize(phrase)
        if wanted and wanted in passage:
            return True
    return False


def first_relevant_rank(passage_texts: Sequence[str], phrases: Sequence[str]) -> int | None:
    """1-based position of the first relevant passage, or None."""
    for position, passage in enumerate(passage_texts, start=1):
        if is_relevant(passage, phrases):
            return position
    return None


def recall_at_k(ranks: Sequence[int | None], k: int) -> float:
    """Share of questions whose answer was found within the top k results."""
    if not ranks:
        return 0.0
    return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float:
    if not ranks:
        return 0.0
    return sum(1.0 / rank for rank in ranks if rank is not None) / len(ranks)


@dataclass(frozen=True)
class ThresholdSuggestion:
    threshold: float          # a topic counts as covered when its best score is >= threshold
    accuracy: float           # share of the given questions this cut-off classifies correctly


def suggest_threshold(
    answerable_scores: Sequence[float], absent_scores: Sequence[float]
) -> ThresholdSuggestion | None:
    """The cut-off that best separates questions the paper answers from ones it cannot answer.

    Candidates are the points halfway between neighbouring observed scores (plus one below and one above
    all of them), so the answer sits between the groups, not on one question's score. Ties choose the lower one.
    """
    if not answerable_scores or not absent_scores:
        return None
    distinct = sorted(set(answerable_scores) | set(absent_scores))
    candidates = [distinct[0] - 1e-9]
    candidates += [(low + high) / 2 for low, high in zip(distinct, distinct[1:])]
    candidates.append(distinct[-1] + 1e-9)

    total = len(answerable_scores) + len(absent_scores)
    best: ThresholdSuggestion | None = None
    for threshold in candidates:
        correct = sum(1 for score in answerable_scores if score >= threshold)
        correct += sum(1 for score in absent_scores if score < threshold)
        accuracy = correct / total
        if best is None or accuracy > best.accuracy:
            best = ThresholdSuggestion(threshold=threshold, accuracy=accuracy)
    return best

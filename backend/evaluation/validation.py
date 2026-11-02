"""Guard against typos in question files: every expected phrase must really occur in the paper."""

from __future__ import annotations

from collections.abc import Sequence

from evaluation.metrics import normalize
from evaluation.questions import QuestionSet


def find_problems(question_set: QuestionSet, passages: Sequence[str]) -> list[str]:
    """One message per answer phrase that no single stored passage contains (absent questions have none).

    Scoring looks inside one passage at a time, so a phrase split across a passage boundary is a problem too.
    """
    haystacks = [normalize(passage) for passage in passages]
    problems = []
    for question in question_set.questions:
        if question.kind != "answerable":
            continue
        for phrase in question.answer_phrases:
            needle = normalize(phrase)
            if not any(needle in haystack for haystack in haystacks):
                problems.append(f"{question.id}: the phrase {phrase!r} does not occur in any single passage of the paper")
    return problems

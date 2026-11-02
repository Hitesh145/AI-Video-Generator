"""Guard against typos in question files: every expected phrase must really occur in the paper."""

from __future__ import annotations

from evaluation.metrics import normalize
from evaluation.questions import QuestionSet


def find_problems(question_set: QuestionSet, paper_text: str) -> list[str]:
    """One message per answer phrase that is not in the paper's text (absent questions have none)."""
    haystack = normalize(paper_text)
    problems = []
    for question in question_set.questions:
        if question.kind != "answerable":
            continue
        for phrase in question.answer_phrases:
            if normalize(phrase) not in haystack:
                problems.append(f"{question.id}: the phrase {phrase!r} does not occur in the paper")
    return problems

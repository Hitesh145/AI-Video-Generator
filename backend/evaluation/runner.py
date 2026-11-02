"""Compare the search modes on a paper's questions and report how well each finds the answer."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Sequence

from evaluation.metrics import (
    ThresholdSuggestion,
    first_relevant_rank,
    mean_reciprocal_rank,
    recall_at_k,
    suggest_threshold,
)
from evaluation.questions import QuestionSet
from retrieval.evidence import Evidence


@dataclass(frozen=True)
class QuestionResult:
    question_id: str
    question: str
    kind: str
    category: str
    rank_by_mode: dict[str, int | None]            # rank of the first relevant passage (answerable questions only)
    best_score_by_mode: dict[str, float | None]    # how strongly the best passage matches (see coverage_score)


@dataclass(frozen=True)
class ModeSummary:
    mode: str
    recall_at: dict[int, float]
    mrr: float
    recall_by_category: dict[str, float]            # recall at `category_k`


@dataclass(frozen=True)
class EvaluationResult:
    paper: str
    answerable_count: int
    absent_count: int
    category_k: int
    k_values: tuple[int, ...]
    summaries: list[ModeSummary]
    questions: list[QuestionResult]
    threshold_by_mode: dict[str, ThresholdSuggestion | None]


def coverage_score(evidence: Sequence[Evidence], mode: str) -> float | None:
    """How strongly the best passage matches the question, as a number comparable across questions.

    Vector and hybrid searches use the best cosine similarity (a hybrid search's own score only
    reflects rank positions, so it cannot tell a covered topic from an uncovered one); keyword search
    uses its text-search rank. None when nothing was found.
    """
    if not evidence:
        return None
    if mode == "keyword":
        return evidence[0].score
    similarities = [item.vector_similarity for item in evidence if item.vector_similarity is not None]
    return max(similarities) if similarities else None


def evaluate(
    searcher,
    user_id: str,
    document_id: str,
    question_set: QuestionSet,
    modes: Sequence[str] = ("vector", "keyword", "hybrid"),
    k_values: Sequence[int] = (1, 3, 5, 8),
) -> EvaluationResult:
    k_values = tuple(sorted(set(k_values)))
    depth = max(k_values)
    category_k = 5 if 5 in k_values else depth

    results: list[QuestionResult] = []
    for question in question_set.questions:
        ranks: dict[str, int | None] = {}
        scores: dict[str, float | None] = {}
        for mode in modes:
            evidence = searcher.search(user_id, document_id, question.question, k=depth, mode=mode)
            scores[mode] = coverage_score(evidence, mode)
            ranks[mode] = (
                first_relevant_rank([item.text for item in evidence], question.answer_phrases)
                if question.kind == "answerable" else None
            )
        results.append(QuestionResult(question.id, question.question, question.kind, question.category, ranks, scores))

    answerable = [item for item in results if item.kind == "answerable"]
    absent = [item for item in results if item.kind == "absent"]

    summaries = []
    thresholds: dict[str, ThresholdSuggestion | None] = {}
    for mode in modes:
        ranks = [item.rank_by_mode[mode] for item in answerable]
        by_category: dict[str, list[int | None]] = {}
        for item in answerable:
            by_category.setdefault(item.category, []).append(item.rank_by_mode[mode])
        summaries.append(ModeSummary(
            mode=mode,
            recall_at={k: recall_at_k(ranks, k) for k in k_values},
            mrr=mean_reciprocal_rank(ranks),
            recall_by_category={category: recall_at_k(values, category_k) for category, values in by_category.items()},
        ))
        thresholds[mode] = suggest_threshold(
            [item.best_score_by_mode[mode] or 0.0 for item in answerable],
            [item.best_score_by_mode[mode] or 0.0 for item in absent],
        )

    return EvaluationResult(
        paper=question_set.paper, answerable_count=len(answerable), absent_count=len(absent),
        category_k=category_k, k_values=k_values, summaries=summaries, questions=results,
        threshold_by_mode=thresholds,
    )


def _range(values: list[float]) -> str:
    if not values:
        return "n/a"
    return f"{min(values):.2f} / {statistics.median(values):.2f} / {max(values):.2f}"


def render_markdown(results: Sequence[EvaluationResult]) -> str:
    lines = ["# Retrieval evaluation", ""]
    for result in results:
        modes = [summary.mode for summary in result.summaries]
        lines += [
            f"## {result.paper}",
            "",
            f"{result.answerable_count} answerable questions, {result.absent_count} that the paper cannot answer.",
            "",
            "| mode | " + " | ".join(f"recall@{k}" for k in result.k_values) + " | MRR |",
            "|---|" + "---|" * (len(result.k_values) + 1),
        ]
        for summary in result.summaries:
            cells = " | ".join(f"{summary.recall_at[k]:.2f}" for k in result.k_values)
            lines.append(f"| {summary.mode} | {cells} | {summary.mrr:.2f} |")

        categories = sorted({category for s in result.summaries for category in s.recall_by_category})
        if categories:
            lines += ["", f"Recall@{result.category_k} by question category:", "",
                      "| category | " + " | ".join(modes) + " |", "|---|" + "---|" * len(modes)]
            for category in categories:
                cells = " | ".join(f"{s.recall_by_category.get(category, 0.0):.2f}" for s in result.summaries)
                lines.append(f"| {category} | {cells} |")

        answerable = [q for q in result.questions if q.kind == "answerable"]
        absent = [q for q in result.questions if q.kind == "absent"]
        lines += ["", "How strongly the best passage matches (min / median / max), and the suggested "
                      "\"covered by the paper\" threshold:", "",
                  "| mode | answerable questions | questions the paper cannot answer | suggested threshold | accuracy |",
                  "|---|---|---|---|---|"]
        for mode in modes:
            suggestion = result.threshold_by_mode.get(mode)
            threshold = f"{suggestion.threshold:.3f}" if suggestion else "n/a"
            accuracy = f"{suggestion.accuracy:.2f}" if suggestion else "n/a"
            lines.append(
                f"| {mode} | {_range([q.best_score_by_mode[mode] or 0.0 for q in answerable])} "
                f"| {_range([q.best_score_by_mode[mode] or 0.0 for q in absent])} | {threshold} | {accuracy} |"
            )

        missed = [q for q in answerable if all(rank is None for rank in q.rank_by_mode.values())]
        lines += ["", f"Answerable questions no mode found in the top {max(result.k_values)}:", ""]
        lines += [f"- {q.question_id} ({q.category}): {q.question}" for q in missed] or ["- none"]
        lines.append("")
    return "\n".join(lines)

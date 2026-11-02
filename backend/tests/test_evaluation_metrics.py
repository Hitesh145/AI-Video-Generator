import pytest

from evaluation.metrics import (
    first_relevant_rank,
    is_relevant,
    mean_reciprocal_rank,
    normalize,
    recall_at_k,
    suggest_threshold,
)


LIGATURE_FI = chr(0xFB01)        # "fi" ligature, common in PDF text
HYPHEN = chr(0x2010)             # Unicode hyphen
SOFT_HYPHEN = chr(0x00AD)
MINUS = chr(0x2212)
NEWLINE = chr(10)


def test_normalize_handles_ligatures_hyphens_case_and_whitespace():
    assert normalize(f"The  {LIGATURE_FI}rst   Self{HYPHEN}Attention{NEWLINE}Layer") == normalize("the first self-attention layer")
    assert normalize(f"multi-{SOFT_HYPHEN}head") == normalize("multi-head")
    assert normalize(f"multi-{NEWLINE}head attention") == normalize("multi-head attention")
    assert normalize(f"A {MINUS} B") == normalize("a - b")


def test_is_relevant_matches_any_phrase_case_insensitively():
    assert is_relevant("We use Multi-Head Attention with h = 8", ["multi-head attention"])
    assert not is_relevant("We use recurrence", ["multi-head attention", "attention heads"])
    assert is_relevant("We use recurrence", ["multi-head attention", "recurrence"])


def test_a_blank_phrase_never_matches():
    assert not is_relevant("any text at all", ["", "   "])


def test_first_relevant_rank_is_one_based_or_none():
    assert first_relevant_rank(["a", "needle here", "b"], ["needle"]) == 2
    assert first_relevant_rank(["a", "b"], ["needle"]) is None
    assert first_relevant_rank([], ["needle"]) is None


def test_recall_at_k_counts_ranks_within_k():
    assert recall_at_k([1, 3, None, 5], 3) == pytest.approx(0.5)
    assert recall_at_k([], 3) == 0.0


def test_mrr_averages_reciprocal_ranks_and_scores_misses_zero():
    assert mean_reciprocal_rank([1, 2, None]) == pytest.approx((1 + 0.5 + 0) / 3)
    assert mean_reciprocal_rank([]) == 0.0


def test_suggest_threshold_separates_the_groups():
    suggestion = suggest_threshold([0.8, 0.7, 0.9], [0.3, 0.4, 0.2])

    assert 0.4 < suggestion.threshold <= 0.7
    assert suggestion.accuracy == 1.0


def test_suggest_threshold_reports_the_best_achievable_accuracy_when_groups_overlap():
    suggestion = suggest_threshold([0.8, 0.5, 0.45], [0.6, 0.4, 0.1])

    assert 0.5 < suggestion.accuracy < 1.0


def test_suggest_threshold_needs_both_groups():
    assert suggest_threshold([], [0.1]) is None
    assert suggest_threshold([0.9], []) is None


def test_suggest_threshold_ties_choose_the_lower_cutoff():
    # identical scores in both groups: cutting just below or just above is equally (in)accurate; the lower wins
    suggestion = suggest_threshold([0.5], [0.5])

    assert suggestion.accuracy == pytest.approx(0.5)
    assert suggestion.threshold < 0.5

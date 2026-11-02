import pytest

from retrieval.fusion import reciprocal_rank_fusion


def test_an_item_found_by_both_rankings_beats_items_found_by_one():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["d", "b", "e"]])

    assert [item for item, _ in fused][0] == "b"


def test_scores_are_the_sum_of_one_over_k_plus_rank():
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60))

    assert fused["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_every_item_appears_exactly_once():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "a"], ["a"]])

    assert sorted(item for item, _ in fused) == ["a", "b", "c"]


def test_ties_keep_first_seen_order():
    assert [item for item, _ in reciprocal_rank_fusion([["x", "y"]], k=60)] == ["x", "y"]
    assert [item for item, _ in reciprocal_rank_fusion([["p"], ["q"]])] == ["p", "q"]


def test_empty_inputs_give_nothing():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_a_duplicate_inside_one_ranking_counts_once_at_its_best_rank():
    fused = dict(reciprocal_rank_fusion([["a", "a", "b"]]))

    assert fused["a"] == pytest.approx(1 / 61)


def test_k_must_be_positive():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)

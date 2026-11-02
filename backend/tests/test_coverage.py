from retrieval.coverage import ABSENT_BELOW, COVERED_AT, Coverage, assess_coverage
from retrieval.evidence import Evidence


def evidence(similarity):
    return Evidence(
        chunk_id="c", document_id="d", text="t", context_prefix="", section_path=[], page_start=1, page_end=1,
        methods=("vector",), score=1.0, vector_similarity=similarity,
    )


def test_a_strong_match_is_covered():
    assert assess_coverage([evidence(0.80)]) == Coverage("covered", 0.80)


def test_a_middling_match_is_weak():
    assert assess_coverage([evidence(0.70)]).level == "weak"


def test_a_poor_match_is_absent():
    assert assess_coverage([evidence(0.59)]).level == "absent"


def test_the_boundaries_lean_toward_the_more_cautious_side_below_and_inclusive_above():
    assert (COVERED_AT, ABSENT_BELOW) == (0.75, 0.60)
    assert assess_coverage([evidence(0.75)]).level == "covered"
    assert assess_coverage([evidence(0.60)]).level == "weak"
    assert assess_coverage([evidence(0.7499)]).level == "weak"
    assert assess_coverage([evidence(0.5999)]).level == "absent"


def test_the_best_of_several_passages_decides():
    assert assess_coverage([evidence(0.5), evidence(0.78), evidence(0.6)]) == Coverage("covered", 0.78)


def test_no_passages_is_absent_with_no_similarity():
    assert assess_coverage([]) == Coverage("absent", None)


def test_passages_without_a_vector_similarity_count_as_absent():
    assert assess_coverage([evidence(None), evidence(None)]) == Coverage("absent", None)

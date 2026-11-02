import pytest

from rag.storage_schema import KeywordHit, SimilarityHit
from retrieval.search import PaperSearcher


def vector_hit(chunk_id, distance, text=None):
    return SimilarityHit(
        chunk_id=chunk_id, document_id="d", title="T", source_filename="p.pdf",
        text=text or f"text of {chunk_id}", context_prefix="ctx", page_start=2, page_end=3,
        section_path=["Intro"], cosine_distance=distance,
    )


def keyword_hit(chunk_id, score):
    return KeywordHit(
        chunk_id=chunk_id, document_id="d", text=f"text of {chunk_id}", context_prefix="ctx",
        section_path=["Intro"], page_start=2, page_end=3, rank_score=score,
    )


class Fakes:
    """Two recording searches with canned results, plus the searcher built on them."""

    def __init__(self, vectors=None, keywords=None, keyword_error=None):
        self.vectors = vectors if vectors is not None else [vector_hit("c1", 0.1), vector_hit("c2", 0.3), vector_hit("c3", 0.5)]
        self.keywords = keywords if keywords is not None else [keyword_hit("c4", 0.9), keyword_hit("c2", 0.5), keyword_hit("c5", 0.1)]
        self.keyword_error = keyword_error
        self.vector_calls = []
        self.keyword_calls = []
        self.searcher = PaperSearcher(self._vector, self._keyword)

    def _vector(self, user_id, document_id, query, limit):
        self.vector_calls.append((user_id, document_id, query, limit))
        return list(self.vectors)

    def _keyword(self, user_id, document_id, query, limit):
        self.keyword_calls.append((user_id, document_id, query, limit))
        if self.keyword_error:
            raise self.keyword_error
        return list(self.keywords)


def test_vector_mode_orders_by_similarity_and_reports_it():
    fakes = Fakes()

    results = fakes.searcher.search("u", "d", "q", k=2, mode="vector")

    assert [e.chunk_id for e in results] == ["c1", "c2"]
    assert results[0].methods == ("vector",)
    assert results[0].vector_similarity == pytest.approx(0.9) and results[0].score == pytest.approx(0.9)
    assert (results[0].page_start, results[0].section_path) == (2, ["Intro"])
    assert fakes.keyword_calls == []


def test_keyword_mode_never_calls_the_vector_search():
    fakes = Fakes()

    results = fakes.searcher.search("u", "d", "q", mode="keyword")

    assert fakes.vector_calls == []
    assert [e.chunk_id for e in results] == ["c4", "c2", "c5"]
    assert all(e.methods == ("keyword",) and e.vector_similarity is None for e in results)
    assert results[0].score == pytest.approx(0.9)


def test_hybrid_merges_duplicates_and_records_both_methods():
    results = Fakes().searcher.search("u", "d", "q", mode="hybrid")

    shared = next(e for e in results if e.chunk_id == "c2")
    assert shared.methods == ("vector", "keyword") and shared.vector_similarity == pytest.approx(0.7)
    assert len({e.chunk_id for e in results}) == len(results)
    assert {e.chunk_id for e in results} == {"c1", "c2", "c3", "c4", "c5"}


def test_hybrid_puts_a_passage_found_by_both_above_ones_found_by_one():
    results = Fakes().searcher.search("u", "d", "q", mode="hybrid")

    assert results[0].chunk_id == "c2"                     # second in each list, but in both
    assert results[0].methods == ("vector", "keyword")
    assert results[0].score > results[1].score >= results[-1].score


def test_k_limits_the_results_and_is_clamped():
    searcher = Fakes().searcher

    assert len(searcher.search("u", "d", "q", k=1)) == 1
    assert len(searcher.search("u", "d", "q", k=0)) == 1
    assert len(searcher.search("u", "d", "q", k=999)) <= 50


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_a_blank_query_returns_nothing_and_calls_no_search(query):
    fakes = Fakes()

    assert fakes.searcher.search("u", "d", query) == []
    assert fakes.vector_calls == [] and fakes.keyword_calls == []


def test_the_callers_ids_are_passed_through_unchanged():
    fakes = Fakes()

    fakes.searcher.search("user-7", "doc-9", "what is attention?", mode="hybrid")

    assert fakes.vector_calls == [("user-7", "doc-9", "what is attention?", 20)]
    assert fakes.keyword_calls == [("user-7", "doc-9", "what is attention?", 20)]


def test_a_failing_keyword_search_does_not_hide_vector_results_in_hybrid_mode():
    fakes = Fakes(keyword_error=RuntimeError("full-text search is down"))

    results = fakes.searcher.search("u", "d", "q", mode="hybrid")

    assert [e.chunk_id for e in results] == ["c1", "c2", "c3"]
    assert all(e.methods == ("vector",) for e in results)


def test_a_failing_keyword_search_is_an_error_in_keyword_mode():
    fakes = Fakes(keyword_error=RuntimeError("full-text search is down"))

    with pytest.raises(RuntimeError):
        fakes.searcher.search("u", "d", "q", mode="keyword")


def test_an_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        Fakes().searcher.search("u", "d", "q", mode="semantic")

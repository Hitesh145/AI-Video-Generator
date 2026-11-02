"""Search inside one stored paper: by meaning, by words, or both merged by rank."""

from __future__ import annotations

import logging
from typing import Callable, Literal

from rag.storage_schema import KeywordHit, SimilarityHit
from retrieval.evidence import Evidence
from retrieval.fusion import reciprocal_rank_fusion

logger = logging.getLogger(__name__)

SearchMode = Literal["vector", "keyword", "hybrid"]
MODES = ("vector", "keyword", "hybrid")
MAX_RESULTS = 50

# Both searches take (user_id, document_id, query, limit): the caller's paper is always named.
VectorSearch = Callable[[str, str, str, int], list[SimilarityHit]]
KeywordSearch = Callable[[str, str, str, int], list[KeywordHit]]


class PaperSearcher:
    def __init__(
        self,
        vector_search: VectorSearch,
        keyword_search: KeywordSearch,
        candidates: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self.vector_search = vector_search
        self.keyword_search = keyword_search
        self.candidates = candidates
        self.rrf_k = rrf_k

    def search(
        self, user_id: str, document_id: str, query: str, k: int = 8, mode: SearchMode = "hybrid"
    ) -> list[Evidence]:
        if mode not in MODES:
            raise ValueError(f"Unknown search mode {mode!r}; use one of {MODES}")
        if not query.strip():
            return []
        k = max(1, min(MAX_RESULTS, k))

        if mode == "vector":
            return self._vector_only(self.vector_search(user_id, document_id, query, self.candidates))[:k]
        if mode == "keyword":
            return self._keyword_only(self.keyword_search(user_id, document_id, query, self.candidates))[:k]

        vectors = self.vector_search(user_id, document_id, query, self.candidates)
        try:
            keywords = self.keyword_search(user_id, document_id, query, self.candidates)
        except Exception:
            logger.warning("Keyword search failed; using vector results only", exc_info=True)
            keywords = []
        return self._hybrid(vectors, keywords)[:k]

    # ------------------------------------------------------------------ builders
    @staticmethod
    def _from_vector(hit: SimilarityHit, methods: tuple[str, ...], score: float) -> Evidence:
        return Evidence(
            chunk_id=hit.chunk_id, document_id=hit.document_id, text=hit.text,
            context_prefix=hit.context_prefix, section_path=list(hit.section_path),
            page_start=hit.page_start, page_end=hit.page_end, methods=methods, score=score,
            vector_similarity=hit.similarity_score,
        )

    @staticmethod
    def _from_keyword(hit: KeywordHit, methods: tuple[str, ...], score: float) -> Evidence:
        return Evidence(
            chunk_id=hit.chunk_id, document_id=hit.document_id, text=hit.text,
            context_prefix=hit.context_prefix, section_path=list(hit.section_path),
            page_start=hit.page_start, page_end=hit.page_end, methods=methods, score=score,
            vector_similarity=None,
        )

    def _vector_only(self, hits: list[SimilarityHit]) -> list[Evidence]:
        return [self._from_vector(hit, ("vector",), hit.similarity_score) for hit in hits]

    def _keyword_only(self, hits: list[KeywordHit]) -> list[Evidence]:
        return [self._from_keyword(hit, ("keyword",), hit.rank_score) for hit in hits]

    def _hybrid(self, vectors: list[SimilarityHit], keywords: list[KeywordHit]) -> list[Evidence]:
        vector_by_id = {hit.chunk_id: hit for hit in vectors}
        keyword_by_id = {hit.chunk_id: hit for hit in keywords}
        fused = reciprocal_rank_fusion(
            [[hit.chunk_id for hit in vectors], [hit.chunk_id for hit in keywords]], k=self.rrf_k
        )
        results = []
        for chunk_id, score in fused:
            in_vector, in_keyword = chunk_id in vector_by_id, chunk_id in keyword_by_id
            methods = tuple(name for name, found in (("vector", in_vector), ("keyword", in_keyword)) if found)
            if in_vector:
                results.append(self._from_vector(vector_by_id[chunk_id], methods, score))
            else:
                results.append(self._from_keyword(keyword_by_id[chunk_id], methods, score))
        return results


def build_paper_searcher(storage, repository, candidates: int = 20, rrf_k: int = 60) -> PaperSearcher:
    """Wire the searcher to the real services: Gemini-embedded vector search and PostgreSQL full-text search."""
    return PaperSearcher(
        vector_search=lambda user_id, document_id, query, limit: storage.search_similar(
            user_id, query, limit=limit, document_id=document_id
        ),
        keyword_search=repository.keyword_search,
        candidates=candidates,
        rrf_k=rrf_k,
    )

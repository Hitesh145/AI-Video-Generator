from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    """One retrieved passage of a paper, with where it came from and how it was found."""

    chunk_id: str
    document_id: str
    text: str
    context_prefix: str
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    methods: tuple[str, ...]            # which searches found it: "vector", "keyword"
    score: float                        # the value results are ordered by
    vector_similarity: float | None     # cosine similarity (1 - distance) when the vector search returned it

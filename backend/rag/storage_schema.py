"""Small provider-neutral result types shared by RAG storage components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PersistenceResult:
    document_id: str
    source_sha256: str
    already_exists: bool
    block_count: int
    chunk_count: int
    asset_count: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EmbeddingWorkItem:
    chunk_id: str
    formatted_text: str
    content_sha256: str


@dataclass(frozen=True)
class EmbeddingToStore:
    chunk_id: str
    content_sha256: str
    vector: list[float]


@dataclass(frozen=True)
class SimilarityHit:
    chunk_id: str
    document_id: str
    title: str | None
    source_filename: str
    text: str
    context_prefix: str
    page_start: int | None
    page_end: int | None
    section_path: list[str]
    cosine_distance: float

    @property
    def similarity_score(self) -> float:
        """Convert pgvector cosine distance to the corresponding 1-distance score."""
        return 1.0 - self.cosine_distance


@dataclass(frozen=True)
class StoredChunkInput:
    chunk_id: str
    title: str | None
    text: str
    context_prefix: str
    existing_embedding_hashes: frozenset[str]

    @property
    def retrieval_text(self) -> str:
        if self.context_prefix and self.text:
            return f"{self.context_prefix}\n\n{self.text}"
        return self.context_prefix or self.text

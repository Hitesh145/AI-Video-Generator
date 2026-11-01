"""Orchestration for canonical persistence, managed assets, and embeddings."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from rag.asset_store import AssetBundle, ManagedAssetStore, sha256_file
from rag.chunk_schema import CanonicalChunk
from rag.document_schema import NormalizedDocument
from rag.embedding_service import GeminiEmbeddingService
from rag.storage_config import EMBEDDING_DIMENSIONS, asset_root_from_env
from rag.storage_schema import EmbeddingToStore, EmbeddingWorkItem, PersistenceResult, SimilarityHit


class RAGRepository(Protocol):
    def find_document_by_sha256(self, source_sha256: str) -> str | None: ...

    def persist_bundle(
        self,
        document: NormalizedDocument,
        chunks: list[CanonicalChunk],
        source_sha256: str,
        asset_bundle: AssetBundle,
    ) -> tuple[str, bool]: ...

    def chunks_missing_embeddings(self, document_id: str, model_name: str) -> list[EmbeddingWorkItem]: ...

    def save_embeddings(self, model_name: str, embeddings: Sequence[EmbeddingToStore]) -> int: ...

    def search_similar(
        self, query_vector: Sequence[float], model_name: str, limit: int = 5
    ) -> list[SimilarityHit]: ...


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    def embed_prepared_text(self, formatted_text: str) -> list[float]: ...

    def embed_query(self, query: str) -> list[float]: ...


class RAGStorageService:
    """Persist one normalized PDF/chunk bundle and optionally build its vector index.

    Canonical content commits independently from embedding generation. If the
    remote embedding API fails, source content remains stored and embedding can be
    safely retried later without reparsing or duplicating the document.
    """

    def __init__(
        self,
        repository: RAGRepository,
        asset_store: ManagedAssetStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.repository = repository
        self.asset_store = asset_store or ManagedAssetStore(asset_root_from_env())
        self.embedding_provider = embedding_provider

    @classmethod
    def from_env(cls) -> "RAGStorageService":
        """Create PostgreSQL-backed storage from RAG_DATABASE_URL/DATABASE_URL."""
        from rag.database import build_engine, build_session_factory
        from rag.pg_repository import PostgresRAGRepository

        engine = build_engine()
        return cls(
            repository=PostgresRAGRepository(build_session_factory(engine)),
            asset_store=ManagedAssetStore(asset_root_from_env()),
        )

    def persist_document(
        self,
        source_pdf: str | Path,
        document: NormalizedDocument,
        chunks: list[CanonicalChunk],
    ) -> PersistenceResult:
        """Persist PDF metadata, normalized blocks, chunks and file assets idempotently."""
        source_path = Path(source_pdf).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Source PDF not found: {source_path}")
        self._validate_bundle(document, chunks)
        source_digest = sha256_file(source_path)

        existing_id = self.repository.find_document_by_sha256(source_digest)
        if existing_id:
            return PersistenceResult(
                document_id=existing_id,
                source_sha256=source_digest,
                already_exists=True,
                block_count=len(document.blocks),
                chunk_count=len(chunks),
                asset_count=0,
                warnings=("This exact PDF has already been stored; existing canonical records were reused.",),
            )

        asset_bundle = self.asset_store.store_bundle(source_path, document, source_digest)
        try:
            stored_document_id, created = self.repository.persist_bundle(
                document, chunks, source_digest, asset_bundle
            )
        except Exception:
            # A competing process may have stored this hash while assets were copied.
            # Do not delete files if a committed document now references the same hash.
            try:
                concurrent_id = self.repository.find_document_by_sha256(source_digest)
            except Exception:
                concurrent_id = None
            if not concurrent_id:
                self.asset_store.cleanup_created_files(asset_bundle)
            raise

        if not created:
            return PersistenceResult(
                document_id=stored_document_id,
                source_sha256=source_digest,
                already_exists=True,
                block_count=len(document.blocks),
                chunk_count=len(chunks),
                asset_count=0,
                warnings=tuple(asset_bundle.warnings),
            )
        return PersistenceResult(
            document_id=stored_document_id,
            source_sha256=source_digest,
            already_exists=False,
            block_count=len(document.blocks),
            chunk_count=len(chunks),
            asset_count=len(asset_bundle.assets),
            warnings=tuple(list(document.warnings) + asset_bundle.warnings),
        )

    def generate_missing_embeddings(self, document_id: str, batch_size: int = 8) -> int:
        """Embed not-yet-indexed text chunks; commits each batch for safe resumption."""
        if batch_size < 1 or batch_size > 128:
            raise ValueError("batch_size must be between 1 and 128")
        provider = self.embedding_provider or GeminiEmbeddingService()
        if provider.dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Storage schema uses {EMBEDDING_DIMENSIONS} dimensions, "
                f"but provider is configured for {provider.dimensions}."
            )
        work = self.repository.chunks_missing_embeddings(document_id, provider.model_name)
        inserted = 0
        for start in range(0, len(work), batch_size):
            batch_items = work[start : start + batch_size]
            embeddings: list[EmbeddingToStore] = []
            for item in batch_items:
                vector = provider.embed_prepared_text(item.formatted_text)
                if len(vector) != EMBEDDING_DIMENSIONS:
                    raise ValueError(
                        f"Provider returned {len(vector)} dimensions for chunk {item.chunk_id}; "
                        f"expected {EMBEDDING_DIMENSIONS}."
                    )
                embeddings.append(
                    EmbeddingToStore(
                        chunk_id=item.chunk_id,
                        content_sha256=item.content_sha256,
                        vector=list(vector),
                    )
                )
            inserted += self.repository.save_embeddings(provider.model_name, embeddings)
        return inserted

    def search_similar(self, query: str, limit: int = 5) -> list[SimilarityHit]:
        """Perform the Phase 3 vector-search smoke path; ranking/expansion is Phase 4."""
        provider = self.embedding_provider or GeminiEmbeddingService()
        if provider.dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Storage schema uses {EMBEDDING_DIMENSIONS} dimensions, "
                f"but provider is configured for {provider.dimensions}."
            )
        vector = provider.embed_query(query)
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError("Query embedding dimensions do not match the database schema.")
        return self.repository.search_similar(vector, provider.model_name, limit)

    @staticmethod
    def _validate_bundle(document: NormalizedDocument, chunks: list[CanonicalChunk]) -> None:
        block_ids = {block.block_id for block in document.blocks}
        if len(block_ids) != len(document.blocks):
            raise ValueError("Document contains duplicate block IDs.")
        seen_chunk_ids: set[str] = set()
        seen_sequences: set[int] = set()
        for chunk in chunks:
            if chunk.document_id != document.document_id:
                raise ValueError(
                    f"Chunk {chunk.chunk_id} belongs to {chunk.document_id}, "
                    f"not {document.document_id}."
                )
            if chunk.chunk_id in seen_chunk_ids:
                raise ValueError(f"Duplicate chunk ID: {chunk.chunk_id}")
            if chunk.sequence_index in seen_sequences:
                raise ValueError(f"Duplicate chunk sequence index: {chunk.sequence_index}")
            seen_chunk_ids.add(chunk.chunk_id)
            seen_sequences.add(chunk.sequence_index)
            missing = {ref.block_id for ref in chunk.source_refs} - block_ids
            missing.update(set(chunk.related_element_ids) - block_ids)
            if missing:
                raise ValueError(
                    f"Chunk {chunk.chunk_id} references blocks absent from the document: {sorted(missing)}"
                )

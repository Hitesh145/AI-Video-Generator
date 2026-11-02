"""PostgreSQL persistence and pgvector operations for the RAG pipeline."""

from __future__ import annotations

import hashlib
import re
from typing import Sequence
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from rag.asset_store import AssetBundle, canonical_source_path
from rag.db_models import (
    RAGChunkEmbedding,
    RAGChunkSourceBlock,
    RAGDocument,
    RAGDocumentAsset,
    RAGDocumentBlock,
    RAGDocumentChunk,
)
from rag.embedding_service import prepare_document_embedding_text
from rag.storage_config import EMBEDDING_DIMENSIONS
from rag.storage_schema import EmbeddingToStore, EmbeddingWorkItem, KeywordHit, SimilarityHit

# Words only (letters and digits in any script). Nothing else from a question ever reaches the tsquery.
_QUERY_WORD = re.compile(r"[^\W_]+")
MAX_QUERY_TERMS = 64
# Must match the expression of the GIN index ix_rag_chunks_fts (migration 0004) exactly.
PASSAGE_TSVECTOR = "to_tsvector('english', c.context_prefix || ' ' || c.text)"


class PostgresRAGRepository:
    """Persistence adapter; all SQLAlchemy sessions are scoped to one operation."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def find_document_by_sha256(self, user_id: str, source_sha256: str) -> str | None:
        with self._session_factory() as session:
            return session.scalar(
                select(RAGDocument.document_id).where(
                    RAGDocument.user_id == user_id, RAGDocument.source_sha256 == source_sha256
                )
            )

    def persist_bundle(
        self,
        user_id: str,
        document,
        chunks,
        source_sha256: str,
        asset_bundle: AssetBundle,
    ) -> tuple[str, bool]:
        """Atomically store canonical metadata, blocks, assets, chunks and source links.

        Returns ``(document_id, created)``. A repeated source PDF hash for the same
        user is treated as idempotent and returns the already stored document;
        another user's copy of the same PDF is a separate document.
        """
        with self._session_factory.begin() as session:
            existing_id = session.scalar(
                select(RAGDocument.document_id).where(
                    RAGDocument.user_id == user_id, RAGDocument.source_sha256 == source_sha256
                )
            )
            if existing_id:
                return str(existing_id), False

            row = RAGDocument(
                document_id=document.document_id,
                user_id=user_id,
                source_sha256=source_sha256,
                source_filename=document.source_filename,
                source_asset_key=asset_bundle.source_pdf_key,
                title=document.title,
                authors=list(document.authors),
                affiliations=list(document.affiliations),
                page_count=document.page_count,
                parser_name=document.parser_name,
                parser_version=document.parser_version,
                warnings=list(document.warnings) + list(asset_bundle.warnings),
            )
            session.add(row)
            session.flush()   # the models declare foreign keys but no relationships, so insert order is ours to enforce

            path_key_map = dict(asset_bundle.source_path_to_key)
            image_keys_by_block = dict(asset_bundle.image_keys_by_block_id)
            block_ids = {block.block_id for block in document.blocks}
            for chunk in chunks:
                if chunk.document_id != document.document_id:
                    raise ValueError(
                        f"Chunk {chunk.chunk_id} belongs to document {chunk.document_id}, "
                        f"not {document.document_id}."
                    )
                missing = {ref.block_id for ref in chunk.source_refs} - block_ids
                missing.update(set(chunk.related_element_ids) - block_ids)
                if missing:
                    raise ValueError(
                        f"Chunk {chunk.chunk_id} references missing source blocks: {sorted(missing)}"
                    )

            session.add_all(
                [
                    RAGDocumentBlock(
                        block_id=block.block_id,
                        document_id=document.document_id,
                        ordinal=block.ordinal,
                        block_type=block.block_type,
                        source_label=block.source_label,
                        text=block.text or "",
                        caption=block.caption,
                        page_number=block.page_number,
                        section_path=list(block.section_path),
                        heading_level=block.heading_level,
                        is_document_metadata=block.is_document_metadata,
                        block_metadata=dict(block.metadata),
                        image_asset_key=image_keys_by_block.get(block.block_id),
                        image_available=(
                            bool(image_keys_by_block.get(block.block_id))
                            if block.block_type == "figure" and block.image_available is not None
                            else block.image_available
                        ),
                    )
                    for block in document.blocks
                ]
            )

            session.flush()
            session.add_all(
                [
                    RAGDocumentAsset(
                        asset_id=str(uuid4()),
                        document_id=document.document_id,
                        asset_key=asset.asset_key,
                        asset_type=asset.asset_type,
                        sha256=asset.sha256,
                        mime_type=asset.mime_type,
                        size_bytes=asset.size_bytes,
                        page_number=asset.page_number,
                        source_block_id=asset.source_block_id,
                    )
                    for asset in asset_bundle.assets
                ]
            )

            session.flush()
            source_link_rows = []
            chunk_rows = []
            for chunk in chunks:
                image_keys = []
                for path in chunk.image_asset_paths:
                    key = path_key_map.get(canonical_source_path(path))
                    if key and key not in image_keys:
                        image_keys.append(key)
                retrieval_text = chunk.retrieval_text
                content_hash = hashlib.sha256(retrieval_text.encode("utf-8")).hexdigest()
                chunk_rows.append(
                    RAGDocumentChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=document.document_id,
                        sequence_index=chunk.sequence_index,
                        text=chunk.text,
                        context_prefix=chunk.context_prefix,
                        content_sha256=content_hash,
                        token_count_estimate=chunk.token_count_estimate,
                        section_id=chunk.section_id,
                        section_title=chunk.section_title,
                        section_path=list(chunk.section_path),
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        related_element_ids=list(chunk.related_element_ids),
                        image_asset_keys=image_keys,
                        previous_chunk_id=chunk.previous_chunk_id,
                        next_chunk_id=chunk.next_chunk_id,
                    )
                )
                seen_links: set[tuple[str, str]] = set()
                for position, source_ref in enumerate(chunk.source_refs):
                    link = (source_ref.block_id, "source")
                    if link not in seen_links:
                        source_link_rows.append(
                            RAGChunkSourceBlock(
                                chunk_id=chunk.chunk_id,
                                block_id=source_ref.block_id,
                                link_type="source",
                                source_position=position,
                            )
                        )
                        seen_links.add(link)
                for related_position, block_id in enumerate(chunk.related_element_ids):
                    link = (block_id, "related")
                    if link not in seen_links:
                        source_link_rows.append(
                            RAGChunkSourceBlock(
                                chunk_id=chunk.chunk_id,
                                block_id=block_id,
                                link_type="related",
                                source_position=related_position,
                            )
                        )
                        seen_links.add(link)

            session.add_all(chunk_rows)
            session.flush()
            session.add_all(source_link_rows)

        return document.document_id, True

    def chunks_missing_embeddings(self, document_id: str, model_name: str) -> list[EmbeddingWorkItem]:
        """Return chunks with no current embedding for their exact formatted input."""
        with self._session_factory() as session:
            document = session.get(RAGDocument, document_id)
            if document is None:
                raise ValueError(f"RAG document not found: {document_id}")
            chunks = session.scalars(
                select(RAGDocumentChunk)
                .where(RAGDocumentChunk.document_id == document_id)
                .order_by(RAGDocumentChunk.sequence_index)
            ).all()
            if not chunks:
                return []
            chunk_ids = [chunk.chunk_id for chunk in chunks]
            existing_rows = session.execute(
                select(RAGChunkEmbedding.chunk_id, RAGChunkEmbedding.content_sha256).where(
                    RAGChunkEmbedding.chunk_id.in_(chunk_ids),
                    RAGChunkEmbedding.model_name == model_name,
                )
            ).all()
            existing_by_chunk: dict[str, set[str]] = {}
            for chunk_id, content_hash in existing_rows:
                existing_by_chunk.setdefault(str(chunk_id), set()).add(str(content_hash))

            pending: list[EmbeddingWorkItem] = []
            for chunk in chunks:
                content = chunk.context_prefix
                if content and chunk.text:
                    content = f"{content}\n\n{chunk.text}"
                else:
                    content = content or chunk.text
                # Structural-only figures/empty headings are stored canonically,
                # but should not receive meaningless text embeddings.
                if not content.strip():
                    continue
                formatted = prepare_document_embedding_text(document.title, content)
                digest = hashlib.sha256(formatted.encode("utf-8")).hexdigest()
                if digest not in existing_by_chunk.get(chunk.chunk_id, set()):
                    pending.append(
                        EmbeddingWorkItem(
                            chunk_id=chunk.chunk_id,
                            formatted_text=formatted,
                            content_sha256=digest,
                        )
                    )
            return pending

    def save_embeddings(
        self,
        model_name: str,
        embeddings: Sequence[EmbeddingToStore],
    ) -> int:
        """Insert embeddings idempotently; duplicate chunk/model/content keys are ignored."""
        if not embeddings:
            return 0
        for item in embeddings:
            if len(item.vector) != EMBEDDING_DIMENSIONS:
                raise ValueError(
                    f"Embedding for chunk {item.chunk_id} has {len(item.vector)} dimensions; "
                    f"expected {EMBEDDING_DIMENSIONS}."
                )
        rows = [
            {
                "embedding_id": str(uuid4()),
                "chunk_id": item.chunk_id,
                "model_name": model_name,
                "dimensions": EMBEDDING_DIMENSIONS,
                "content_sha256": item.content_sha256,
                "embedding": item.vector,
            }
            for item in embeddings
        ]
        insert_statement = pg_insert(RAGChunkEmbedding).values(rows)
        statement = insert_statement.on_conflict_do_update(
            index_elements=["chunk_id", "model_name"],
            set_={
                "dimensions": insert_statement.excluded.dimensions,
                "content_sha256": insert_statement.excluded.content_sha256,
                "embedding": insert_statement.excluded.embedding,
                "created_at": func.now(),
            },
        )
        with self._session_factory.begin() as session:
            session.execute(statement)
        # An upsert inserts or updates every submitted row; rowcount is not reliable across drivers.
        return len(rows)

    def search_similar(
        self,
        user_id: str,
        query_vector: Sequence[float],
        model_name: str,
        limit: int = 5,
        document_id: str | None = None,
    ) -> list[SimilarityHit]:
        """Cosine-nearest-neighbor search over one user's papers, or one of their papers."""
        if len(query_vector) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Query vector has {len(query_vector)} dimensions; expected {EMBEDDING_DIMENSIONS}."
            )
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        distance = RAGChunkEmbedding.embedding.cosine_distance(list(query_vector)).label("cosine_distance")
        statement = (
            select(RAGDocumentChunk, RAGDocument, distance)
            .join(RAGChunkEmbedding, RAGChunkEmbedding.chunk_id == RAGDocumentChunk.chunk_id)
            .join(RAGDocument, RAGDocument.document_id == RAGDocumentChunk.document_id)
            .where(
                RAGDocument.user_id == user_id,
                RAGChunkEmbedding.model_name == model_name,
                RAGChunkEmbedding.dimensions == EMBEDDING_DIMENSIONS,
            )
            .order_by(distance)
            .limit(limit)
        )
        if document_id is not None:
            statement = statement.where(RAGDocument.document_id == document_id)
        with self._session_factory() as session:
            rows = session.execute(statement).all()
        return [
            SimilarityHit(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                title=document.title,
                source_filename=document.source_filename,
                text=chunk.text,
                context_prefix=chunk.context_prefix,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                section_path=list(chunk.section_path),
                cosine_distance=float(distance_value),
            )
            for chunk, document, distance_value in rows
        ]

    def keyword_search(self, user_id: str, document_id: str, query: str, limit: int = 20) -> list[KeywordHit]:
        """Passages of one of the user's papers that contain the question's words, best match first.

        The words are OR-ed (a natural question rarely has every word in one passage) and
        English stop words are ignored. A question with no usable words finds nothing.
        """
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        words = list(dict.fromkeys(word.lower() for word in _QUERY_WORD.findall(query)))[:MAX_QUERY_TERMS]
        if not words:
            return []

        statement = text(
            f"""
            SELECT c.chunk_id, c.document_id, c.text, c.context_prefix, c.section_path,
                   c.page_start, c.page_end,
                   ts_rank_cd({PASSAGE_TSVECTOR}, to_tsquery('english', :tsquery)) AS rank_score
            FROM rag_document_chunks c
            JOIN rag_documents d ON d.document_id = c.document_id
            WHERE d.user_id = :user_id
              AND c.document_id = :document_id
              AND {PASSAGE_TSVECTOR} @@ to_tsquery('english', :tsquery)
            ORDER BY rank_score DESC, c.sequence_index
            LIMIT :limit
            """
        )
        with self._session_factory() as session:
            rows = session.execute(
                statement,
                {"tsquery": " | ".join(words), "user_id": user_id, "document_id": document_id, "limit": limit},
            ).all()
        return [
            KeywordHit(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                text=row.text,
                context_prefix=row.context_prefix,
                section_path=list(row.section_path),
                page_start=row.page_start,
                page_end=row.page_end,
                rank_score=float(row.rank_score),
            )
            for row in rows
        ]

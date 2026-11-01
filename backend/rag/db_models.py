"""SQLAlchemy models for canonical RAG source data and pgvector embeddings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from rag.storage_config import EMBEDDING_DIMENSIONS


class Base(DeclarativeBase):
    """Base for the separate RAG storage schema."""


class RAGDocument(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        CheckConstraint("page_count IS NULL OR page_count > 0", name="ck_rag_documents_page_count"),
        UniqueConstraint("user_id", "source_sha256", name="uq_rag_documents_user_source_sha256"),
    )

    document_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_asset_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    affiliations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parser_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RAGDocumentBlock(Base):
    __tablename__ = "rag_document_blocks"
    block_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rag_documents.document_id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_label: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_document_metadata: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # `metadata` is reserved by SQLAlchemy's declarative API, so use a different
    # Python attribute while preserving the column name in PostgreSQL.
    block_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    image_asset_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_rag_blocks_document_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_rag_blocks_ordinal"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="ck_rag_blocks_page_number"),
    )


class RAGDocumentAsset(Base):
    __tablename__ = "rag_document_assets"
    __table_args__ = (
        UniqueConstraint("document_id", "asset_key", name="uq_rag_assets_document_key"),
        CheckConstraint("size_bytes >= 0", name="ck_rag_assets_size"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="ck_rag_assets_page_number"),
    )

    asset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rag_documents.document_id", ondelete="CASCADE"), nullable=False
    )
    asset_key: Mapped[str] = mapped_column(Text, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_block_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rag_document_blocks.block_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RAGDocumentChunk(Base):
    __tablename__ = "rag_document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "sequence_index", name="uq_rag_chunks_document_sequence"),
        CheckConstraint("sequence_index >= 0", name="ck_rag_chunks_sequence"),
        CheckConstraint("token_count_estimate >= 0", name="ck_rag_chunks_token_estimate"),
        CheckConstraint(
            "page_start IS NULL OR page_end IS NULL OR page_end >= page_start",
            name="ck_rag_chunks_page_range",
        ),
    )

    chunk_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rag_documents.document_id", ondelete="CASCADE"), nullable=False
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_prefix: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    section_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    related_element_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    image_asset_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    previous_chunk_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    next_chunk_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RAGChunkSourceBlock(Base):
    __tablename__ = "rag_chunk_source_blocks"
    __table_args__ = (
        CheckConstraint("link_type IN ('source', 'related')", name="ck_rag_chunk_source_link_type"),
        CheckConstraint("source_position >= 0", name="ck_rag_chunk_source_position"),
    )

    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rag_document_chunks.chunk_id", ondelete="CASCADE"), primary_key=True
    )
    block_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rag_document_blocks.block_id", ondelete="CASCADE"), primary_key=True
    )
    link_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    source_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RAGChunkEmbedding(Base):
    __tablename__ = "rag_chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "model_name", name="uq_rag_embeddings_chunk_model"),
        CheckConstraint(
            f"dimensions = {EMBEDDING_DIMENSIONS}", name="ck_rag_embeddings_dimensions"
        ),
    )

    embedding_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rag_document_chunks.chunk_id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=EMBEDDING_DIMENSIONS)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(EMBEDDING_DIMENSIONS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index("ix_rag_blocks_document_ordinal", RAGDocumentBlock.document_id, RAGDocumentBlock.ordinal)
Index("ix_rag_chunks_document_sequence", RAGDocumentChunk.document_id, RAGDocumentChunk.sequence_index)
Index("ix_rag_embeddings_model_name", RAGChunkEmbedding.model_name)
Index(
    "ix_rag_embeddings_vector_hnsw",
    RAGChunkEmbedding.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)


# RAGDocument.user_id references the users table, so anything that imports these models
# alone (Alembic, the repository) must also see the account tables. Kept at the bottom
# because accounts.models imports Base from this module.
import accounts.models  # noqa: E402,F401

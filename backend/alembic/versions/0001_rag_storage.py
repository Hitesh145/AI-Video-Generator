"""Create canonical RAG storage and pgvector index.

Revision ID: 0001_rag_storage
Revises:
Create Date: 2026-10-28
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0001_rag_storage"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    # Requires pgvector to be installed on the PostgreSQL server. The extension
    # is intentionally retained on downgrade because other schemas may use it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rag_documents",
        sa.Column("document_id", sa.String(length=36), primary_key=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_filename", sa.String(length=512), nullable=False),
        sa.Column("source_asset_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("authors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("affiliations", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parser_name", sa.String(length=128), nullable=False),
        sa.Column("parser_version", sa.String(length=128), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("page_count IS NULL OR page_count > 0", name="ck_rag_documents_page_count"),
        sa.UniqueConstraint("source_sha256", name="uq_rag_documents_source_sha256"),
    )
    op.create_table(
        "rag_document_blocks",
        sa.Column("block_id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=32), nullable=False),
        sa.Column("source_label", sa.String(length=128), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_path", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("heading_level", sa.Integer(), nullable=True),
        sa.Column("is_document_metadata", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("image_asset_key", sa.Text(), nullable=True),
        sa.Column("image_available", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_rag_blocks_ordinal"),
        sa.CheckConstraint("page_number IS NULL OR page_number > 0", name="ck_rag_blocks_page_number"),
        sa.ForeignKeyConstraint(["document_id"], ["rag_documents.document_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "ordinal", name="uq_rag_blocks_document_ordinal"),
    )
    op.create_index("ix_rag_blocks_document_ordinal", "rag_document_blocks", ["document_id", "ordinal"])

    op.create_table(
        "rag_document_assets",
        sa.Column("asset_id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("asset_key", sa.Text(), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("source_block_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="ck_rag_assets_size"),
        sa.CheckConstraint("page_number IS NULL OR page_number > 0", name="ck_rag_assets_page_number"),
        sa.ForeignKeyConstraint(["document_id"], ["rag_documents.document_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_block_id"], ["rag_document_blocks.block_id"], ondelete="SET NULL"),
        sa.UniqueConstraint("document_id", "asset_key", name="uq_rag_assets_document_key"),
    )

    op.create_table(
        "rag_document_chunks",
        sa.Column("chunk_id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("context_prefix", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("token_count_estimate", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.String(length=64), nullable=True),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column("section_path", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("related_element_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("image_asset_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("previous_chunk_id", sa.String(length=36), nullable=True),
        sa.Column("next_chunk_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("sequence_index >= 0", name="ck_rag_chunks_sequence"),
        sa.CheckConstraint("token_count_estimate >= 0", name="ck_rag_chunks_token_estimate"),
        sa.CheckConstraint("page_start IS NULL OR page_end IS NULL OR page_end >= page_start", name="ck_rag_chunks_page_range"),
        sa.ForeignKeyConstraint(["document_id"], ["rag_documents.document_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "sequence_index", name="uq_rag_chunks_document_sequence"),
    )
    op.create_index("ix_rag_chunks_document_sequence", "rag_document_chunks", ["document_id", "sequence_index"])

    op.create_table(
        "rag_chunk_source_blocks",
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("block_id", sa.String(length=36), nullable=False),
        sa.Column("link_type", sa.String(length=16), nullable=False),
        sa.Column("source_position", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("link_type IN ('source', 'related')", name="ck_rag_chunk_source_link_type"),
        sa.CheckConstraint("source_position >= 0", name="ck_rag_chunk_source_position"),
        sa.ForeignKeyConstraint(["chunk_id"], ["rag_document_chunks.chunk_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["block_id"], ["rag_document_blocks.block_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chunk_id", "block_id", "link_type"),
    )

    op.create_table(
        "rag_chunk_embeddings",
        sa.Column("embedding_id", sa.String(length=36), primary_key=True),
        sa.Column("chunk_id", sa.String(length=36), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.SmallInteger(), nullable=False, server_default=str(EMBEDDING_DIMENSIONS)),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding", VECTOR(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(f"dimensions = {EMBEDDING_DIMENSIONS}", name="ck_rag_embeddings_dimensions"),
        sa.ForeignKeyConstraint(["chunk_id"], ["rag_document_chunks.chunk_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("chunk_id", "model_name", name="uq_rag_embeddings_chunk_model"),
    )
    op.create_index("ix_rag_embeddings_model_name", "rag_chunk_embeddings", ["model_name"])
    op.create_index(
        "ix_rag_embeddings_vector_hnsw",
        "rag_chunk_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_rag_embeddings_vector_hnsw", table_name="rag_chunk_embeddings")
    op.drop_index("ix_rag_embeddings_model_name", table_name="rag_chunk_embeddings")
    op.drop_table("rag_chunk_embeddings")
    op.drop_table("rag_chunk_source_blocks")
    op.drop_index("ix_rag_chunks_document_sequence", table_name="rag_document_chunks")
    op.drop_table("rag_document_chunks")
    op.drop_table("rag_document_assets")
    op.drop_index("ix_rag_blocks_document_ordinal", table_name="rag_document_blocks")
    op.drop_table("rag_document_blocks")
    op.drop_table("rag_documents")

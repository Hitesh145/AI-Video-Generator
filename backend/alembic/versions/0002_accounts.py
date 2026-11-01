"""Add user accounts, login sessions, videos and paper ownership.

Revision ID: 0002_accounts
Revises: 0001_rag_storage
Create Date: 2026-11-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_accounts"
down_revision: Union[str, None] = "0001_rag_storage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = op.get_bind().execute(sa.text("SELECT count(*) FROM rag_documents")).scalar_one()
    if existing:
        raise RuntimeError(
            "rag_documents is not empty; clear or re-ingest it before enabling accounts "
            "(there is no way to know which user owns the existing papers)."
        )

    op.create_table(
        "users",
        sa.Column("user_id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("session_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table(
        "videos",
        sa.Column("video_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("run_dir", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="topic"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_dir", name="uq_videos_run_dir"),
    )
    op.create_index("ix_videos_user_id", "videos", ["user_id"])

    op.add_column("rag_documents", sa.Column("user_id", sa.String(length=36), nullable=False))
    op.create_foreign_key(
        "fk_rag_documents_user_id_users", "rag_documents", "users", ["user_id"], ["user_id"], ondelete="CASCADE"
    )
    op.create_index("ix_rag_documents_user_id", "rag_documents", ["user_id"])
    op.drop_constraint("uq_rag_documents_source_sha256", "rag_documents", type_="unique")
    op.create_unique_constraint(
        "uq_rag_documents_user_source_sha256", "rag_documents", ["user_id", "source_sha256"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_rag_documents_user_source_sha256", "rag_documents", type_="unique")
    op.create_unique_constraint("uq_rag_documents_source_sha256", "rag_documents", ["source_sha256"])
    op.drop_index("ix_rag_documents_user_id", table_name="rag_documents")
    op.drop_constraint("fk_rag_documents_user_id_users", "rag_documents", type_="foreignkey")
    op.drop_column("rag_documents", "user_id")
    op.drop_index("ix_videos_user_id", table_name="videos")
    op.drop_table("videos")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("users")

"""Index passage text for keyword search.

Revision ID: 0004_passage_text_index
Revises: 0003_papers
Create Date: 2026-11-03
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0004_passage_text_index"
down_revision: Union[str, None] = "0003_papers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The expression must match rag.pg_repository.PASSAGE_TSVECTOR for the index to be used.
    op.execute(
        "CREATE INDEX ix_rag_chunks_fts ON rag_document_chunks "
        "USING gin (to_tsvector('english', context_prefix || ' ' || text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_fts")

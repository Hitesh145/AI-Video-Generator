"""Let a video belong to a paper.

Revision ID: 0005_video_paper
Revises: 0004_passage_text_index
Create Date: 2026-11-04
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_video_paper"
down_revision: Union[str, None] = "0004_passage_text_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("paper_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_videos_paper_id", "videos", "papers", ["paper_id"], ["paper_id"], ondelete="SET NULL"
    )
    op.create_index("ix_videos_paper_id", "videos", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_videos_paper_id", table_name="videos")
    op.drop_constraint("fk_videos_paper_id", "videos", type_="foreignkey")
    op.drop_column("videos", "paper_id")

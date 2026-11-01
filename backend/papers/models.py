"""The papers table: one row per uploaded PDF, owned by one user, with a processing status."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from rag.db_models import Base

QUEUED = "queued"
PARSING = "parsing"
CHUNKING = "chunking"
STORING = "storing"
EMBEDDING = "embedding"
READY = "ready"
FAILED = "failed"
IN_PROGRESS = frozenset({QUEUED, PARSING, CHUNKING, STORING, EMBEDDING})


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (UniqueConstraint("user_id", "sha256", name="uq_papers_user_sha256"),)

    paper_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=QUEUED)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rag_documents.document_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

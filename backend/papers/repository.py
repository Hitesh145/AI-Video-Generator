"""Database access for papers. Every read that takes a user id only ever sees that user's rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from papers.models import EMBEDDING, FAILED, IN_PROGRESS, QUEUED, Paper
from rag.db_models import RAGDocument, RAGDocumentBlock, RAGDocumentChunk

UPDATABLE_FIELDS = frozenset({"status", "detail", "title", "page_count", "document_id"})


@dataclass(frozen=True)
class PaperRecord:
    paper_id: str
    user_id: str
    filename: str
    size_bytes: int
    sha256: str
    status: str
    detail: str | None
    title: str | None
    page_count: int | None
    document_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PaperReport:
    title: str | None
    authors: list[str]
    page_count: int | None
    chunk_count: int
    figure_count: int
    warnings: list[str]


def _record(row: Paper) -> PaperRecord:
    return PaperRecord(
        paper_id=row.paper_id,
        user_id=row.user_id,
        filename=row.filename,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        status=row.status,
        detail=row.detail,
        title=row.title,
        page_count=row.page_count,
        document_id=row.document_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PaperRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def create(self, user_id: str, filename: str, size_bytes: int, sha256: str) -> PaperRecord:
        with self._session_factory.begin() as session:
            row = Paper(
                paper_id=str(uuid4()),
                user_id=user_id,
                filename=filename,
                size_bytes=size_bytes,
                sha256=sha256,
                status=QUEUED,
            )
            session.add(row)
            session.flush()
            session.refresh(row)        # read back the database-assigned timestamps
            return _record(row)

    def find_by_hash(self, user_id: str, sha256: str) -> PaperRecord | None:
        statement = select(Paper).where(Paper.user_id == user_id, Paper.sha256 == sha256)
        with self._session_factory() as session:
            row = session.scalar(statement)
            return _record(row) if row else None

    def get(self, paper_id: str, user_id: str) -> PaperRecord | None:
        statement = select(Paper).where(Paper.paper_id == paper_id, Paper.user_id == user_id)
        with self._session_factory() as session:
            row = session.scalar(statement)
            return _record(row) if row else None

    def list_for_user(self, user_id: str) -> list[PaperRecord]:
        statement = select(Paper).where(Paper.user_id == user_id).order_by(Paper.created_at.desc())
        with self._session_factory() as session:
            return [_record(row) for row in session.scalars(statement)]

    def update(self, paper_id: str, **fields) -> None:
        unknown = set(fields) - UPDATABLE_FIELDS
        if unknown:
            raise ValueError(f"Cannot update paper fields: {sorted(unknown)}")
        with self._session_factory.begin() as session:
            session.execute(
                update(Paper).where(Paper.paper_id == paper_id).values(**fields, updated_at=func.now())
            )

    def claim_for_reading(self, paper_id: str) -> bool:
        """Failed-while-reading paper -> queued. True only for the one caller that wins the race."""
        return self._claim(paper_id, Paper.document_id.is_(None), status=QUEUED, detail=None)

    def claim_for_retry(self, paper_id: str) -> bool:
        """Failed paper whose text is stored -> embedding. True only for the one caller that wins the race."""
        return self._claim(paper_id, Paper.document_id.is_not(None), status=EMBEDDING, detail="Indexing passages")

    def _claim(self, paper_id: str, document_condition, **values) -> bool:
        statement = (
            update(Paper)
            .where(Paper.paper_id == paper_id, Paper.status == FAILED, document_condition)
            .values(**values, updated_at=func.now())
            .returning(Paper.paper_id)
        )
        with self._session_factory.begin() as session:
            return session.execute(statement).first() is not None

    def fail_interrupted(self, message: str) -> int:
        with self._session_factory.begin() as session:
            result = session.execute(
                update(Paper)
                .where(Paper.status.in_(IN_PROGRESS))
                .values(status=FAILED, detail=message, updated_at=func.now())
            )
            return int(result.rowcount or 0)

    def report(self, document_id: str) -> PaperReport:
        """What the parser stored for a paper. Needs the RAG tables, so PostgreSQL only."""
        with self._session_factory() as session:
            document = session.get(RAGDocument, document_id)
            if document is None:
                raise ValueError(f"No stored document {document_id}")
            chunks = session.scalar(
                select(func.count()).select_from(RAGDocumentChunk).where(RAGDocumentChunk.document_id == document_id)
            )
            figures = session.scalar(
                select(func.count())
                .select_from(RAGDocumentBlock)
                .where(RAGDocumentBlock.document_id == document_id, RAGDocumentBlock.block_type == "figure")
            )
            return PaperReport(
                title=document.title,
                authors=list(document.authors),
                page_count=document.page_count,
                chunk_count=int(chunks or 0),
                figure_count=int(figures or 0),
                warnings=list(document.warnings),
            )

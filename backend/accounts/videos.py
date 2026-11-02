"""Which finished video (run folder) belongs to which user."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from accounts.models import Video


@dataclass(frozen=True)
class VideoRecord:
    video_id: str
    run_dir: str
    title: str
    kind: str
    created_at: datetime
    paper_id: str | None = None


class VideoRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    def record(
        self, user_id: str, run_dir: str, title: str, kind: str = "topic", paper_id: str | None = None
    ) -> str:
        video_id = str(uuid4())
        with self._session_factory.begin() as session:
            session.add(Video(video_id=video_id, user_id=user_id, run_dir=run_dir, title=title, kind=kind, paper_id=paper_id))
        return video_id

    def list_for_user(self, user_id: str) -> list[VideoRecord]:
        statement = select(Video).where(Video.user_id == user_id).order_by(Video.created_at.desc())
        with self._session_factory() as session:
            return [
                VideoRecord(row.video_id, row.run_dir, row.title, row.kind, row.created_at, row.paper_id)
                for row in session.scalars(statement)
            ]

    def list_for_paper(self, user_id: str, paper_id: str) -> list[VideoRecord]:
        statement = (
            select(Video)
            .where(Video.user_id == user_id, Video.paper_id == paper_id)
            .order_by(Video.created_at.desc())
        )
        with self._session_factory() as session:
            return [
                VideoRecord(row.video_id, row.run_dir, row.title, row.kind, row.created_at, row.paper_id)
                for row in session.scalars(statement)
            ]

    def owner_of_run(self, run_dir: str) -> str | None:
        with self._session_factory() as session:
            return session.scalar(select(Video.user_id).where(Video.run_dir == run_dir))

"""HTTP endpoints for videos made from a paper. Every call is scoped to the logged-in owner."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StringConstraints

from accounts.service import UserInfo
from schemas.job import JobCreated
from services.paper_video_service import PaperNotFound, PaperNotReady, PaperVideoService, TopicNotCovered

MAX_TOPIC_LENGTH = 500
Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TOPIC_LENGTH)]

MESSAGES = {
    "covered": "The paper covers this topic.",
    "weak": "The paper may only mention this topic. We can try a short video of what it says; if it has nothing on the topic, we will tell you instead.",
    "absent": "The paper does not cover this topic. It can still be explained from general knowledge.",
}


class TopicBody(BaseModel):
    topic: Topic


class StartBody(TopicBody):
    mode: Literal["paper", "general"] = "paper"


class CoverageOut(BaseModel):
    level: Literal["covered", "weak", "absent"]
    best_similarity: float | None
    message: str


class PaperVideoOut(BaseModel):
    video_id: str
    title: str
    kind: str
    url: str
    created_at: datetime
    notes: list[str]


def create_paper_videos_router(service: PaperVideoService, current_user: Callable[[Request], UserInfo]) -> APIRouter:
    router = APIRouter()

    @router.post("/papers/{paper_id}/videos/check", response_model=CoverageOut)
    def check(paper_id: str, body: TopicBody, user: UserInfo = Depends(current_user)) -> CoverageOut:
        try:
            coverage = service.check(user.user_id, paper_id, body.topic)
        except (PaperNotFound, PaperNotReady) as exc:
            raise _problem(exc)
        return CoverageOut(level=coverage.level, best_similarity=coverage.best_similarity, message=MESSAGES[coverage.level])

    @router.post("/papers/{paper_id}/videos", response_model=JobCreated, status_code=202)
    def start(paper_id: str, body: StartBody, user: UserInfo = Depends(current_user)) -> JobCreated:
        try:
            return JobCreated(job_id=service.start(user.user_id, paper_id, body.topic, body.mode))
        except (PaperNotFound, PaperNotReady, TopicNotCovered) as exc:
            raise _problem(exc)

    @router.get("/papers/{paper_id}/videos", response_model=list[PaperVideoOut])
    def list_videos(paper_id: str, user: UserInfo = Depends(current_user)) -> list[PaperVideoOut]:
        try:
            items = service.list_videos(user.user_id, paper_id)
        except PaperNotFound as exc:
            raise _problem(exc)
        return [
            PaperVideoOut(
                video_id=item.record.video_id, title=item.record.title, kind=item.record.kind,
                url=f"/media/{item.record.run_dir}/lesson_demo.mp4", created_at=item.record.created_at,
                notes=item.notes,
            )
            for item in items
        ]

    return router


def _problem(exc: Exception) -> HTTPException:
    if isinstance(exc, PaperNotFound):
        return HTTPException(status_code=404, detail="Paper not found")
    if isinstance(exc, PaperNotReady):
        return HTTPException(status_code=409, detail=f"This paper is not ready yet (status: {exc.status}).")
    return HTTPException(status_code=409, detail="The paper does not cover this topic.")

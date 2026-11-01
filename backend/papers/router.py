"""HTTP endpoints for the paper library. Every paper is private to the logged-in owner."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from accounts.service import UserInfo
from papers.models import FAILED
from papers.repository import PaperRecord, PaperReport
from papers.service import CannotRetry, InvalidUpload, PaperService, UploadTooLarge


class PaperOut(BaseModel):
    paper_id: str
    filename: str
    size_bytes: int
    status: str
    detail: str | None
    title: str | None
    page_count: int | None
    can_retry: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: PaperRecord) -> "PaperOut":
        return cls(
            paper_id=record.paper_id,
            filename=record.filename,
            size_bytes=record.size_bytes,
            status=record.status,
            detail=record.detail,
            title=record.title,
            page_count=record.page_count,
            can_retry=record.status == FAILED and record.document_id is not None,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class PaperReportOut(BaseModel):
    title: str | None
    authors: list[str]
    page_count: int | None
    chunk_count: int
    figure_count: int
    warnings: list[str]

    @classmethod
    def from_report(cls, report: PaperReport) -> "PaperReportOut":
        return cls(
            title=report.title,
            authors=report.authors,
            page_count=report.page_count,
            chunk_count=report.chunk_count,
            figure_count=report.figure_count,
            warnings=report.warnings,
        )


class PaperDetailOut(PaperOut):
    report: PaperReportOut | None = None


def create_papers_router(service: PaperService, current_user: Callable[[Request], UserInfo]) -> APIRouter:
    router = APIRouter()

    @router.post("/papers", response_model=PaperOut, status_code=202)
    def upload_paper(response: Response, file: UploadFile = File(...), user: UserInfo = Depends(current_user)):
        try:
            record, created = service.upload(user.user_id, file.filename or "", file.file)
        except InvalidUpload as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except UploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc))
        if not created:
            response.status_code = 200
        return PaperOut.from_record(record)

    @router.get("/papers", response_model=list[PaperOut])
    def list_papers(user: UserInfo = Depends(current_user)):
        return [PaperOut.from_record(record) for record in service.list(user.user_id)]

    @router.get("/papers/{paper_id}", response_model=PaperDetailOut)
    def get_paper(paper_id: str, user: UserInfo = Depends(current_user)):
        record = service.get(paper_id, user.user_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        report = service.report(paper_id, user.user_id)
        return PaperDetailOut(
            **PaperOut.from_record(record).model_dump(),
            report=PaperReportOut.from_report(report) if report is not None else None,
        )

    @router.post("/papers/{paper_id}/retry", response_model=PaperOut, status_code=202)
    def retry_paper(paper_id: str, user: UserInfo = Depends(current_user)):
        try:
            record = service.retry(paper_id, user.user_id)
        except CannotRetry as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if record is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        return PaperOut.from_record(record)

    return router

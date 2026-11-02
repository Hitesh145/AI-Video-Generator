"""Videos made from one of the user's papers: find the relevant passages, judge coverage, write, render."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol

from accounts.videos import VideoRecord, VideoRepository
from papers.models import READY
from papers.repository import PaperRecord
from retrieval.coverage import Coverage, assess_coverage
from retrieval.evidence import Evidence
from schemas.demo import DemoVideoResponse
from schemas.lesson import UserLessonRequest
from services.grounded_lesson_service import GroundedResult
from services.job_service import JobService
from services.run_context import llm_step, report_stage

Mode = Literal["paper", "general"]
CoverageCheck = Coverage

NOT_CHECKED_WARNING = "This video has not yet been checked sentence by sentence against the paper."
BRIEF_WARNING = "The paper only touches this topic briefly."


class PaperNotFound(Exception):
    """The paper does not exist, or belongs to someone else (deliberately the same answer)."""


class PaperNotReady(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class TopicNotCovered(Exception):
    """The paper does not cover the requested topic."""


class PaperLookup(Protocol):
    def get(self, paper_id: str, user_id: str) -> PaperRecord | None: ...


class Searcher(Protocol):
    def search(self, user_id: str, document_id: str, query: str, k: int = 8, mode: str = "hybrid") -> list[Evidence]: ...


class Grounded(Protocol):
    def create(self, topic: str, evidence: Sequence[Evidence], brief: bool = False) -> GroundedResult: ...


class Renderer(Protocol):
    def render_lesson(self, lesson_request, lesson_plan, lesson_script, knowledge_base=None, qc_warnings=None, extra_artifacts=None) -> DemoVideoResponse: ...

    def generate_demo_video(self, request: UserLessonRequest) -> DemoVideoResponse: ...


class PaperVideoService:
    def __init__(
        self,
        papers: PaperLookup,
        searcher: Searcher,
        grounded: Grounded,
        demo: Renderer,
        jobs: JobService,
        videos: VideoRepository,
        evidence_count: int = 12,
    ) -> None:
        self.papers = papers
        self.searcher = searcher
        self.grounded = grounded
        self.demo = demo
        self.jobs = jobs
        self.videos = videos
        self.evidence_count = evidence_count

    def check(self, user_id: str, paper_id: str, topic: str) -> CoverageCheck:
        paper = self._ready_paper(user_id, paper_id)
        return assess_coverage(self._search(user_id, paper, topic))

    def start(self, user_id: str, paper_id: str, topic: str, mode: Mode) -> str:
        """Start the video as a background job and return the job id."""
        request = UserLessonRequest(request=topic)
        if mode == "general":
            self._owned_paper(user_id, paper_id)
            return self.jobs.start(
                request, user_id,
                pipeline=self.demo.generate_demo_video,
                on_complete=self._recorder("general", paper_id),
            )

        paper = self._ready_paper(user_id, paper_id)
        evidence = self._search(user_id, paper, topic)
        coverage = assess_coverage(evidence)
        if coverage.level == "absent":
            raise TopicNotCovered()
        return self.jobs.start(
            request, user_id,
            pipeline=lambda _request: self._make_paper_video(topic, evidence, coverage),
            on_complete=self._recorder("paper", paper_id),
        )

    def list_videos(self, user_id: str, paper_id: str) -> list[VideoRecord]:
        self._owned_paper(user_id, paper_id)
        return self.videos.list_for_paper(user_id, paper_id)

    # ------------------------------------------------------------------ internals
    def _owned_paper(self, user_id: str, paper_id: str) -> PaperRecord:
        paper = self.papers.get(paper_id, user_id)
        if paper is None:
            raise PaperNotFound()
        return paper

    def _ready_paper(self, user_id: str, paper_id: str) -> PaperRecord:
        paper = self._owned_paper(user_id, paper_id)
        if paper.status != READY or not paper.document_id:
            raise PaperNotReady(paper.status)
        return paper

    def _search(self, user_id: str, paper: PaperRecord, topic: str) -> list[Evidence]:
        return self.searcher.search(user_id, paper.document_id, topic, k=self.evidence_count, mode="vector")

    def _recorder(self, kind: str, paper_id: str):
        def record(user_id: str, response: DemoVideoResponse) -> None:
            self.videos.record(
                user_id, Path(response.output_dir).name, response.lesson_plan.title, kind=kind, paper_id=paper_id
            )

        return record

    def _make_paper_video(self, topic: str, evidence: list[Evidence], coverage: Coverage) -> DemoVideoResponse:
        report_stage("analyze", "Finding the relevant parts of the paper")
        report_stage("knowledge", f"{len(evidence)} passages{_pages(evidence)}")
        report_stage("plan")
        with llm_step("grounded lesson"):
            result = self.grounded.create(topic, evidence, brief=coverage.level == "weak")
        report_stage("script")

        warnings = [NOT_CHECKED_WARNING]
        if coverage.level == "weak":
            warnings.append(BRIEF_WARNING)
        evidence_file = [
            {
                "passage_id": passage.passage_id,
                "chunk_id": passage.evidence.chunk_id,
                "page_start": passage.evidence.page_start,
                "page_end": passage.evidence.page_end,
                "section_path": passage.evidence.section_path,
                "text": passage.evidence.text,
            }
            for passage in result.passages
        ]
        citations = {
            section.section_title: ids
            for section, ids in zip(result.lesson_script.sections, result.section_citations)
        }
        return self.demo.render_lesson(
            result.lesson_request, result.lesson_plan, result.lesson_script,
            qc_warnings=warnings,
            extra_artifacts={
                "evidence.json": json.dumps(evidence_file, indent=2, ensure_ascii=False),
                "citations.json": json.dumps(citations, indent=2, ensure_ascii=False),
            },
        )


def _pages(evidence: Sequence[Evidence]) -> str:
    starts = [item.page_start for item in evidence if item.page_start is not None]
    ends = [item.page_end for item in evidence if item.page_end is not None]
    if not starts:
        return ""
    low, high = min(starts), max(ends or starts)
    return f", page {low}" if low == high else f", pages {low}-{high}"

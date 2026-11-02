"""Videos made from one of the user's papers: find the relevant passages, judge coverage, write, render."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from accounts.videos import VideoRecord, VideoRepository
from papers.models import READY
from papers.repository import PaperRecord
from retrieval.coverage import Coverage, assess_coverage
from retrieval.evidence import Evidence
from schemas.demo import DemoVideoResponse
from schemas.lesson import UserLessonRequest
from services.claim_checker import ClaimReport, apply_report
from services.grounded_lesson_service import GroundedResult, UngroundedLesson
from services.job_service import JobService
from services.run_context import llm_step, report_stage

Mode = Literal["paper", "general"]
CoverageCheck = Coverage

CHECKED_NOTE = "Each sentence was checked against the passages it cites by a second model pass; this is not a guarantee."
BRIEF_WARNING = "The paper may cover this topic only briefly."


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
    def create(
        self, topic: str, evidence: Sequence[Evidence], brief: bool = False, feedback: Sequence[str] = ()
    ) -> GroundedResult: ...


class Checker(Protocol):
    def check(self, result: GroundedResult) -> ClaimReport: ...


class Renderer(Protocol):
    def render_lesson(self, lesson_request, lesson_plan, lesson_script, knowledge_base=None, qc_warnings=None, extra_artifacts=None, allow_trace=True) -> DemoVideoResponse: ...

    def generate_demo_video(self, request: UserLessonRequest) -> DemoVideoResponse: ...


@dataclass(frozen=True)
class PaperVideoItem:
    record: VideoRecord
    notes: list[str]           # the quality-control warnings saved with the video


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
        output_root: Path | None = None,
        *,
        checker: Checker,
    ) -> None:
        self.papers = papers
        self.searcher = searcher
        self.grounded = grounded
        self.demo = demo
        self.jobs = jobs
        self.videos = videos
        self.evidence_count = evidence_count
        self.output_root = Path(output_root) if output_root else None
        self.checker = checker

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

    def list_videos(self, user_id: str, paper_id: str) -> list[PaperVideoItem]:
        self._owned_paper(user_id, paper_id)
        return [
            PaperVideoItem(record, self._notes(record.run_dir))
            for record in self.videos.list_for_paper(user_id, paper_id)
        ]

    def _notes(self, run_dir: str) -> list[str]:
        if self.output_root is None:
            return []
        try:
            notes = json.loads((self.output_root / run_dir / "qc_warnings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [note for note in notes if isinstance(note, str)] if isinstance(notes, list) else []

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

    def _checked(self, topic: str, evidence: list[Evidence], coverage: Coverage, result: GroundedResult):
        """Check the script; rewrite once if sentences are unsupported; keep the better script; remove what still fails.

        A checker error propagates, so a script that could not be checked is never rendered. If the rewrite cannot be
        written (including when the writer says the passages do not address the topic) the first script is kept and
        its unsupported sentences are removed: it already passed coverage, and what remains is checked.
        """
        report_stage("check")
        with llm_step("claim check"):
            report = self.checker.check(result)
        regenerated = used_rewrite = False
        if not report.ok:
            report_stage("check", "Rewriting the sentences the paper does not support")
            regenerated = True
            try:
                with llm_step("grounded lesson (rewrite)"):
                    rewritten = self.grounded.create(
                        topic, evidence, brief=coverage.level == "weak",
                        feedback=[check.sentence for check in report.failed],
                    )
            except UngroundedLesson:
                rewritten = None
            if rewritten is not None:
                report_stage("check", "Checking the rewritten script")
                with llm_step("claim check (second pass)"):
                    second = self.checker.check(rewritten)
                if len(second.failed) <= len(report.failed):          # keep whichever script loses less
                    result, report, used_rewrite = rewritten, second, True
        fixed, removed = apply_report(result, report)
        return fixed, report, removed, regenerated, used_rewrite

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

        result, report, removed, regenerated, used_rewrite = self._checked(topic, evidence, coverage, result)

        warnings = [CHECKED_NOTE]
        if removed:
            count = len(removed)
            warnings.append(
                f"{count} sentence{'s' if count != 1 else ''} the paper did not support "
                f"{'were' if count != 1 else 'was'} removed."
            )
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
            allow_trace=False,          # the trace path would re-narrate sections with text nobody checked
            extra_artifacts={
                "evidence.json": json.dumps(evidence_file, indent=2, ensure_ascii=False),
                "citations.json": json.dumps(citations, indent=2, ensure_ascii=False),
                "qc_warnings.json": json.dumps(warnings, indent=2, ensure_ascii=False),
                "claim_check.json": json.dumps(
                    {
                        "regenerated": regenerated,
                        "used_rewrite": used_rewrite,
                        "checks": [_check_as_dict(check) for check in report.checks],
                        "removed": [_check_as_dict(check) for check in removed],
                    },
                    indent=2, ensure_ascii=False,
                ),
            },
        )


def _check_as_dict(check) -> dict:
    return {"part": check.part, "sentence": check.sentence, "verdict": check.verdict, "quote": check.quote}


def _pages(evidence: Sequence[Evidence]) -> str:
    starts = [item.page_start for item in evidence if item.page_start is not None]
    ends = [item.page_end for item in evidence if item.page_end is not None]
    if not starts:
        return ""
    low, high = min(starts), max(ends or starts)
    return f", page {low}" if low == high else f", pages {low}-{high}"

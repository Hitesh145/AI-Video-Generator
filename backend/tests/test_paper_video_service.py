import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from accounts_helpers import make_session_factory

from accounts.models import User
from accounts.videos import VideoRepository
from papers.models import Paper
from papers.repository import PaperRecord
from retrieval.evidence import Evidence
from schemas.demo import DemoVideoResponse
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, ScriptSection, UserLessonRequest
from services.grounded_lesson_service import GroundedResult, Passage, UngroundedLesson
from services.job_service import JobService
from services.paper_video_service import (
    NOT_CHECKED_WARNING,
    PaperNotFound,
    PaperNotReady,
    PaperVideoService,
    TopicNotCovered,
)

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def record(user_id, paper_id="paper-1", status="ready", document_id="doc-1"):
    return PaperRecord(paper_id=paper_id, user_id=user_id, filename="p.pdf", size_bytes=1, sha256="a" * 64, status=status,
                       detail=None, title="A paper", page_count=9, document_id=document_id, created_at=NOW, updated_at=NOW)


def evidence(similarity, chunk="c1", page=3):
    return Evidence(chunk_id=chunk, document_id="doc-1", text="Passage text.", context_prefix="", section_path=["3 Method"],
                    page_start=page, page_end=page, methods=("vector",), score=1.0, vector_similarity=similarity)


def response(output_dir):
    return DemoVideoResponse(
        lesson_request=LessonRequest(topic="T", audience="a", goal="g", duration_minutes=2, teaching_depth="intro"),
        lesson_plan=LessonPlan(title="The encoder", learning_objectives=["x"], sections=["How"]),
        lesson_script=LessonScript(introduction="i", sections=[ScriptSection(section_title="How", narration="n")], conclusion="c"),
        output_dir=str(output_dir), video_path=f"{output_dir}/lesson_demo.mp4", video_url=f"/media/{Path(output_dir).name}/lesson_demo.mp4",
    )


class FakePapers:
    def __init__(self, *records):
        self.records = {(r.paper_id, r.user_id): r for r in records}

    def get(self, paper_id, user_id):
        return self.records.get((paper_id, user_id))


class FakeSearcher:
    def __init__(self, similarity):
        self.similarity = similarity
        self.calls = []

    def search(self, user_id, document_id, query, k=8, mode="hybrid"):
        self.calls.append((user_id, document_id, query, k, mode))
        return [evidence(self.similarity, "c1", 3), evidence(self.similarity - 0.05, "c2", 7)]


class FakeGrounded:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def create(self, topic, evidence, brief=False):
        self.calls.append((topic, list(evidence), brief))
        if self.error:
            raise self.error
        passages = [Passage(f"P{i}", item) for i, item in enumerate(evidence, start=1)]
        return GroundedResult(
            lesson_request=LessonRequest(topic=topic, audience="a", goal="g", duration_minutes=2, teaching_depth="intro"),
            lesson_plan=LessonPlan(title="The encoder", learning_objectives=["x"], sections=["How"]),
            lesson_script=LessonScript(introduction="i", sections=[ScriptSection(section_title="How", narration="n")], conclusion="c"),
            passages=passages, section_citations=[["P1", "P2"]],
        )


class FakeDemo:
    def __init__(self, root):
        self.root = root
        self.rendered = []
        self.generated = []

    def render_lesson(self, lesson_request, lesson_plan, lesson_script, knowledge_base=None, qc_warnings=None, extra_artifacts=None):
        run = self.root / f"run-{uuid4().hex[:6]}"
        run.mkdir()
        self.rendered.append((qc_warnings, dict(extra_artifacts or {})))
        return response(run)

    def generate_demo_video(self, request):
        run = self.root / f"general-{uuid4().hex[:6]}"
        run.mkdir()
        self.generated.append(request.request)
        return response(run)


@pytest.fixture
def world(tmp_path):
    factory = make_session_factory()
    users = {"me": str(uuid4()), "other": str(uuid4())}
    with factory.begin() as session:
        for name, user_id in users.items():
            session.add(User(user_id=user_id, email=f"{name}@x.com", password_hash="h"))
        session.add(Paper(paper_id="paper-1", user_id=users["me"], filename="p.pdf", size_bytes=1, sha256="a" * 64))

    class World:
        pass

    w = World()
    w.users = users
    w.me = users["me"]
    w.videos = VideoRepository(factory)
    w.demo = FakeDemo(tmp_path)
    w.jobs = JobService(lambda request: response(tmp_path), tmp_path)
    w.grounded = FakeGrounded()

    def build(similarity=0.9, papers=None, grounded=None):
        w.searcher = FakeSearcher(similarity)
        w.grounded = grounded or FakeGrounded()
        w.service = PaperVideoService(
            papers or FakePapers(record(w.me)), w.searcher, w.grounded, w.demo, w.jobs, w.videos
        )
        return w.service

    w.build = build
    return w


def finish(world, job_id, user_id=None):
    world.jobs.wait(job_id, timeout=10)
    return world.jobs.get(job_id, user_id or world.me)


def test_check_reports_the_coverage_level(world):
    service = world.build(similarity=0.8)

    check = service.check(world.me, "paper-1", "the encoder")

    assert (check.level, check.best_similarity) == ("covered", 0.8)


def test_check_of_a_foreign_or_missing_paper_is_not_found(world):
    service = world.build()

    with pytest.raises(PaperNotFound):
        service.check(world.users["other"], "paper-1", "x")      # exists, but belongs to someone else
    with pytest.raises(PaperNotFound):
        service.check(world.me, "no-such-paper", "x")
    assert world.searcher.calls == []


def test_check_of_a_paper_that_is_not_ready_names_its_status(world):
    for status, document_id in (("parsing", None), ("failed", "doc-1"), ("ready", None)):
        service = world.build(papers=FakePapers(record(world.me, status=status, document_id=document_id)))
        with pytest.raises(PaperNotReady):
            service.check(world.me, "paper-1", "x")
    assert world.searcher.calls == []


def test_paper_mode_searches_only_the_callers_document_with_vector_search(world):
    service = world.build()

    service.start(world.me, "paper-1", "the encoder", "paper")

    assert world.searcher.calls == [(world.me, "doc-1", "the encoder", 12, "vector")]


def test_an_absent_topic_in_paper_mode_raises_and_starts_no_job(world):
    service = world.build(similarity=0.3)

    with pytest.raises(TopicNotCovered):
        service.start(world.me, "paper-1", "bananas", "paper")

    assert world.grounded.calls == [] and world.videos.list_for_paper(world.me, "paper-1") == []


def test_a_covered_topic_renders_with_citations_evidence_and_the_not_checked_warning(world):
    service = world.build(similarity=0.9)

    job = finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert job.status == "completed"
    warnings, artifacts = world.demo.rendered[0]
    assert NOT_CHECKED_WARNING in warnings and not any("only briefly" in w for w in warnings)
    assert json.loads(artifacts["citations.json"]) == {"How": ["P1", "P2"]}
    evidence_file = json.loads(artifacts["evidence.json"])
    assert [p["passage_id"] for p in evidence_file] == ["P1", "P2"]
    assert evidence_file[0]["chunk_id"] == "c1" and evidence_file[0]["page_start"] == 3
    assert evidence_file[0]["section_path"] == ["3 Method"] and evidence_file[0]["text"] == "Passage text."
    stages = {s.key: s for s in job.stages}
    assert "2 passages" in stages["knowledge"].detail and "3" in stages["knowledge"].detail
    recorded = world.videos.list_for_paper(world.me, "paper-1")
    assert [(v.kind, v.paper_id, v.title) for v in recorded] == [("paper", "paper-1", "The encoder")]


def test_a_weak_topic_uses_brief_mode_and_adds_the_brief_warning(world):
    service = world.build(similarity=0.68)

    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert world.grounded.calls[0][2] is True
    assert any("only briefly" in w for w in world.demo.rendered[0][0])


def test_general_mode_runs_the_unchanged_pipeline_and_records_kind_general(world):
    service = world.build(similarity=0.1)           # even an uncovered topic is fine without the paper

    job = finish(world, service.start(world.me, "paper-1", "bananas", "general"))

    assert job.status == "completed"
    assert world.demo.generated == ["bananas"] and world.grounded.calls == [] and world.searcher.calls == []
    recorded = world.videos.list_for_paper(world.me, "paper-1")
    assert [(v.kind, v.paper_id) for v in recorded] == [("general", "paper-1")]


def test_general_mode_on_someone_elses_paper_is_not_found(world):
    service = world.build()

    with pytest.raises(PaperNotFound):
        service.start(world.users["other"], "paper-1", "bananas", "general")


def test_a_script_that_cannot_be_grounded_fails_the_job_with_a_message(world):
    service = world.build(grounded=FakeGrounded(error=UngroundedLesson("The lesson could not be tied to the paper: x")))

    job = finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert job.status == "failed"
    assert "could not be tied to the paper" in job.error.message
    assert world.videos.list_for_paper(world.me, "paper-1") == []


def test_list_videos_is_scoped_to_the_owner(world):
    service = world.build()
    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert len(service.list_videos(world.me, "paper-1")) == 1
    with pytest.raises(PaperNotFound):
        service.list_videos(world.users["other"], "paper-1")

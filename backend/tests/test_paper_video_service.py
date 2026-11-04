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
from services.claim_checker import ClaimReport, NothingSupported, SentenceCheck
from services.grounded_lesson_service import GroundedResult, Passage, UngroundedLesson
from services.job_service import JobService
from services.paper_video_service import (
    CHECKED_NOTE,
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
    def __init__(self, error=None, background=()):
        self.error = error
        self.background = list(background)
        self.calls = []

    def create(self, topic, evidence, brief=False, feedback=()):
        self.calls.append((topic, list(evidence), brief, list(feedback)))
        if self.error:
            raise self.error
        passages = [Passage(f"P{i}", item) for i, item in enumerate(evidence, start=1)]
        return GroundedResult(
            lesson_request=LessonRequest(topic=topic, audience="a", goal="g", duration_minutes=2, teaching_depth="intro"),
            lesson_plan=LessonPlan(title="The encoder", learning_objectives=["x"], sections=["How"]),
            lesson_script=LessonScript(introduction="Intro.", sections=[ScriptSection(section_title="How", narration="First claim. Second claim.")], conclusion="Outro."),
            passages=passages, section_citations=[["P1", "P2"]], section_background=list(self.background),
        )


def passing_report():
    return ClaimReport([SentenceCheck("How", "First claim.", "supported", "a quote of the paper", True),
                        SentenceCheck("How", "Second claim.", "supported", "another quote", True)])


def failing_report(*sentences):
    return ClaimReport([SentenceCheck("How", s, "unsupported", "", False) for s in sentences])


class FakeChecker:
    def __init__(self, *reports, error=None):
        self.reports = list(reports) or [passing_report()]
        self.error = error
        self.calls = 0
        self.seen = []

    def check(self, result):
        self.calls += 1
        self.seen.append(result)
        if self.error:
            raise self.error
        return self.reports.pop(0) if len(self.reports) > 1 else self.reports[0]


class FakeDemo:
    def __init__(self, root):
        self.root = root
        self.rendered = []
        self.scripts = []
        self.generated = []

    def render_lesson(self, lesson_request, lesson_plan, lesson_script, knowledge_base=None, qc_warnings=None, extra_artifacts=None, allow_trace=True):
        self.allow_trace = allow_trace
        self.scripts.append(lesson_script)
        run = self.root / f"run-{uuid4().hex[:6]}"
        run.mkdir()
        self.rendered.append((qc_warnings, dict(extra_artifacts or {})))
        for name, content in (extra_artifacts or {}).items():
            (run / name).write_text(content, encoding="utf-8")
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

    def build(similarity=0.9, papers=None, grounded=None, checker=None):
        w.searcher = FakeSearcher(similarity)
        w.grounded = grounded or FakeGrounded()
        w.checker = checker or FakeChecker()
        w.service = PaperVideoService(
            papers or FakePapers(record(w.me)), w.searcher, w.grounded, w.demo, w.jobs, w.videos,
            output_root=tmp_path, checker=w.checker,
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

    assert world.searcher.calls == [(world.me, "doc-1", "the encoder", 20, "vector")]


def test_an_absent_topic_in_paper_mode_raises_and_starts_no_job(world):
    service = world.build(similarity=0.3)

    with pytest.raises(TopicNotCovered):
        service.start(world.me, "paper-1", "bananas", "paper")

    assert world.grounded.calls == [] and world.videos.list_for_paper(world.me, "paper-1") == []


def test_a_covered_topic_renders_with_citations_evidence_and_the_checked_note(world):
    service = world.build(similarity=0.9)

    job = finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert job.status == "completed"
    warnings, artifacts = world.demo.rendered[0]
    assert CHECKED_NOTE in warnings and not any("only briefly" in w for w in warnings)
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


def test_the_video_warnings_are_saved_with_the_video_and_listed_as_notes(world):
    service = world.build(similarity=0.68)
    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    items = service.list_videos(world.me, "paper-1")

    assert len(items) == 1
    assert CHECKED_NOTE in items[0].notes and any("only briefly" in n for n in items[0].notes)
    assert items[0].record.kind == "paper"


def test_a_general_video_has_no_notes(world):
    service = world.build()
    finish(world, service.start(world.me, "paper-1", "bananas", "general"))

    assert service.list_videos(world.me, "paper-1")[0].notes == []


def test_the_check_stage_is_reported_and_the_note_says_each_sentence_was_checked(world):
    service = world.build()

    job = finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert "check" in [s.key for s in job.stages] and world.checker.calls == 1
    artifacts = world.demo.rendered[0][1]
    saved = json.loads(artifacts["claim_check.json"])
    assert saved["regenerated"] is False and saved["removed"] == [] and len(saved["checks"]) == 2
    assert "not a guarantee" in CHECKED_NOTE


def test_failed_sentences_trigger_one_regeneration_with_feedback_and_the_second_result_is_rendered(world):
    checker = FakeChecker(failing_report("Second claim."), passing_report())
    service = world.build(checker=checker)

    job = finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert job.status == "completed" and checker.calls == 2
    assert len(world.grounded.calls) == 2 and world.grounded.calls[1][3] == ["Second claim."]
    assert json.loads(world.demo.rendered[0][1]["claim_check.json"])["regenerated"] is True


def test_sentences_still_failing_after_regeneration_are_removed_and_the_note_says_how_many(world):
    checker = FakeChecker(failing_report("Second claim."), failing_report("Second claim."))
    service = world.build(checker=checker)

    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    warnings, artifacts = world.demo.rendered[0]
    assert any("1 sentence the paper did not support was removed" in w for w in warnings)
    saved = json.loads(artifacts["claim_check.json"])
    assert [r["sentence"] for r in saved["removed"]] == ["Second claim."]


def test_if_the_rewrite_cannot_be_grounded_the_first_script_is_kept_with_its_unsupported_sentences_removed(world):
    class RewriteFails(FakeGrounded):
        def create(self, topic, evidence, brief=False, feedback=()):
            if feedback:
                raise UngroundedLesson("could not be tied")
            return super().create(topic, evidence, brief, feedback)

    checker = FakeChecker(failing_report("Second claim."))
    service = world.build(checker=checker, grounded=RewriteFails())

    job = finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert job.status == "completed"
    assert any("removed" in w for w in world.demo.rendered[0][0])


def test_a_checker_exception_fails_the_job_and_renders_nothing(world):
    service = world.build(checker=FakeChecker(error=RuntimeError("model down")))

    job = finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert job.status == "failed" and "model down" in job.error.message
    assert world.demo.rendered == [] and world.videos.list_for_paper(world.me, "paper-1") == []


def test_nothing_supported_fails_the_job_with_a_plain_message(world):
    service = world.build(checker=FakeChecker(failing_report("First claim.", "Second claim.")))

    job = finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert job.status == "failed" and "no video was made" in job.error.message
    assert world.demo.rendered == []


def test_paper_videos_never_use_the_trace_path_whose_narration_is_rewritten_by_another_model(world):
    service = world.build()

    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    assert world.demo.allow_trace is False


def test_the_better_of_the_two_scripts_is_rendered(world):
    # The rewrite is checked too, and is worse than the first script: the first one is kept.
    checker = FakeChecker(failing_report("Second claim."), failing_report("First claim.", "Second claim."))
    service = world.build(checker=checker)

    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    saved = json.loads(world.demo.rendered[0][1]["claim_check.json"])
    assert saved["regenerated"] is True and saved["used_rewrite"] is False
    assert [r["sentence"] for r in saved["removed"]] == ["Second claim."]


def test_a_failed_rewrite_is_recorded_as_a_regeneration_attempt(world):
    class RewriteFails(FakeGrounded):
        def create(self, topic, evidence, brief=False, feedback=()):
            if feedback:
                raise UngroundedLesson("could not be tied")
            return super().create(topic, evidence, brief, feedback)

    service = world.build(checker=FakeChecker(failing_report("Second claim.")), grounded=RewriteFails())

    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    saved = json.loads(world.demo.rendered[0][1]["claim_check.json"])
    assert saved["regenerated"] is True and saved["used_rewrite"] is False


def test_the_final_narration_starts_with_the_background_marker(world):
    service = world.build(grounded=FakeGrounded(background=["A claim is a statement."]))

    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    narration = world.demo.scripts[0].sections[0].narration
    assert narration == "Some background that is not from the paper: A claim is a statement. First claim. Second claim."


def test_the_note_is_added_only_when_background_is_used(world):
    note = "Sentences introduced as background are general knowledge, not from the paper, and are not checked against it."
    service = world.build(grounded=FakeGrounded(background=["A claim is a statement."]))
    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))
    assert note in world.demo.rendered[0][0]

    other = world.build()
    finish(world, other.start(world.me, "paper-1", "the encoder", "paper"))
    assert note not in world.demo.rendered[1][0]
    assert world.demo.scripts[1].sections[0].narration == "First claim. Second claim."


def test_the_claim_checker_never_receives_the_background_text(world):
    service = world.build(grounded=FakeGrounded(background=["A claim is a statement."]))

    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    for seen in world.checker.seen:
        text = " ".join([seen.lesson_script.introduction, *(s.narration for s in seen.lesson_script.sections)])
        assert "A claim is a statement." not in text and "Some background" not in text


def test_claim_check_json_lists_the_background(world):
    service = world.build(grounded=FakeGrounded(background=["A claim is a statement."]))

    finish(world, service.start(world.me, "paper-1", "the encoder", "paper"))

    saved = json.loads(world.demo.rendered[0][1]["claim_check.json"])
    assert saved["background"] == [{"section": "How", "text": "A claim is a statement."}]

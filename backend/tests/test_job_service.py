import json
import threading

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

from accounts.service import UserInfo
from fakes import FakeLLM
from schemas.demo import DemoVideoResponse
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, ScriptSection, UserLessonRequest
from services.job_service import STAGES, JobService
from services.jobs_router import create_jobs_router
from services.llm_recorder import RecordingLLM
from services.run_context import bind_run_directory, llm_step, report_section, report_stage


class Answer(BaseModel):
    text: str


def make_response(output_dir="out"):
    return DemoVideoResponse(
        lesson_request=LessonRequest(topic="T", audience="a", goal="g", duration_minutes=2, teaching_depth="intro"),
        lesson_plan=LessonPlan(title="T", learning_objectives=["x"], sections=["s"]),
        lesson_script=LessonScript(introduction="i", sections=[ScriptSection(section_title="s", narration="n")], conclusion="c"),
        output_dir=str(output_dir),
        video_path="out/lesson_demo.mp4",
        video_url="/media/out/lesson_demo.mp4",
    )


REQUEST = UserLessonRequest(request="Explain binary search")
USER = "user-1"


def run_to_end(service, pipeline_request=REQUEST):
    job_id = service.start(pipeline_request, USER)
    service.wait(job_id, timeout=10)
    return service.get(job_id, USER)


def test_completed_job_marks_every_stage_done(tmp_path):
    def pipeline(request):
        for key, _ in STAGES:
            if key != "animate":
                report_stage(key)
        return make_response()

    status = run_to_end(JobService(pipeline, tmp_path))

    assert status.status == "completed"
    assert [s.state for s in status.stages] == ["done"] * len(STAGES)
    assert [s.key for s in status.stages] == [key for key, _ in STAGES]
    assert status.result.video_url == "/media/out/lesson_demo.mp4"
    assert status.error is None
    assert status.elapsed_seconds >= 0


def test_status_during_the_run_reflects_the_real_stage_and_section(tmp_path):
    reached, release = threading.Event(), threading.Event()

    def pipeline(request):
        report_stage("analyze")
        report_stage("knowledge", "skipped")
        report_stage("plan")
        report_stage("script")
        report_stage("route")
        report_section(2, 5, "Divide and conquer", "trace", "narrating steps")
        reached.set()
        release.wait(timeout=10)
        return make_response()

    service = JobService(pipeline, tmp_path)
    job_id = service.start(REQUEST, USER)
    assert reached.wait(timeout=10)

    status = service.get(job_id, USER)
    states = {s.key: s.state for s in status.stages}
    assert status.status == "running"
    assert states == {
        "analyze": "done", "knowledge": "done", "plan": "done", "script": "done",
        "route": "done", "animate": "current", "assemble": "pending",
    }
    assert [s for s in status.stages if s.key == "knowledge"][0].detail == "skipped"
    assert [s for s in status.stages if s.key == "animate"][0].detail == "Section 2 of 5 · narrating steps"
    assert status.section.model_dump() == {
        "index": 2, "total": 5, "title": "Divide and conquer", "path": "trace", "activity": "narrating steps",
    }
    assert status.result is None

    release.set()
    service.wait(job_id, timeout=10)
    assert service.get(job_id, USER).status == "completed"


def test_failure_marks_the_current_stage_failed_and_logs_before_the_run_folder_exists(tmp_path):
    def pipeline(request):
        report_stage("analyze")
        report_stage("plan")
        raise ValueError("boom")

    service = JobService(pipeline, tmp_path)
    status = run_to_end(service)

    states = {s.key: s.state for s in status.stages}
    assert status.status == "failed"
    assert states["analyze"] == "done" and states["plan"] == "failed" and states["script"] == "pending"
    assert status.error.stage == "Building the lesson plan"
    assert status.error.message == "ValueError: boom"
    assert status.result is None

    logs = list((tmp_path / "_failed").glob("*/llm_calls.json"))
    assert len(logs) == 1
    assert json.loads(logs[0].read_text(encoding="utf-8"))["status"] == "failed"


def test_calls_are_logged_into_the_bound_run_folder(tmp_path):
    llm = RecordingLLM(FakeLLM([{"text": "hi"}]))
    folder = tmp_path / "run1"

    def pipeline(request):
        report_stage("analyze")
        with llm_step("lesson analyzer"):
            llm.generate_structured("PROMPT", Answer)
        bind_run_directory(folder)
        return make_response(folder)

    run_to_end(JobService(pipeline, tmp_path))

    log = json.loads((folder / "llm_calls.json").read_text(encoding="utf-8"))
    assert log["status"] == "completed"
    assert [c["label"] for c in log["calls"]] == ["lesson analyzer"]
    assert log["calls"][0]["prompt"] == "PROMPT"


def test_two_jobs_at_once_do_not_mix_logs_or_progress(tmp_path):
    llm = RecordingLLM(FakeLLM([{"text": "a"}, {"text": "b"}]))
    barrier = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    reached = {"A": threading.Event(), "B": threading.Event()}
    gate = threading.Event()

    def pipeline(request):
        name = request.request
        report_stage("analyze" if name == "A" else "plan")
        barrier.wait()                       # both pipelines are inside their run at the same time
        reached[name].set()
        gate.wait(timeout=10)
        with lock, llm_step(f"step {name}"):
            llm.generate_structured(f"prompt {name}", Answer)
        bind_run_directory(tmp_path / name)
        return make_response(tmp_path / name)

    service = JobService(pipeline, tmp_path)
    job_a = service.start(UserLessonRequest(request="A"), USER)
    job_b = service.start(UserLessonRequest(request="B"), USER)
    assert reached["A"].wait(timeout=10) and reached["B"].wait(timeout=10)

    states_a = {s.key: s.state for s in service.get(job_a, USER).stages}
    states_b = {s.key: s.state for s in service.get(job_b, USER).stages}
    assert states_a["analyze"] == "current" and states_a["plan"] == "pending"
    assert states_b["analyze"] == "done" and states_b["plan"] == "current"   # B's report closed its earlier stages only

    gate.set()
    service.wait(job_a, timeout=10)
    service.wait(job_b, timeout=10)

    log_a = json.loads((tmp_path / "A" / "llm_calls.json").read_text(encoding="utf-8"))
    log_b = json.loads((tmp_path / "B" / "llm_calls.json").read_text(encoding="utf-8"))
    assert [c["prompt"] for c in log_a["calls"]] == ["prompt A"]
    assert [c["prompt"] for c in log_b["calls"]] == ["prompt B"]
    assert [c["label"] for c in log_a["calls"]] == ["step A"]
    assert [c["label"] for c in log_b["calls"]] == ["step B"]


def test_unknown_job_is_none(tmp_path):
    assert JobService(lambda request: make_response(), tmp_path).get("nope", USER) is None


def test_run_blocking_returns_the_result_and_writes_the_log(tmp_path):
    folder = tmp_path / "run1"

    def pipeline(request):
        bind_run_directory(folder)
        return make_response(folder)

    result = JobService(pipeline, tmp_path).run_blocking(REQUEST, USER)

    assert result.video_url == "/media/out/lesson_demo.mp4"
    assert json.loads((folder / "llm_calls.json").read_text(encoding="utf-8"))["status"] == "completed"


def test_run_blocking_reraises_and_logs_the_failure(tmp_path):
    def pipeline(request):
        raise RuntimeError("down")

    with pytest.raises(RuntimeError, match="down"):
        JobService(pipeline, tmp_path).run_blocking(REQUEST, USER)

    logs = list((tmp_path / "_failed").glob("*/llm_calls.json"))
    assert json.loads(logs[0].read_text(encoding="utf-8"))["error"] == "RuntimeError: down"


def stub_current_user(request: Request) -> UserInfo:
    user_id = request.headers.get("x-user")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    return UserInfo(user_id, f"{user_id}@x.com")


def jobs_client(service):
    app = FastAPI()
    app.include_router(create_jobs_router(service, stub_current_user))
    return TestClient(app)


def test_endpoints_create_and_poll_a_job(tmp_path):
    service = JobService(lambda request: make_response(), tmp_path)
    client = jobs_client(service)
    headers = {"x-user": USER}

    created = client.post("/lesson/jobs", json={"request": "Explain binary search"}, headers=headers)
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    service.wait(job_id, timeout=10)

    polled = client.get(f"/lesson/jobs/{job_id}", headers=headers)
    body = polled.json()
    assert polled.status_code == 200
    assert body["status"] == "completed"
    assert [s["key"] for s in body["stages"]] == [key for key, _ in STAGES]
    assert body["result"]["video_url"] == "/media/out/lesson_demo.mp4"

    assert client.get("/lesson/jobs/unknown", headers=headers).status_code == 404


def test_jobs_endpoints_need_login_and_hide_other_users_jobs(tmp_path):
    service = JobService(lambda request: make_response(), tmp_path)
    client = jobs_client(service)

    assert client.post("/lesson/jobs", json={"request": "x"}).status_code == 401
    assert client.get("/lesson/jobs/anything").status_code == 401

    job_id = client.post("/lesson/jobs", json={"request": "x"}, headers={"x-user": "user-1"}).json()["job_id"]
    service.wait(job_id, timeout=10)
    assert client.get(f"/lesson/jobs/{job_id}", headers={"x-user": "user-2"}).status_code == 404
    assert client.get(f"/lesson/jobs/{job_id}", headers={"x-user": "user-1"}).status_code == 200


def test_another_users_job_is_invisible(tmp_path):
    service = JobService(lambda request: make_response(), tmp_path)
    job_id = service.start(REQUEST, "user-1")
    service.wait(job_id, timeout=10)

    assert service.get(job_id, "user-2") is None
    assert service.get(job_id, "user-1").status == "completed"


def test_on_complete_receives_the_owner_and_the_result_for_jobs_and_blocking_runs(tmp_path):
    calls = []
    service = JobService(
        lambda request: make_response(),
        tmp_path,
        on_complete=lambda user_id, result: calls.append((user_id, result.video_url)),
    )

    run_to_end(service)
    service.run_blocking(REQUEST, "user-2")

    assert calls == [("user-1", "/media/out/lesson_demo.mp4"), ("user-2", "/media/out/lesson_demo.mp4")]


def test_a_failing_on_complete_fails_the_job_and_the_log(tmp_path):
    folder = tmp_path / "run1"

    def pipeline(request):
        bind_run_directory(folder)
        return make_response(folder)

    def broken(user_id, result):
        raise RuntimeError("cannot record video")

    status = run_to_end(JobService(pipeline, tmp_path, on_complete=broken))

    assert status.status == "failed"
    assert status.error.message == "RuntimeError: cannot record video"
    assert json.loads((folder / "llm_calls.json").read_text(encoding="utf-8"))["status"] == "failed"

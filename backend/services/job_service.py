import logging
import threading
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

from schemas.demo import DemoVideoResponse
from schemas.job import JobError, JobSection, JobStage, JobStatus
from schemas.lesson import UserLessonRequest
from services.llm_recorder import LLMCallRecorder
from services.run_context import NullProgress, RunContext, run_scope


logger = logging.getLogger(__name__)

STAGES: list[tuple[str, str]] = [
    ("analyze", "Understanding the request"),
    ("knowledge", "Gathering resources"),
    ("plan", "Building the lesson plan"),
    ("script", "Creating the script"),
    ("route", "Choosing animations"),
    ("animate", "Animating sections"),
    ("assemble", "Assembling the video"),
]
_KEYS = [key for key, _ in STAGES]
_LABELS = dict(STAGES)

Pipeline = Callable[[UserLessonRequest], DemoVideoResponse]
OnComplete = Callable[[str, DemoVideoResponse], None]


class JobProgress:
    """Thread-safe stage state of one job; receives the pipeline's progress reports."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._finished: float | None = None
        self._states = {key: "pending" for key in _KEYS}
        self._details: dict[str, str | None] = {}
        self._current: str | None = None
        self._section: JobSection | None = None
        self._result: DemoVideoResponse | None = None
        self._error: JobError | None = None
        self._status = "running"

    def stage(self, key: str, detail: str | None = None) -> None:
        with self._lock:
            self._enter(key, detail)

    def section(self, number: int, total: int, title: str, path: str, activity: str) -> None:
        with self._lock:
            self._section = JobSection(index=number, total=total, title=title, path=path, activity=activity)
            self._enter("animate", f"Section {number} of {total} · {activity}")

    def complete(self, result: DemoVideoResponse) -> None:
        with self._lock:
            for key in _KEYS:
                if self._states[key] in ("pending", "current"):
                    self._states[key] = "done"
            self._result = result
            self._status = "completed"
            self._finished = time.monotonic()

    def fail(self, exc: Exception) -> None:
        with self._lock:
            if self._current is not None:
                self._states[self._current] = "failed"
            stage = _LABELS[self._current] if self._current else "Starting"
            self._error = JobError(stage=stage, message=f"{type(exc).__name__}: {exc}")
            self._status = "failed"
            self._finished = time.monotonic()

    def snapshot(self) -> JobStatus:
        with self._lock:
            end = self._finished if self._finished is not None else time.monotonic()
            return JobStatus(
                job_id=self.job_id,
                status=self._status,
                elapsed_seconds=round(end - self._started, 1),
                stages=[
                    JobStage(key=key, label=label, state=self._states[key], detail=self._details.get(key))
                    for key, label in STAGES
                ],
                section=self._section,
                result=self._result,
                error=self._error,
            )

    def _enter(self, key: str, detail: str | None) -> None:
        if key not in _KEYS:
            return
        position = _KEYS.index(key)
        for earlier in _KEYS[:position]:
            if self._states[earlier] in ("pending", "current"):
                self._states[earlier] = "done"
        self._states[key] = "current"
        self._details[key] = detail
        self._current = key


class JobService:
    def __init__(self, pipeline: Pipeline, output_root: Path, on_complete: OnComplete | None = None) -> None:
        self.pipeline = pipeline
        self.output_root = Path(output_root)
        self.on_complete = on_complete
        self._jobs: dict[str, tuple[JobProgress, threading.Thread, str]] = {}
        self._lock = threading.Lock()

    def start(self, request: UserLessonRequest, user_id: str) -> str:
        job_id = uuid4().hex[:12]
        progress = JobProgress(job_id)
        thread = threading.Thread(target=self._run, args=(progress, request, user_id), daemon=True, name=f"job-{job_id}")
        with self._lock:
            self._jobs[job_id] = (progress, thread, user_id)
        thread.start()
        return job_id

    def get(self, job_id: str, user_id: str) -> JobStatus | None:
        """The job's status, or None if it does not exist or belongs to someone else."""
        with self._lock:
            entry = self._jobs.get(job_id)
        return entry[0].snapshot() if entry and entry[2] == user_id else None

    def wait(self, job_id: str, timeout: float | None = None) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
        if entry:
            entry[1].join(timeout)

    def run_blocking(self, request: UserLessonRequest, user_id: str) -> DemoVideoResponse:
        """Run the pipeline in the calling thread (the old endpoint), still writing the LLM log."""
        return self._execute(NullProgress(), request, user_id)

    def _run(self, progress: JobProgress, request: UserLessonRequest, user_id: str) -> None:
        try:
            result = self._execute(progress, request, user_id)
        except Exception as exc:
            logger.exception("Job %s failed", progress.job_id)
            progress.fail(exc)
            return
        progress.complete(result)

    def _execute(
        self, progress: NullProgress | JobProgress, request: UserLessonRequest, user_id: str
    ) -> DemoVideoResponse:
        recorder = LLMCallRecorder(request.request, fallback_root=self.output_root)
        try:
            with run_scope(RunContext(recorder, progress)):
                result = self.pipeline(request)
            if self.on_complete is not None:
                self.on_complete(user_id, result)
        except Exception as exc:
            recorder.finish("failed", f"{type(exc).__name__}: {exc}")
            raise
        recorder.finish("completed")
        return result

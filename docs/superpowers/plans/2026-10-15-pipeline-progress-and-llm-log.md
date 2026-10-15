# Pipeline Progress, Video Display and LLM Call Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the studio show real pipeline progress, play the generated videos, and write every LLM call (input and output) into `llm_calls.md` and `llm_calls.json` in each run folder.

**Architecture:** A `contextvars`-based run context carries an LLM call recorder and a progress reporter implicitly, so existing service and animator signatures stay unchanged. A `RecordingLLM` wrapper records every call. A thread-based `JobService` runs the existing pipeline and exposes stage state through `POST /lesson/jobs` and `GET /lesson/jobs/{id}`. Videos get `+faststart`, a `Range`-capable media route replaces `StaticFiles`, and the React app polls the job endpoint and plays the result.

**Tech Stack:** FastAPI 0.115 / Starlette 0.38.6, pydantic v2, `contextvars`, `threading`, ffmpeg, React 19 + Vite + TypeScript (frontend), pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-pipeline-progress-and-llm-log-design.md`

## Global Constraints

- Run backend tests from `backend/`. Default `python -m pytest -q` excludes the `slow` marker; the full run is `python -m pytest -q -m "slow or not slow"`.
- Fakes are imported as `from fakes import FakeLLM`; media helpers as `from media_helpers import make_test_clip`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Stage files by name only; the working tree has many unrelated `backend/output/**` deletions and an untracked `backend/rendering/__init__.py`.
- `POST /lesson/generate-demo-video` keeps its path, request and response shape (the response only gains the additive `video_url` field).
- No change to `LessonScript`, tracers, the router order, or the animation logic.
- Writing the LLM log must never raise into the pipeline.
- Files are written as UTF-8. Markdown fences are one backtick longer than the longest backtick run in their content.
- Frontend checks: `npm run build` and `npm run lint` in `frontend/` must pass (there is no frontend unit-test setup).

## Review Focus

1. **Prompts that contain triple backticks, pipes or non-ASCII text:** the Markdown log stays valid (fence widened, table cells escaped, UTF-8). Tested in Task 1.
2. **Pipeline fails before the run folder exists (for example the analyzer call):** the log still lands in `output/_failed/<run_id>/` with status `failed`. Tested in Task 3.
3. **Two jobs running at once:** logs and progress never mix between them. Tested in Task 3.
4. **Range edge cases and path traversal on `/media`:** open-ended and suffix ranges, an end beyond the file, a start past the end (`416`), and `..` paths (`404`). Tested in Task 4.
5. **Log directory not writable:** the pipeline keeps going and only a warning is logged. Tested in Task 1.

---

## File Structure

**Create**
- `backend/services/run_context.py`: context variable, `RunContext`, `llm_step`, `report_stage`, `report_section`, `bind_run_directory`, `NullProgress`.
- `backend/services/llm_recorder.py`: `LLMCallRecorder`, `RecordingLLM`, `render_markdown`, `fence`.
- `backend/schemas/job.py`: `JobStage`, `JobSection`, `JobError`, `JobStatus`, `JobCreated`.
- `backend/services/job_service.py`: `STAGES`, `JobProgress`, `JobService`.
- `backend/services/jobs_router.py`: `create_jobs_router(job_service)`.
- `backend/rendering/faststart.py`: `is_faststart`, `ensure_faststart`.
- `backend/services/media_response.py`: `parse_range`, `create_media_router(output_root)`.
- `backend/services/video_library.py`: `list_videos(output_root)`.
- Tests: `tests/test_run_context.py`, `tests/test_llm_recorder.py`, `tests/test_job_service.py`, `tests/test_faststart.py`, `tests/test_media_response.py`, `tests/test_video_library.py`.

**Modify**
- `backend/schemas/demo.py`: `video_url` field.
- `backend/services/demo_video_service.py`: stage reporting, labels, run-folder binding, `video_url`.
- `backend/animation/section_animator.py`: labels and section progress.
- `backend/rendering/video_renderer.py`: `+faststart` in `mux_video`.
- `backend/main.py`: wrap the LLM, add the job service and routers, replace the `/media` mount, use the library helper.
- `backend/tests/test_demo_video_service.py`, `backend/tests/test_end_to_end.py`, `backend/tests/test_section_animator.py`: new assertions.
- `frontend/src/App.tsx`, `frontend/src/index.css`.

## Deviations from the spec (decided while planning)

- **The old endpoint also writes the LLM log.** `POST /lesson/generate-demo-video` now runs through `JobService.run_blocking` with a no-op progress reporter, so its run folder gets `llm_calls.*` too (success criterion 4: every run folder). Its path, request and response are unchanged apart from the additive `video_url`.
- **`report_section` signature:** `report_section(number, total, title, path, activity)` with a 1-based `number`; the activity text ("planning beats", "narrating", "rendering scene") builds the stage detail on the server.
- **Router factories:** the job endpoints and the media route live in `create_jobs_router(job_service)` and `create_media_router(output_root)` so they can be tested with a small FastAPI app without importing `main.py` (which needs Gemini credentials).
- **Library helper:** the `/videos` listing moves from `main.py` into `services/video_library.py` for the same reason.

---

### Task 1: Run context and LLM call recorder

**Files:**
- Create: `backend/services/run_context.py`, `backend/services/llm_recorder.py`
- Test: `backend/tests/test_run_context.py`, `backend/tests/test_llm_recorder.py`

**Interfaces:**
- Consumes: nothing.
- Produces (`services.run_context`): `ProgressReporter` and `CallRecorder` protocols, `NullProgress`, `RunContext(recorder, progress)`, `run_scope(run)` (context manager), `current_run() -> RunContext | None`, `llm_step(label)` (context manager), `current_label() -> str`, `report_stage(key, detail=None)`, `report_section(number, total, title, path, activity)`, `bind_run_directory(path)`. All `report_*`/`bind_*` helpers are no-ops without an active run.
- Produces (`services.llm_recorder`): `fence(text, language="")`, `render_markdown(payload) -> str`, `LLMCallRecorder(request_text, fallback_root=None)` with `.add(...)`, `.bind_directory(path)`, `.finish(status, error=None)`, `.calls`, `.directory`, `.run_id`; `RecordingLLM(inner)` with `generate` and `generate_structured`.

- [ ] **Step 1: Write the failing tests for the run context**

Create `backend/tests/test_run_context.py`:

```python
import threading
from pathlib import Path

from services.run_context import (
    NullProgress,
    RunContext,
    bind_run_directory,
    current_label,
    current_run,
    llm_step,
    report_section,
    report_stage,
    run_scope,
)


class Progress:
    def __init__(self):
        self.events = []

    def stage(self, key, detail=None):
        self.events.append(("stage", key, detail))

    def section(self, number, total, title, path, activity):
        self.events.append(("section", number, total, title, path, activity))


class Recorder:
    def __init__(self):
        self.bound = []

    def bind_directory(self, directory):
        self.bound.append(directory)


def test_helpers_do_nothing_without_a_run():
    report_stage("analyze")
    report_section(1, 2, "Intro", "codegen", "rendering scene")
    bind_run_directory(Path("x"))

    assert current_run() is None
    assert current_label() == "unlabelled"


def test_helpers_forward_to_the_active_run():
    progress, recorder = Progress(), Recorder()

    with run_scope(RunContext(recorder, progress)):
        report_stage("plan", "detail")
        report_section(2, 5, "How", "trace", "narrating")
        bind_run_directory(Path("out"))

    assert progress.events == [("stage", "plan", "detail"), ("section", 2, 5, "How", "trace", "narrating")]
    assert recorder.bound == [Path("out")]
    assert current_run() is None


def test_labels_nest_and_unwind():
    with llm_step("section 2"):
        assert current_label() == "section 2"
        with llm_step("storyboard"):
            assert current_label() == "section 2 · storyboard"
        assert current_label() == "section 2"

    assert current_label() == "unlabelled"


def test_a_run_in_another_thread_does_not_leak_into_this_one():
    seen = {}
    entered, release = threading.Event(), threading.Event()

    def worker():
        with run_scope(RunContext(Recorder(), NullProgress())):
            with llm_step("worker"):
                entered.set()
                release.wait(timeout=5)

    thread = threading.Thread(target=worker)
    thread.start()
    entered.wait(timeout=5)
    seen["run"] = current_run()
    seen["label"] = current_label()
    release.set()
    thread.join()

    assert seen == {"run": None, "label": "unlabelled"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_run_context.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'services.run_context'`.

- [ ] **Step 3: Implement the run context**

Create `backend/services/run_context.py`:

```python
import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol


class ProgressReporter(Protocol):
    def stage(self, key: str, detail: str | None = None) -> None:
        ...

    def section(self, number: int, total: int, title: str, path: str, activity: str) -> None:
        ...


class CallRecorder(Protocol):
    def bind_directory(self, directory: Path) -> None:
        ...


class NullProgress:
    def stage(self, key: str, detail: str | None = None) -> None:
        pass

    def section(self, number: int, total: int, title: str, path: str, activity: str) -> None:
        pass


@dataclass
class RunContext:
    recorder: CallRecorder
    progress: ProgressReporter


# Context variables are per thread, so a pipeline running in a job thread never
# sees (or disturbs) the run of another thread.
_current: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar("run_context", default=None)
_labels: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("llm_step_labels", default=())


def current_run() -> RunContext | None:
    return _current.get()


@contextmanager
def run_scope(run: RunContext) -> Iterator[RunContext]:
    token = _current.set(run)
    try:
        yield run
    finally:
        _current.reset(token)


@contextmanager
def llm_step(label: str) -> Iterator[None]:
    token = _labels.set(_labels.get() + (label,))
    try:
        yield
    finally:
        _labels.reset(token)


def current_label() -> str:
    return " · ".join(_labels.get()) or "unlabelled"


def report_stage(key: str, detail: str | None = None) -> None:
    run = current_run()
    if run is not None:
        run.progress.stage(key, detail)


def report_section(number: int, total: int, title: str, path: str, activity: str) -> None:
    run = current_run()
    if run is not None:
        run.progress.section(number, total, title, path, activity)


def bind_run_directory(directory: Path) -> None:
    run = current_run()
    if run is not None:
        run.recorder.bind_directory(directory)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_run_context.py -q`
Expected: 4 passed.

- [ ] **Step 5: Write the failing tests for the recorder**

Create `backend/tests/test_llm_recorder.py`:

```python
import json

import pytest
from pydantic import BaseModel

from fakes import FakeLLM
from services.llm_recorder import LLMCallRecorder, RecordingLLM, fence, render_markdown
from services.run_context import NullProgress, RunContext, llm_step, run_scope


class Answer(BaseModel):
    text: str


class TextLLM:
    model = "fake-model"

    def generate(self, prompt):
        return f"echo: {prompt}"


def make_run(tmp_path=None, request="Explain binary search"):
    recorder = LLMCallRecorder(request, fallback_root=tmp_path)
    return recorder, RunContext(recorder, NullProgress())


def test_structured_call_is_recorded_with_label_prompt_and_output():
    recorder, run = make_run()
    llm = RecordingLLM(FakeLLM([{"text": "hello"}]))

    with run_scope(run), llm_step("lesson analyzer"):
        result = llm.generate_structured("PROMPT", Answer)

    assert result == Answer(text="hello")
    call = recorder.calls[0]
    assert call["seq"] == 1
    assert call["label"] == "lesson analyzer"
    assert call["kind"] == "structured"
    assert call["schema"] == "Answer"
    assert call["prompt"] == "PROMPT"
    assert call["output"] == {"text": "hello"}
    assert call["error"] is None
    assert call["duration_seconds"] >= 0
    assert call["started_at"].endswith("+00:00")


def test_text_call_is_recorded():
    recorder, run = make_run()

    with run_scope(run):
        assert RecordingLLM(TextLLM()).generate("hi") == "echo: hi"

    assert recorder.calls[0]["kind"] == "text"
    assert recorder.calls[0]["schema"] is None
    assert recorder.calls[0]["output"] == "echo: hi"


def test_failed_call_is_recorded_and_reraised():
    recorder, run = make_run()
    llm = RecordingLLM(FakeLLM([RuntimeError("quota")]))

    with run_scope(run), llm_step("planner"):
        with pytest.raises(RuntimeError, match="quota"):
            llm.generate_structured("P", Answer)

    assert recorder.calls[0]["output"] is None
    assert recorder.calls[0]["error"] == "RuntimeError: quota"


def test_repeated_labels_are_numbered():
    recorder, run = make_run()
    llm = RecordingLLM(FakeLLM([{"text": "a"}, {"text": "b"}, {"text": "c"}]))

    with run_scope(run), llm_step("codegen"):
        for _ in range(3):
            llm.generate_structured("P", Answer)

    assert [c["label"] for c in recorder.calls] == ["codegen", "codegen #2", "codegen #3"]
    assert [c["seq"] for c in recorder.calls] == [1, 2, 3]


def test_without_a_run_the_call_passes_through_unrecorded():
    llm = RecordingLLM(FakeLLM([{"text": "x"}]))

    assert llm.generate_structured("P", Answer) == Answer(text="x")


def test_other_attributes_are_delegated_to_the_inner_llm():
    assert RecordingLLM(TextLLM()).model == "fake-model"


def test_bind_directory_writes_both_files_and_rewrites_after_each_call(tmp_path):
    recorder, run = make_run()
    llm = RecordingLLM(FakeLLM([{"text": "a"}, {"text": "b"}]))
    folder = tmp_path / "run1"

    with run_scope(run):
        llm.generate_structured("P1", Answer)         # before the folder exists
        recorder.bind_directory(folder)
        first = json.loads((folder / "llm_calls.json").read_text(encoding="utf-8"))
        llm.generate_structured("P2", Answer)

    second = json.loads((folder / "llm_calls.json").read_text(encoding="utf-8"))
    assert [c["prompt"] for c in first["calls"]] == ["P1"]
    assert [c["prompt"] for c in second["calls"]] == ["P1", "P2"]
    assert second["status"] == "running"
    assert second["request"] == "Explain binary search"
    assert (folder / "llm_calls.md").exists()


def test_finish_records_status_and_error(tmp_path):
    recorder, _ = make_run()
    recorder.bind_directory(tmp_path / "run")

    recorder.finish("failed", "ValueError: boom")

    data = json.loads((tmp_path / "run" / "llm_calls.json").read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["error"] == "ValueError: boom"
    assert data["finished_at"] is not None
    assert "ValueError: boom" in (tmp_path / "run" / "llm_calls.md").read_text(encoding="utf-8")


def test_failed_run_without_a_folder_is_written_to_the_fallback_location(tmp_path):
    recorder, _ = make_run(tmp_path)

    recorder.finish("failed", "APIConnectionError: getaddrinfo failed")

    path = tmp_path / "_failed" / recorder.run_id / "llm_calls.json"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "failed"


def test_completed_run_without_a_folder_writes_nothing(tmp_path):
    recorder, _ = make_run(tmp_path)

    recorder.finish("completed")

    assert not (tmp_path / "_failed").exists()


def test_a_prompt_with_backticks_pipes_and_unicode_keeps_the_markdown_valid(tmp_path):
    recorder, run = make_run()
    prompt = "Example:\n```python\nprint('é → ✓')\n```\nend"
    llm = RecordingLLM(FakeLLM([{"text": "a | b"}]))

    with run_scope(run), llm_step("section 1 | weird"):
        llm.generate_structured(prompt, Answer)
    recorder.bind_directory(tmp_path)

    markdown = (tmp_path / "llm_calls.md").read_text(encoding="utf-8")
    assert "````\n" + prompt + "\n````" in markdown      # fence is longer than the ``` inside
    assert "section 1 \\| weird" in markdown             # pipe escaped in the index table
    assert "é → ✓" in markdown


def test_unwritable_log_directory_does_not_break_the_pipeline(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    recorder, run = make_run()
    llm = RecordingLLM(FakeLLM([{"text": "a"}]))

    with run_scope(run):
        recorder.bind_directory(blocker / "sub")            # parent is a file: mkdir fails
        assert llm.generate_structured("P", Answer) == Answer(text="a")

    recorder.finish("completed")
    assert len(recorder.calls) == 1


def test_fence_is_longer_than_any_backtick_run_inside():
    assert fence("plain") == "```\nplain\n```"
    assert fence("a ```` b", "json") == "`````json\na ```` b\n`````"


def test_markdown_has_an_index_and_a_section_per_call():
    payload = {
        "request": "Teach X", "started_at": "t0", "finished_at": "t1", "status": "completed", "error": None,
        "calls": [
            {"seq": 1, "label": "planner", "kind": "structured", "schema": "LessonPlan",
             "started_at": "t", "duration_seconds": 1.5, "prompt": "P", "output": {"a": 1}, "error": None},
            {"seq": 2, "label": "router", "kind": "structured", "schema": "RoutePlan",
             "started_at": "t", "duration_seconds": 0.5, "prompt": "Q", "output": None, "error": "X: y"},
        ],
    }

    markdown = render_markdown(payload)

    assert "| 1 | planner | LessonPlan | 1.5 | ok |" in markdown
    assert "| 2 | router | RoutePlan | 0.5 | error |" in markdown
    assert "### 1. planner" in markdown and "### 2. router" in markdown
    assert '"a": 1' in markdown
    assert "X: y" in markdown
    assert "Calls: 2 · total LLM time 2.0 s" in markdown
```

- [ ] **Step 6: Run to verify it fails**

Run: `python -m pytest tests/test_llm_recorder.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'services.llm_recorder'`.

- [ ] **Step 7: Implement the recorder**

Create `backend/services/llm_recorder.py`:

```python
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel

from services.run_context import current_label, current_run


logger = logging.getLogger(__name__)

JSON_NAME = "llm_calls.json"
MARKDOWN_NAME = "llm_calls.md"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fence(text: str, language: str = "") -> str:
    """Fenced block whose fence is longer than any backtick run inside the text."""
    longest = run = 0
    for char in text:
        run = run + 1 if char == "`" else 0
        longest = max(longest, run)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{language}\n{text}\n{ticks}"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(payload: dict[str, Any]) -> str:
    calls = payload["calls"]
    total = sum(call["duration_seconds"] for call in calls)
    status = payload["status"] + (f" — {payload['error']}" if payload.get("error") else "")

    lines = [
        "# LLM calls",
        "",
        f"- Status: {status}",
        f"- Started: {payload['started_at']}",
        f"- Finished: {payload['finished_at'] or '—'}",
        f"- Calls: {len(calls)} · total LLM time {total:.1f} s",
        "",
        "## Request",
        "",
        fence(payload["request"]),
        "",
        "## Index",
        "",
        "| # | Step | Schema | Seconds | Result |",
        "|---|---|---|---|---|",
    ]
    for call in calls:
        result = "error" if call["error"] else "ok"
        lines.append(
            f"| {call['seq']} | {_cell(call['label'])} | {call['schema'] or 'text'} "
            f"| {call['duration_seconds']} | {result} |"
        )

    lines += ["", "## Calls"]
    for call in calls:
        output = call["output"]
        if call["error"]:
            outcome = ["**Error**", "", fence(call["error"])]
        elif isinstance(output, str):
            outcome = ["**Output**", "", fence(output)]
        else:
            outcome = ["**Output**", "", fence(json.dumps(output, indent=2, ensure_ascii=False, default=str), "json")]
        lines += [
            "",
            f"### {call['seq']}. {call['label']}",
            "",
            f"Schema: {call['schema'] or 'text'} · started {call['started_at']} · {call['duration_seconds']} s",
            "",
            "**Prompt**",
            "",
            fence(call["prompt"]),
            "",
            *outcome,
        ]
    return "\n".join(lines) + "\n"


class LLMCallRecorder:
    """Collects every LLM call of one run and keeps llm_calls.json / llm_calls.md up to date."""

    def __init__(self, request_text: str, fallback_root: Path | None = None) -> None:
        self.request_text = request_text
        self.fallback_root = fallback_root
        self.run_id = uuid4().hex[:8]
        self.directory: Path | None = None
        self.status = "running"
        self.error: str | None = None
        self.started_at = _now()
        self.finished_at: str | None = None
        self.calls: list[dict[str, Any]] = []
        self._label_counts: dict[str, int] = {}
        self._lock = threading.RLock()

    def add(
        self,
        *,
        label: str,
        kind: str,
        schema: str | None,
        started_at: str,
        duration_seconds: float,
        prompt: str,
        output: Any,
        error: str | None,
    ) -> None:
        with self._lock:
            count = self._label_counts.get(label, 0) + 1
            self._label_counts[label] = count
            self.calls.append({
                "seq": len(self.calls) + 1,
                "label": label if count == 1 else f"{label} #{count}",
                "kind": kind,
                "schema": schema,
                "started_at": started_at,
                "duration_seconds": duration_seconds,
                "prompt": prompt,
                "output": output,
                "error": error,
            })
            self._write()

    def bind_directory(self, directory: Path) -> None:
        with self._lock:
            self.directory = Path(directory)
            self._write()

    def finish(self, status: str, error: str | None = None) -> None:
        with self._lock:
            self.status = status
            self.error = error
            self.finished_at = _now()
            if self.directory is None and status == "failed" and self.fallback_root is not None:
                self.directory = Path(self.fallback_root) / "_failed" / self.run_id
            self._write()

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "request": self.request_text,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "status": self.status,
                "error": self.error,
                "calls": list(self.calls),
            }

    def _write(self) -> None:
        if self.directory is None:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = self.to_dict()
            (self.directory / JSON_NAME).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
            )
            (self.directory / MARKDOWN_NAME).write_text(render_markdown(payload), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not write the LLM call log to %s: %s", self.directory, exc)


def _dump(result: Any) -> Any:
    return result.model_dump(mode="json") if isinstance(result, BaseModel) else result


class RecordingLLM:
    """Wraps an LLM service and records every call made inside an active run."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__dict__["_inner"], name)

    def generate(self, prompt: str) -> str:
        return self._record("text", None, prompt, lambda: self._inner.generate(prompt), lambda result: result)

    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        return self._record(
            "structured",
            response_schema.__name__,
            prompt,
            lambda: self._inner.generate_structured(prompt, response_schema),
            _dump,
        )

    def _record(
        self,
        kind: str,
        schema: str | None,
        prompt: str,
        call: Callable[[], Any],
        to_output: Callable[[Any], Any],
    ) -> Any:
        run = current_run()
        recorder = getattr(run, "recorder", None)
        if recorder is None or not hasattr(recorder, "add"):
            return call()

        label = current_label()
        started_at = _now()
        begin = time.perf_counter()
        try:
            result = call()
        except Exception as exc:
            recorder.add(
                label=label, kind=kind, schema=schema, started_at=started_at,
                duration_seconds=round(time.perf_counter() - begin, 2),
                prompt=prompt, output=None, error=f"{type(exc).__name__}: {exc}",
            )
            raise

        try:
            output = to_output(result)
        except Exception:
            output = repr(result)
        recorder.add(
            label=label, kind=kind, schema=schema, started_at=started_at,
            duration_seconds=round(time.perf_counter() - begin, 2),
            prompt=prompt, output=output, error=None,
        )
        return result
```

- [ ] **Step 8: Run to verify it passes**

Run: `python -m pytest tests/test_run_context.py tests/test_llm_recorder.py -q`
Expected: all pass (4 + 14). If the backtick test fails, check that `fence` is used for the prompt and that `longest + 1` is at least 4 for a prompt containing three backticks.

- [ ] **Step 9: Commit**

```bash
git add services/run_context.py services/llm_recorder.py tests/test_run_context.py tests/test_llm_recorder.py
git commit -m "Add run context and LLM call recorder" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Instrument the pipeline (stages, labels, run folder, `video_url`)

**Files:**
- Modify: `backend/schemas/demo.py`, `backend/services/demo_video_service.py`, `backend/animation/section_animator.py`
- Test: `backend/tests/test_demo_video_service.py` (append), `backend/tests/test_section_animator.py` (append), `backend/tests/test_end_to_end.py` (extend)

**Interfaces:**
- Consumes (Task 1): `report_stage`, `report_section`, `llm_step`, `bind_run_directory`, `run_scope`, `RunContext`, `LLMCallRecorder`, `RecordingLLM`.
- Produces:
  - `DemoVideoResponse.video_url: str | None = None` (`"/media/<run folder>/lesson_demo.mp4"`).
  - Stage keys reported by the pipeline, in order: `analyze`, `knowledge` (detail `"skipped"` when there is no agent), `plan`, `script`, `route` (reported by `SectionAnimator.animate`), `animate` (via `report_section`), `assemble`.
  - LLM step labels: `lesson analyzer`, `knowledge base`, `lesson planner`, `script writer`, `router`, then per section `section N · narrator` / `section N · storyboard` / `section N · codegen` (N is 1-based).
  - `SectionAnimator` private methods `_animate_section`, `_trace_section`, `_codegen_section` gain a trailing optional parameter `announce: Callable[[str], None]`; `animate()` is unchanged for callers.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_demo_video_service.py` (add `import json`, `from services.llm_recorder import LLMCallRecorder`, and `from services.run_context import RunContext, run_scope` to the imports at the top):

```python
class CapturingProgress:
    def __init__(self):
        self.stages = []

    def stage(self, key, detail=None):
        self.stages.append((key, detail))

    def section(self, number, total, title, path, activity):
        pass


def _mux(video, out, audio, subtitles):
    out.write_bytes(b"mp4")
    return out


def _service(tmp_path, animator=None):
    return DemoVideoService(
        lesson_analyzer_service=Analyzer(),
        lesson_planner_service=Planner(),
        script_writer_service=Writer(),
        section_animator=animator or Animator(),
        output_root=tmp_path,
        concat_clips=lambda paths, out: out,
        build_audio=lambda paths, durations, out: out,
        mux=_mux,
    )


def test_reports_the_real_stages_in_order_and_binds_the_run_folder(tmp_path):
    progress = CapturingProgress()
    recorder = LLMCallRecorder("Explain binary search")

    with run_scope(RunContext(recorder, progress)):
        response = _service(tmp_path).generate_demo_video(UserLessonRequest(request="Explain binary search"))

    assert progress.stages == [
        ("analyze", None),
        ("knowledge", "skipped"),
        ("plan", None),
        ("script", None),
        ("assemble", None),
    ]
    assert recorder.directory == Path(response.output_dir)
    assert (Path(response.output_dir) / "llm_calls.json").exists()


def test_response_carries_a_media_url_relative_to_the_output_root(tmp_path):
    response = _service(tmp_path).generate_demo_video(UserLessonRequest(request="Explain binary search"))

    folder = Path(response.output_dir).name
    assert response.video_url == f"/media/{folder}/lesson_demo.mp4"


def test_service_still_works_without_a_run_context(tmp_path):
    response = _service(tmp_path).generate_demo_video(UserLessonRequest(request="Explain binary search"))

    assert response.video_path.endswith("lesson_demo.mp4")
    assert not (Path(response.output_dir) / "llm_calls.json").exists()
```

Append to `backend/tests/test_section_animator.py` (add `from animation.storyboard import Storyboard`, `from fakes import FakeLLM`, `from services.llm_recorder import LLMCallRecorder, RecordingLLM` and `from services.run_context import RunContext, run_scope` to the imports at the top):

```python
class SectionProgress:
    def __init__(self):
        self.stages = []
        self.sections = []

    def stage(self, key, detail=None):
        self.stages.append(key)

    def section(self, number, total, title, path, activity):
        self.sections.append((number, total, title, path, activity))


class LabelledStoryboarder(FakeStoryboarder):
    """Storyboarder that makes a real recorded LLM call, so labels can be checked."""

    def __init__(self, llm):
        super().__init__()
        self.llm = llm

    def plan(self, section):
        self.llm.generate_structured("storyboard prompt", Storyboard)
        return super().plan(section)


def test_codegen_section_reports_progress_and_labels_its_llm_calls(tmp_path):
    progress, recorder = SectionProgress(), LLMCallRecorder("req")
    llm = RecordingLLM(FakeLLM([{"beats": [{"sentence_count": 2, "visual": "v"}]}]))
    animator, _, _, _ = make([CODEGEN_ROUTE], storyboarder=LabelledStoryboarder(llm))

    with run_scope(RunContext(recorder, progress)):
        animator.animate([TEXT_SECTION], tmp_path)

    assert progress.stages == ["route"]
    assert [s[:4] for s in progress.sections][0] == (1, 1, "Why", "codegen")
    assert [s[4] for s in progress.sections] == ["starting", "planning beats", "narrating", "rendering scene"]
    assert recorder.calls[0]["label"] == "section 1 · storyboard"


def test_trace_section_reports_its_activities(tmp_path):
    progress = SectionProgress()
    animator, _, _, _ = make([TRACE_ROUTE])

    with run_scope(RunContext(LLMCallRecorder("req"), progress)):
        animator.animate([TRACE_SECTION], tmp_path)

    assert [s[4] for s in progress.sections] == ["starting", "narrating steps", "animating algorithm trace"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_demo_video_service.py tests/test_section_animator.py -q`
Expected: failures such as `assert progress.stages == [...]` (empty list), `AttributeError: ... video_url`, and the section progress assertions failing. The old tests still pass.

- [ ] **Step 3: Add `video_url` to the response**

In `backend/schemas/demo.py` add this field directly after `video_path`:

```python
    video_url: str | None = Field(
        default=None,
        description="URL path under /media where the finished MP4 is served.",
    )
```

- [ ] **Step 4: Instrument `DemoVideoService`**

In `backend/services/demo_video_service.py` add to the imports:

```python
from services.run_context import bind_run_directory, llm_step, report_stage
```

Replace the start of `generate_demo_video` (everything from the first `lesson_request = ...` line to the line `clip_durations = [...]`) with:

```python
        report_stage("analyze")
        with llm_step("lesson analyzer"):
            lesson_request = self.lesson_analyzer_service.analyze_lesson_request(request)
        lesson_request = self._normalize_lesson_request_topic(request, lesson_request)

        knowledge_base = None
        qc_warnings: list[str] = []
        if self.knowledge_agent_service is not None:
            report_stage("knowledge")
            with llm_step("knowledge base"):
                knowledge_base = self.knowledge_agent_service.create_knowledge_base(
                    lesson_request
                )
            qc_warnings = self._build_qc_warnings(knowledge_base)
        else:
            report_stage("knowledge", "skipped")

        report_stage("plan")
        with llm_step("lesson planner"):
            lesson_plan = self.lesson_planner_service.create_lesson_plan(lesson_request)
        report_stage("script")
        with llm_step("script writer"):
            lesson_script = self.script_writer_service.create_lesson_script(
                lesson_request,
                lesson_plan,
            )

        sections = build_render_sections(lesson_script)
        if not sections:
            raise ValueError("Lesson script has no narration to render.")

        output_dir = self._create_output_dir(lesson_request.topic)
        bind_run_directory(output_dir)
        clips, animation_warnings = self.section_animator.animate(sections, output_dir)
        qc_warnings.extend(animation_warnings)

        report_stage("assemble")
        clip_durations = [sum(clip.segment_durations) for clip in clips]
```

In the `DemoVideoResponse(...)` construction at the end of the method add `video_url=self._media_url(video_path),` after `video_path=str(video_path),`, and add this method to the class (next to `_create_output_dir`):

```python
    def _media_url(self, video_path: Path) -> str | None:
        try:
            relative = Path(video_path).resolve().relative_to(self.output_root.resolve())
        except ValueError:
            return None
        return "/media/" + relative.as_posix()
```

- [ ] **Step 5: Instrument `SectionAnimator`**

In `backend/animation/section_animator.py` add to the imports:

```python
from services.run_context import llm_step, report_section, report_stage
```

Add below the `SectionRenderError` class:

```python
def _no_announce(activity: str) -> None:
    pass
```

Replace `animate` and `_animate_section` with:

```python
    def animate(self, sections: list[RenderSection], output_dir: Path) -> tuple[list[SectionClip], list[str]]:
        report_stage("route")
        with llm_step("router"):
            routing = self.router.route(sections)
        warnings = list(routing.warnings)
        clips: list[SectionClip] = []
        total = len(sections)

        for number, (section, route) in enumerate(zip(sections, routing.routes), start=1):
            def announce(activity: str, number: int = number, section: RenderSection = section, path: str = route.path) -> None:
                report_section(number, total, section.title, path, activity)

            announce("starting")
            with llm_step(f"section {number}"):
                clip = self._animate_section(section, route, output_dir, announce)
            clips.append(clip)
            warnings.extend(clip.warnings)

        return clips, warnings

    def _animate_section(
        self,
        section: RenderSection,
        route: ResolvedRoute,
        output_dir: Path,
        announce: Callable[[str], None] = _no_announce,
    ) -> SectionClip:
        section_dir = output_dir / "sections" / f"section_{section.index:02d}"
        warnings: list[str] = []

        if route.path == "trace":
            try:
                return self._trace_section(section, route, section_dir, announce)
            except Exception as exc:
                warnings.append(f"Section '{section.title}': trace animation failed ({exc}); using generated animation.")

        return self._codegen_section(section, section_dir, output_dir, warnings, announce)
```

Change the `_trace_section` signature to `def _trace_section(self, section: RenderSection, route: ResolvedRoute, section_dir: Path, announce: Callable[[str], None] = _no_announce) -> SectionClip:` and replace these two snippets inside it:

```python
        steps = tracer.trace(route.inputs)
        segments, warnings = self.narrator.narrate(section, steps)
```
with
```python
        steps = tracer.trace(route.inputs)
        announce("narrating steps")
        with llm_step("narrator"):
            segments, warnings = self.narrator.narrate(section, steps)
```
and
```python
        section_audio = self.build_audio(segment_paths, segment_totals, section_dir / "narration.m4a")
        raw = self.template_renderer.render(
```
with
```python
        section_audio = self.build_audio(segment_paths, segment_totals, section_dir / "narration.m4a")
        announce("animating algorithm trace")
        raw = self.template_renderer.render(
```

Change the `_codegen_section` signature to add a final parameter `announce: Callable[[str], None] = _no_announce`, then replace these snippets inside it:

```python
        beats, plan_warnings = self.storyboarder.plan(section)
        warnings.extend(plan_warnings)
```
with
```python
        announce("planning beats")
        with llm_step("storyboard"):
            beats, plan_warnings = self.storyboarder.plan(section)
        warnings.extend(plan_warnings)
        announce("narrating")
```
and the render call inside the `try:` block
```python
            result = self.codegen_renderer.render(
                section,
                beats,
                durations,
                section_dir / "codegen_work",
                section_dir / "codegen_raw.mp4",
                output_dir / "codegen",
            )
```
with
```python
            announce("rendering scene")
            with llm_step("codegen"):
                result = self.codegen_renderer.render(
                    section,
                    beats,
                    durations,
                    section_dir / "codegen_work",
                    section_dir / "codegen_raw.mp4",
                    output_dir / "codegen",
                )
```

- [ ] **Step 6: Run to verify the unit tests pass**

Run: `python -m pytest tests/test_demo_video_service.py tests/test_section_animator.py -q`
Expected: all pass, including the pre-existing tests (the existing fakes ignore the new optional behaviour).

- [ ] **Step 7: Extend the end-to-end test**

In `backend/tests/test_end_to_end.py` add `import json`, `from pathlib import Path` and the imports
```python
from services.llm_recorder import LLMCallRecorder, RecordingLLM
from services.run_context import NullProgress, RunContext, run_scope
```
Change `llm = FakeLLM([` in `test_full_lesson_renders_with_mixed_paths` to `fake_llm = FakeLLM([` and add `llm = RecordingLLM(fake_llm)` on the line after the closing `])` of that list. Replace the final part of the test (from `response = service.generate_demo_video(...)` to the end) with:

```python
    recorder = LLMCallRecorder("Explain binary search")
    with run_scope(RunContext(recorder, NullProgress())):
        response = service.generate_demo_video(UserLessonRequest(request="Explain binary search"))
    recorder.finish("completed")

    assert [s.path_used for s in response.sections] == ["codegen", "trace", "codegen"]
    assert response.qc_warnings == []
    assert probe_duration(response.video_path) == pytest.approx(sum(response.scene_durations), abs=0.5)

    run_dir = Path(response.output_dir)
    log = json.loads((run_dir / "llm_calls.json").read_text(encoding="utf-8"))
    assert log["status"] == "completed"
    assert [c["label"] for c in log["calls"]] == [
        "router",
        "section 1 · storyboard",
        "section 1 · codegen",
        "section 2 · narrator",
        "section 3 · storyboard",
        "section 3 · codegen",
    ]
    assert len(fake_llm.prompts) == 6
    assert (run_dir / "llm_calls.md").exists()
```

- [ ] **Step 8: Run to verify the slow end-to-end test passes**

Run: `python -m pytest tests/test_end_to_end.py -q -m slow`
Expected: 1 passed (about 25 s).

- [ ] **Step 9: Commit**

```bash
git add schemas/demo.py services/demo_video_service.py animation/section_animator.py tests/test_demo_video_service.py tests/test_section_animator.py tests/test_end_to_end.py
git commit -m "Report real pipeline stages and label every LLM call" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Jobs: progress state, `JobService`, endpoints, `main.py` wiring

**Files:**
- Create: `backend/schemas/job.py`, `backend/services/job_service.py`, `backend/services/jobs_router.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_job_service.py`

**Interfaces:**
- Consumes (Tasks 1-2): `RunContext`, `run_scope`, `NullProgress`, `LLMCallRecorder`, `report_stage`, `report_section`, `bind_run_directory`; `DemoVideoResponse`.
- Produces:
  - `schemas.job`: `JobStage(key, label, state, detail)`, `JobSection(index, total, title, path, activity)`, `JobError(stage, message)`, `JobStatus(job_id, status, elapsed_seconds, stages, section, result, error)`, `JobCreated(job_id)`.
  - `services.job_service`: `STAGES` (list of `(key, label)`), `JobProgress(job_id)` implementing the `ProgressReporter` protocol plus `.complete(result)`, `.fail(exc)`, `.snapshot() -> JobStatus`; `JobService(pipeline, output_root)` with `.start(request) -> str`, `.get(job_id) -> JobStatus | None`, `.wait(job_id, timeout=None)`, `.run_blocking(request) -> DemoVideoResponse`.
  - `services.jobs_router.create_jobs_router(job_service) -> APIRouter` with `POST /lesson/jobs` (202, `JobCreated`) and `GET /lesson/jobs/{job_id}` (`JobStatus`, 404 when unknown).
  - `pipeline` is any callable `(UserLessonRequest) -> DemoVideoResponse`; `main.py` passes `demo_video_service.generate_demo_video`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_job_service.py`:

```python
import json
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

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


def run_to_end(service, pipeline_request=REQUEST):
    job_id = service.start(pipeline_request)
    service.wait(job_id, timeout=10)
    return service.get(job_id)


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
    job_id = service.start(REQUEST)
    assert reached.wait(timeout=10)

    status = service.get(job_id)
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
    assert service.get(job_id).status == "completed"


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

    def pipeline(request):
        name = request.request
        report_stage("analyze" if name == "A" else "plan")
        barrier.wait()                       # both pipelines are inside their run at the same time
        with lock, llm_step(f"step {name}"):
            llm.generate_structured(f"prompt {name}", Answer)
        bind_run_directory(tmp_path / name)
        return make_response(tmp_path / name)

    service = JobService(pipeline, tmp_path)
    job_a = service.start(UserLessonRequest(request="A"))
    job_b = service.start(UserLessonRequest(request="B"))
    service.wait(job_a, timeout=10)
    service.wait(job_b, timeout=10)

    log_a = json.loads((tmp_path / "A" / "llm_calls.json").read_text(encoding="utf-8"))
    log_b = json.loads((tmp_path / "B" / "llm_calls.json").read_text(encoding="utf-8"))
    assert [c["prompt"] for c in log_a["calls"]] == ["prompt A"]
    assert [c["prompt"] for c in log_b["calls"]] == ["prompt B"]
    assert [c["label"] for c in log_a["calls"]] == ["step A"]
    states_a = {s.key: s.state for s in service.get(job_a).stages}
    states_b = {s.key: s.state for s in service.get(job_b).stages}
    assert states_a["analyze"] == "done" and states_a["plan"] == "pending"
    assert states_b["plan"] == "done" and states_b["analyze"] == "done"   # earlier stages are closed when a later one is reported


def test_unknown_job_is_none(tmp_path):
    assert JobService(lambda request: make_response(), tmp_path).get("nope") is None


def test_run_blocking_returns_the_result_and_writes_the_log(tmp_path):
    folder = tmp_path / "run1"

    def pipeline(request):
        bind_run_directory(folder)
        return make_response(folder)

    result = JobService(pipeline, tmp_path).run_blocking(REQUEST)

    assert result.video_url == "/media/out/lesson_demo.mp4"
    assert json.loads((folder / "llm_calls.json").read_text(encoding="utf-8"))["status"] == "completed"


def test_run_blocking_reraises_and_logs_the_failure(tmp_path):
    def pipeline(request):
        raise RuntimeError("down")

    with pytest.raises(RuntimeError, match="down"):
        JobService(pipeline, tmp_path).run_blocking(REQUEST)

    logs = list((tmp_path / "_failed").glob("*/llm_calls.json"))
    assert json.loads(logs[0].read_text(encoding="utf-8"))["error"] == "RuntimeError: down"


def test_endpoints_create_and_poll_a_job(tmp_path):
    service = JobService(lambda request: make_response(), tmp_path)
    app = FastAPI()
    app.include_router(create_jobs_router(service))
    client = TestClient(app)

    created = client.post("/lesson/jobs", json={"request": "Explain binary search"})
    assert created.status_code == 202
    job_id = created.json()["job_id"]
    service.wait(job_id, timeout=10)

    polled = client.get(f"/lesson/jobs/{job_id}")
    body = polled.json()
    assert polled.status_code == 200
    assert body["status"] == "completed"
    assert [s["key"] for s in body["stages"]] == [key for key, _ in STAGES]
    assert body["result"]["video_url"] == "/media/out/lesson_demo.mp4"

    assert client.get("/lesson/jobs/unknown").status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_job_service.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'services.job_service'`.

- [ ] **Step 3: Implement the job schemas**

Create `backend/schemas/job.py`:

```python
from typing import Literal

from pydantic import BaseModel

from schemas.demo import DemoVideoResponse


StageState = Literal["pending", "current", "done", "failed"]


class JobStage(BaseModel):
    key: str
    label: str
    state: StageState
    detail: str | None = None


class JobSection(BaseModel):
    index: int
    total: int
    title: str
    path: str
    activity: str


class JobError(BaseModel):
    stage: str
    message: str


class JobStatus(BaseModel):
    job_id: str
    status: Literal["running", "completed", "failed"]
    elapsed_seconds: float
    stages: list[JobStage]
    section: JobSection | None = None
    result: DemoVideoResponse | None = None
    error: JobError | None = None


class JobCreated(BaseModel):
    job_id: str
```

- [ ] **Step 4: Implement `JobProgress` and `JobService`**

Create `backend/services/job_service.py`:

```python
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
    def __init__(self, pipeline: Pipeline, output_root: Path) -> None:
        self.pipeline = pipeline
        self.output_root = Path(output_root)
        self._jobs: dict[str, tuple[JobProgress, threading.Thread]] = {}
        self._lock = threading.Lock()

    def start(self, request: UserLessonRequest) -> str:
        job_id = uuid4().hex[:12]
        progress = JobProgress(job_id)
        thread = threading.Thread(target=self._run, args=(progress, request), daemon=True, name=f"job-{job_id}")
        with self._lock:
            self._jobs[job_id] = (progress, thread)
        thread.start()
        return job_id

    def get(self, job_id: str) -> JobStatus | None:
        with self._lock:
            entry = self._jobs.get(job_id)
        return entry[0].snapshot() if entry else None

    def wait(self, job_id: str, timeout: float | None = None) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
        if entry:
            entry[1].join(timeout)

    def run_blocking(self, request: UserLessonRequest) -> DemoVideoResponse:
        """Run the pipeline in the calling thread (the old endpoint), still writing the LLM log."""
        return self._execute(NullProgress(), request)

    def _run(self, progress: JobProgress, request: UserLessonRequest) -> None:
        try:
            result = self._execute(progress, request)
        except Exception as exc:
            logger.exception("Job %s failed", progress.job_id)
            progress.fail(exc)
            return
        progress.complete(result)

    def _execute(self, progress: NullProgress | JobProgress, request: UserLessonRequest) -> DemoVideoResponse:
        recorder = LLMCallRecorder(request.request, fallback_root=self.output_root)
        try:
            with run_scope(RunContext(recorder, progress)):
                result = self.pipeline(request)
        except Exception as exc:
            recorder.finish("failed", f"{type(exc).__name__}: {exc}")
            raise
        recorder.finish("completed")
        return result
```

- [ ] **Step 5: Implement the router factory**

Create `backend/services/jobs_router.py`:

```python
from fastapi import APIRouter, HTTPException

from schemas.job import JobCreated, JobStatus
from schemas.lesson import UserLessonRequest
from services.job_service import JobService


def create_jobs_router(job_service: JobService) -> APIRouter:
    router = APIRouter()

    @router.post("/lesson/jobs", response_model=JobCreated, status_code=202)
    def create_job(request: UserLessonRequest) -> JobCreated:
        return JobCreated(job_id=job_service.start(request))

    @router.get("/lesson/jobs/{job_id}", response_model=JobStatus)
    def get_job(job_id: str) -> JobStatus:
        status = job_service.get(job_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Unknown job")
        return status

    return router
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/test_job_service.py -q`
Expected: 9 passed. If `test_two_jobs_at_once...` hangs or fails on the barrier, the cause is a shared `run_scope` between threads: each job must call `run_scope` inside its own thread (as `_execute` does).

- [ ] **Step 7: Wire `main.py`**

In `backend/main.py`:
- Add imports: `from services.job_service import JobService`, `from services.jobs_router import create_jobs_router`, `from services.llm_recorder import RecordingLLM`.
- Replace `llm_service = LLMService()` with `llm_service = RecordingLLM(LLMService())`.
- After the `demo_video_service = DemoVideoService(...)` block add:

```python
job_service = JobService(demo_video_service.generate_demo_video, output_root)
app.include_router(create_jobs_router(job_service))
```
- Change the body of the `generate_demo_video` endpoint to `return job_service.run_blocking(request)`.

(The `/media` and `/videos` changes come in Task 4.)

- [ ] **Step 8: Verify `main.py` still imports and the suite is green**

Run: `python -c "import main; print([r.path for r in main.app.routes if 'jobs' in r.path])"` then `python -m pytest -q`
Expected: the first prints `['/lesson/jobs', '/lesson/jobs/{job_id}']`; the suite passes. (Import needs the `.env` with Gemini settings, as before.)

- [ ] **Step 9: Commit**

```bash
git add schemas/job.py services/job_service.py services/jobs_router.py main.py tests/test_job_service.py
git commit -m "Add job endpoints with real stage progress" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Video playback: `+faststart`, `Range` media route, library helper

**Files:**
- Create: `backend/rendering/faststart.py`, `backend/services/media_response.py`, `backend/services/video_library.py`
- Modify: `backend/rendering/video_renderer.py` (`mux_video`), `backend/main.py`
- Test: `backend/tests/test_faststart.py`, `backend/tests/test_media_response.py`, `backend/tests/test_video_library.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (`main.py` already has `output_root`).
- Produces:
  - `rendering.faststart`: `is_faststart(path: Path) -> bool` (true when the `moov` box precedes `mdat`, or when neither exists), `ensure_faststart(path: Path) -> bool` (remuxes in place with `-c copy -movflags +faststart`, keeps the file's mtime, returns whether the file is now fast; never raises).
  - `mux_video(...)` output has `moov` before `mdat`.
  - `services.media_response`: `parse_range(header, size) -> tuple[int, int] | None` (raises `RangeNotSatisfiable`), `create_media_router(output_root) -> APIRouter` serving `GET /media/{relative_path:path}`.
  - `services.video_library`: `list_videos(output_root, fix_video=ensure_faststart) -> list[dict]` (same keys as the old `/videos`: `id, title, filename, url, created_at, size_bytes`).

- [ ] **Step 1: Write the failing faststart and mux tests**

Create `backend/tests/test_faststart.py`:

```python
import os
import struct

import pytest

from animation.timing import probe_duration
from media_helpers import make_test_clip
from rendering.faststart import ensure_faststart, is_faststart
from rendering.video_renderer import mux_video


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def big_box(kind: bytes, payload: bytes = b"") -> bytes:
    # 64-bit "largesize" form: size field is 1, real size follows the type
    return struct.pack(">I4sQ", 1, kind, 16 + len(payload)) + payload


def write(tmp_path, *boxes):
    path = tmp_path / "v.mp4"
    path.write_bytes(b"".join(boxes))
    return path


def test_moov_before_mdat_is_faststart(tmp_path):
    assert is_faststart(write(tmp_path, box(b"ftyp", b"isom"), box(b"free"), box(b"moov", b"m"), box(b"mdat", b"d")))


def test_mdat_before_moov_is_not_faststart(tmp_path):
    assert not is_faststart(write(tmp_path, box(b"ftyp", b"isom"), box(b"free"), box(b"mdat", b"d"), box(b"moov", b"m")))


def test_large_boxes_are_skipped_correctly(tmp_path):
    assert is_faststart(write(tmp_path, box(b"ftyp"), big_box(b"free", b"x" * 20), box(b"moov"), big_box(b"mdat", b"d")))
    assert not is_faststart(write(tmp_path, box(b"ftyp"), big_box(b"mdat", b"d" * 20), box(b"moov")))


def test_file_without_media_boxes_or_with_garbage_counts_as_fast(tmp_path):
    assert is_faststart(write(tmp_path, box(b"ftyp")))
    assert is_faststart(write(tmp_path, b"abc"))


def test_ensure_faststart_leaves_a_fast_file_alone(tmp_path):
    path = write(tmp_path, box(b"ftyp"), box(b"moov"), box(b"mdat", b"d"))
    before = path.read_bytes()

    assert ensure_faststart(path) is True
    assert path.read_bytes() == before


def test_ensure_faststart_reports_failure_without_touching_a_broken_file(tmp_path):
    path = write(tmp_path, box(b"ftyp"), box(b"mdat", b"not really video"), box(b"moov"))
    before = path.read_bytes()

    assert ensure_faststart(path) is False
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["v.mp4"]       # no temp file left behind


@pytest.mark.slow
def test_ensure_faststart_moves_the_index_to_the_front_and_keeps_duration_and_mtime(tmp_path):
    clip = make_test_clip(tmp_path / "clip.mp4", 1.0)
    os.utime(clip, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    assert not is_faststart(clip)

    assert ensure_faststart(clip) is True

    assert is_faststart(clip)
    assert probe_duration(clip) == pytest.approx(1.0, abs=0.1)
    assert clip.stat().st_mtime_ns == 1_000_000_000_000_000_000


@pytest.mark.slow
def test_mux_video_writes_the_index_first(tmp_path):
    clip = make_test_clip(tmp_path / "clip.mp4", 1.0)

    out = mux_video(clip, tmp_path / "out.mp4")

    assert is_faststart(out)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_faststart.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'rendering.faststart'`.

- [ ] **Step 3: Implement `faststart.py` and change `mux_video`**

Create `backend/rendering/faststart.py`:

```python
import logging
import os
import struct
import subprocess
from pathlib import Path
from typing import Iterator


logger = logging.getLogger(__name__)


def _top_level_boxes(path: Path) -> Iterator[str]:
    total = path.stat().st_size
    with path.open("rb") as handle:
        offset = 0
        while offset + 8 <= total:
            handle.seek(offset)
            size, kind = struct.unpack(">I4s", handle.read(8))
            if size == 1:                      # 64-bit size follows the type
                size = struct.unpack(">Q", handle.read(8))[0]
            elif size == 0:                    # box runs to the end of the file
                size = total - offset
            if size < 8:
                return
            yield kind.decode("latin-1")
            offset += size


def is_faststart(path: Path) -> bool:
    """True when the moov index comes before the media data (or there is nothing to move)."""
    for kind in _top_level_boxes(path):
        if kind == "moov":
            return True
        if kind == "mdat":
            return False
    return True


def ensure_faststart(path: Path) -> bool:
    """Remux in place so browsers can read duration and seek before the whole file arrives."""
    temp = path.with_name(f"{path.stem}.faststart.tmp{path.suffix}")
    try:
        if is_faststart(path):
            return True
        original = path.stat()
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-c", "copy", "-movflags", "+faststart", str(temp)],
            check=True,
            capture_output=True,
        )
        os.replace(temp, path)
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
        return True
    except Exception as exc:
        logger.warning("Could not make %s fast-start: %s", path, exc)
        temp.unlink(missing_ok=True)
        return False
```

In `backend/rendering/video_renderer.py`, inside `mux_video`, change the final extend line

```python
    mux_command.extend(["-c:v", "copy", "-shortest", str(output_path)])
```
to
```python
    mux_command.extend(["-c:v", "copy", "-shortest", "-movflags", "+faststart", str(output_path)])
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_faststart.py -q` then `python -m pytest tests/test_faststart.py -q -m slow`
Expected: 6 fast tests pass; then both slow tests pass. If `test_ensure_faststart_reports_failure...` fails because ffmpeg unexpectedly accepts the file, replace its payload with random bytes; the point is that a failed remux leaves the original untouched and no temp file.

- [ ] **Step 5: Write the failing media route tests**

Create `backend/tests/test_media_response.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.media_response import create_media_router


DATA = bytes(range(256)) * 4        # 1024 bytes


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "output"
    (root / "run").mkdir(parents=True)
    (root / "run" / "lesson_demo.mp4").write_bytes(DATA)
    (root / "run" / "notes.json").write_text("{}", encoding="utf-8")
    (root / "run" / "empty.mp4").write_bytes(b"")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    app = FastAPI()
    app.include_router(create_media_router(root))
    return TestClient(app)


URL = "/media/run/lesson_demo.mp4"


def test_whole_file_is_served_with_range_support_advertised(client):
    response = client.get(URL)

    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "1024"


@pytest.mark.parametrize("header, expected, content_range", [
    ("bytes=0-99", DATA[:100], "bytes 0-99/1024"),
    ("bytes=100-", DATA[100:], "bytes 100-1023/1024"),
    ("bytes=-50", DATA[-50:], "bytes 974-1023/1024"),
    ("bytes=1000-5000", DATA[1000:], "bytes 1000-1023/1024"),
    ("bytes=0-0", DATA[:1], "bytes 0-0/1024"),
])
def test_ranges_return_partial_content(client, header, expected, content_range):
    response = client.get(URL, headers={"Range": header})

    assert response.status_code == 206
    assert response.content == expected
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(expected))


@pytest.mark.parametrize("header", ["bytes=2000-", "bytes=5-2", "bytes=-0", "bytes=1024-1030"])
def test_unsatisfiable_ranges_return_416(client, header):
    response = client.get(URL, headers={"Range": header})

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */1024"


@pytest.mark.parametrize("header", ["bytes=abc", "bytes=0-1,5-6", "items=0-5", "bytes=-"])
def test_unsupported_range_syntax_falls_back_to_the_whole_file(client, header):
    response = client.get(URL, headers={"Range": header})

    assert response.status_code == 200
    assert response.content == DATA


def test_other_file_types_get_their_own_content_type(client):
    response = client.get("/media/run/notes.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_empty_file_is_served_empty(client):
    response = client.get("/media/run/empty.mp4")

    assert response.status_code == 200
    assert response.content == b""


@pytest.mark.parametrize("path", [
    "/media/run/missing.mp4",
    "/media/run",
    "/media/../secret.txt",
    "/media/%2e%2e/secret.txt",
    "/media/run/../../secret.txt",
    "/media/run/%2e%2e/%2e%2e/secret.txt",
])
def test_missing_files_directories_and_traversal_are_404(client, path):
    assert client.get(path).status_code == 404
```

- [ ] **Step 6: Run to verify it fails**

Run: `python -m pytest tests/test_media_response.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'services.media_response'`.

- [ ] **Step 7: Implement the media route**

Create `backend/services/media_response.py`:

```python
import mimetypes
import re
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response, StreamingResponse


mimetypes.add_type("video/mp4", ".mp4")

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK_BYTES = 1024 * 1024


class RangeNotSatisfiable(Exception):
    pass


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Inclusive (start, end) for a single byte range; None means serve the whole file."""
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if match is None:
        return None                     # multiple ranges or other units: ignore the header
    first, last = match.groups()
    if first == "" and last == "":
        return None

    if first == "":                     # suffix range: the last N bytes
        length = int(last)
        if length == 0:
            raise RangeNotSatisfiable
        start, end = max(size - length, 0), size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1

    if size == 0 or start >= size or start > end:
        raise RangeNotSatisfiable
    return start, end


def _iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def create_media_router(output_root: Path) -> APIRouter:
    router = APIRouter()
    root = Path(output_root).resolve()

    @router.get("/media/{relative_path:path}")
    def serve_media(relative_path: str, range_header: str | None = Header(default=None, alias="range")):
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(status_code=404, detail="Not found")
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Not found")

        size = target.stat().st_size
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if size == 0:
            return Response(content=b"", media_type=media_type, headers={"Accept-Ranges": "bytes"})

        try:
            byte_range = parse_range(range_header, size)
        except RangeNotSatisfiable:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"})

        if byte_range is None:
            start, end, status = 0, size - 1, 200
        else:
            (start, end), status = byte_range, 206

        headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1)}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(_iter_file(target, start, end), status_code=status, media_type=media_type, headers=headers)

    return router
```

- [ ] **Step 8: Run to verify it passes**

Run: `python -m pytest tests/test_media_response.py -q`
Expected: all pass. If a traversal case returns 200, the `relative_to(root)` check is the cause; resolve both sides before comparing.

- [ ] **Step 9: Write the failing library tests**

Create `backend/tests/test_video_library.py`:

```python
import os

import pytest

from media_helpers import make_test_clip
from rendering.faststart import is_faststart
from services.video_library import list_videos


def make_video(root, name, mtime_ns, content=b"v"):
    folder = root / name
    folder.mkdir(parents=True)
    video = folder / "lesson_demo.mp4"
    video.write_bytes(content)
    os.utime(video, ns=(mtime_ns, mtime_ns))
    return video


def test_lists_only_finished_videos_newest_first(tmp_path):
    older = make_video(tmp_path, "binary-search-aaaa1111", 1_000_000_000)
    newer = make_video(tmp_path, "linear-search-bbbb2222", 2_000_000_000, b"vv")
    (newer.parent / "lesson_video_only.mp4").write_bytes(b"x")            # ignored
    (tmp_path / "_failed" / "abc").mkdir(parents=True)
    (tmp_path / "_failed" / "abc" / "llm_calls.json").write_text("{}", encoding="utf-8")

    videos = list_videos(tmp_path, fix_video=lambda path: True)

    assert [v["id"] for v in videos] == [
        "linear-search-bbbb2222/lesson_demo.mp4",
        "binary-search-aaaa1111/lesson_demo.mp4",
    ]
    first = videos[0]
    assert first["title"] == "Linear Search Bbbb2222"
    assert first["filename"] == "lesson_demo.mp4"
    assert first["url"] == "/media/linear-search-bbbb2222/lesson_demo.mp4"
    assert first["size_bytes"] == 2
    assert first["created_at"] == 2_000_000_000
    assert older.exists()


def test_every_listed_video_is_passed_to_the_fixer(tmp_path):
    a = make_video(tmp_path, "run-a", 1)
    b = make_video(tmp_path, "run-b", 2)
    seen = []

    list_videos(tmp_path, fix_video=lambda path: seen.append(path) or True)

    assert sorted(seen) == sorted([a, b])


def test_empty_output_root_lists_nothing(tmp_path):
    assert list_videos(tmp_path, fix_video=lambda path: True) == []


@pytest.mark.slow
def test_listing_makes_old_videos_fast_start_without_changing_their_order(tmp_path):
    old = tmp_path / "old-run"
    old.mkdir()
    clip = make_test_clip(old / "lesson_demo.mp4", 1.0)
    os.utime(clip, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))
    assert not is_faststart(clip)

    videos = list_videos(tmp_path)

    assert is_faststart(clip)
    assert videos[0]["created_at"] == 1_000_000_000_000_000_000
```

- [ ] **Step 10: Run to verify it fails**

Run: `python -m pytest tests/test_video_library.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'services.video_library'`.

- [ ] **Step 11: Implement the library helper**

Create `backend/services/video_library.py`:

```python
from pathlib import Path
from typing import Callable

from rendering.faststart import ensure_faststart


def list_videos(
    output_root: Path,
    fix_video: Callable[[Path], bool] = ensure_faststart,
) -> list[dict[str, str | int]]:
    videos: list[dict[str, str | int]] = []
    for video_path in Path(output_root).rglob("lesson_demo.mp4"):
        if not video_path.is_file():
            continue

        fix_video(video_path)                 # old runs were written without +faststart
        stat = video_path.stat()
        relative_path = video_path.relative_to(output_root).as_posix()
        parent_name = video_path.parent.name.replace("-", " ").replace("_", " ")
        title = parent_name.title() if parent_name else "Lesson Demo"
        videos.append(
            {
                "id": relative_path,
                "title": title,
                "filename": video_path.name,
                "url": f"/media/{relative_path}",
                "created_at": stat.st_mtime_ns,
                "size_bytes": stat.st_size,
            }
        )

    return sorted(videos, key=lambda video: int(video["created_at"]), reverse=True)
```

- [ ] **Step 12: Run to verify it passes**

Run: `python -m pytest tests/test_video_library.py -q` then `python -m pytest tests/test_video_library.py -q -m slow`
Expected: 3 fast tests pass; the slow test passes.

- [ ] **Step 13: Wire `main.py`**

In `backend/main.py`:
- Remove `from fastapi.staticfiles import StaticFiles` and the line `app.mount("/media", StaticFiles(directory=output_root), name="generated-media")`.
- Add imports `from services.media_response import create_media_router` and `from services.video_library import list_videos`.
- Directly after the CORS middleware block add `app.include_router(create_media_router(output_root))`.
- Replace the whole body of `list_generated_videos` with `return list_videos(output_root)` (keep the decorator and the return annotation).

- [ ] **Step 14: Verify the wiring against the real output folder**

Run:
```bash
python - <<'PYEOF'
from fastapi.testclient import TestClient
import main
c = TestClient(main.app)
videos = c.get("/videos").json()
print(len(videos), "videos")
url = videos[0]["url"]
r = c.get(url, headers={"Range": "bytes=0-99"})
print(url, r.status_code, r.headers.get("content-range"), r.headers.get("accept-ranges"))
PYEOF
python -m pytest -q
```
Expected: the script prints the video count, then `206 bytes 0-99/<size> bytes`; the whole suite passes. (The `/videos` call remuxes old tail-indexed files in place; this is intended.)

- [ ] **Step 15: Commit**

```bash
git add rendering/faststart.py rendering/video_renderer.py services/media_response.py services/video_library.py main.py tests/test_faststart.py tests/test_media_response.py tests/test_video_library.py
git commit -m "Serve videos with Range support and fast-start indexes" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Frontend: real progress, result player, working library

**Files:**
- Modify: `frontend/src/App.tsx` (full replacement), `frontend/src/index.css` (append)

**Interfaces:**
- Consumes (Tasks 2-4): `POST /lesson/jobs` -> `{job_id}`; `GET /lesson/jobs/{id}` -> `JobStatus` (`status`, `elapsed_seconds`, `stages[{key,label,state,detail}]`, `section`, `result` with `video_url`, `error{stage,message}`); `GET /videos`; `/media/...` with Range support.
- Produces: the UI. No new backend names.

The frontend has no test runner; Steps 2-3 are the verification gate (type-check, build, lint), then a manual check in Task 6.

- [ ] **Step 1: Replace `frontend/src/App.tsx`**

```tsx
import { useCallback, useEffect, useState } from "react";

type StageState = "pending" | "current" | "done" | "failed";
type JobStage = { key: string; label: string; state: StageState; detail: string | null };
type SectionSummary = {
    title: string;
    path_used: "trace" | "codegen" | "slideshow";
    tracer: string | null;
    duration_seconds: number;
    warnings: string[];
};
type VideoResponse = {
    lesson_request: { topic: string; audience: string; duration_minutes: number };
    lesson_plan: { title: string; learning_objectives: string[] };
    scene_durations: number[];
    video_path: string;
    video_url: string | null;
    audio_path: string | null;
    subtitle_path: string | null;
    sections: SectionSummary[];
};
type JobStatus = {
    job_id: string;
    status: "running" | "completed" | "failed";
    elapsed_seconds: number;
    stages: JobStage[];
    section: { index: number; total: number; title: string; path: string; activity: string } | null;
    result: VideoResponse | null;
    error: { stage: string; message: string } | null;
};
type LibraryVideo = { id: string; title: string; filename: string; url: string; created_at: number; size_bytes: number };

const API_BASE = "http://localhost:8000";
const JOBS_URL = `${API_BASE}/lesson/jobs`;
const LIBRARY_URL = `${API_BASE}/videos`;
const POLL_INTERVAL_MS = 1000;
const MAX_POLL_FAILURES = 5;

function pathLabel(section: SectionSummary): string {
    if (section.path_used === "trace") return `Algorithm trace · ${section.tracer ?? "unknown"}`;
    if (section.path_used === "codegen") return "Custom animation";
    return "Slideshow fallback";
}

function App() {
    const [request, setRequest] = useState("Explain binary search to a beginner.");
    const [jobId, setJobId] = useState<string | null>(null);
    const [job, setJob] = useState<JobStatus | null>(null);
    const [isStarting, setIsStarting] = useState(false);
    const [library, setLibrary] = useState<LibraryVideo[]>([]);
    const [error, setError] = useState("");

    const isGenerating = isStarting || jobId !== null;
    const result = job?.status === "completed" ? job.result : null;

    const loadLibrary = useCallback(async () => {
        try {
            const response = await fetch(LIBRARY_URL);
            if (response.ok) setLibrary((await response.json()) as LibraryVideo[]);
        } catch {
            // The generation studio remains usable while the library is unavailable.
            console.error("Failed to load library.");
        }
    }, []);

    useEffect(() => {
        void loadLibrary();
    }, [loadLibrary]);

    useEffect(() => {
        if (!jobId) return;
        let cancelled = false;
        let failures = 0;
        let timer = 0;

        const poll = async () => {
            try {
                const response = await fetch(`${JOBS_URL}/${jobId}`);
                if (!response.ok) throw new Error(`Status ${response.status}`);
                const status = (await response.json()) as JobStatus;
                failures = 0;
                if (cancelled) return;
                setJob(status);
                if (status.status !== "running") {
                    if (status.status === "failed" && status.error) setError(`${status.error.stage}: ${status.error.message}`);
                    setJobId(null);
                    void loadLibrary();
                    return;
                }
            } catch {
                failures += 1;
                if (failures >= MAX_POLL_FAILURES) {
                    if (!cancelled) {
                        setError("Lost connection to the server.");
                        setJobId(null);
                    }
                    return;
                }
            }
            if (!cancelled) timer = window.setTimeout(poll, POLL_INTERVAL_MS);
        };

        timer = window.setTimeout(poll, 0);
        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [jobId, loadLibrary]);

    async function generateVideo() {
        if (!request.trim() || isGenerating) return;
        setIsStarting(true);
        setJob(null);
        setError("");
        try {
            const response = await fetch(JOBS_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ request: request.trim() }),
            });
            if (!response.ok) throw new Error((await response.text()) || `Could not start generation (status ${response.status})`);
            const created = (await response.json()) as { job_id: string };
            setJobId(created.job_id);
        } catch (generationError) {
            setError(generationError instanceof Error ? generationError.message : "Video generation failed.");
        } finally {
            setIsStarting(false);
        }
    }

    const statusText = error ? "Generation stopped" : result ? "Your lesson is ready" : job || isGenerating ? "The studio is working through each stage" : "Ready when you are";
    const elapsed = Math.round(job?.elapsed_seconds ?? 0);

    return (
        <main className="app-shell">
            <header className="topbar"><div className="brand-mark"><span>EDU</span><strong>GEN</strong></div><div className="topbar-status"><span className="status-dot" /> Video studio <span className="slash">/</span> beta</div></header>
            <section className="workspace">
                <div className="intro"><p className="eyebrow">Motion lesson studio</p><h1>Turn a question into a <em>visual explanation.</em></h1><p className="intro-copy">Describe what you want to teach. EduGen will plan the lesson, choreograph the scenes, and assemble a narrated video.</p></div>
                <div className="studio-grid">
                    <section className="prompt-panel">
                        <div className="panel-heading"><span className="step-number">01</span><div><p className="panel-kicker">Your lesson</p><h2>What should we explain?</h2></div></div>
                        <textarea value={request} onChange={(event) => setRequest(event.target.value)} disabled={isGenerating} aria-label="Lesson request" />
                        <div className="prompt-footer"><span className="hint">Try a concept, process, or algorithm</span><button className="generate-button" onClick={generateVideo} disabled={isGenerating || !request.trim()}>{isGenerating ? "Generating..." : "Generate video"}<span aria-hidden="true">↗</span></button></div>
                        {error && <p className="error-message">{error}</p>}
                    </section>
                    <section className={`progress-panel ${isGenerating || job ? "is-active" : ""}`} aria-live="polite">
                        <div className="panel-heading progress-heading"><span className="step-number">02</span><div><p className="panel-kicker">Production pipeline</p><h2>{statusText}</h2></div>{(isGenerating || job) && <span className="elapsed">{elapsed}s</span>}</div>
                        {job ? (
                            <div className="stage-list">{job.stages.map((stage, index) => <div className={`stage ${stage.state === "done" ? "complete" : ""} ${stage.state === "current" ? "current" : ""} ${stage.state === "failed" ? "failed" : ""}`} key={stage.key}><span className="stage-icon">{stage.state === "done" ? "✓" : stage.state === "failed" ? "!" : stage.state === "current" ? <span className="loader-dot" /> : String(index + 1).padStart(2, "0")}</span><div><strong>{stage.label}</strong><small>{stage.detail ?? ""}</small></div>{stage.state === "current" && <span className="stage-state">working</span>}</div>)}</div>
                        ) : (
                            <p className="stage-hint">{isGenerating ? "Starting the pipeline..." : "The real stages of the pipeline appear here once generation starts."}</p>
                        )}
                    </section>
                </div>
                {result && <section className="result-panel"><div><p className="panel-kicker">Export complete</p><h2>{result.lesson_plan.title}</h2><p>{result.lesson_request.audience} lesson · {result.sections.length} sections · narrated video with subtitles</p>{result.sections.length > 0 && <ul className="section-list">{result.sections.map((section, index) => <li key={`${index}-${section.title}`}><span className="section-title">{section.title}</span><span className={`path-badge path-${section.path_used}`}>{pathLabel(section)}</span></li>)}</ul>}</div><div className="result-badge">MP4 ready <span>✓</span></div>{result.video_url && <><video className="result-video" controls preload="metadata" src={`${API_BASE}${result.video_url}`} /><a className="result-link" href={`${API_BASE}${result.video_url}`} download>Download MP4</a></>}</section>}
                <section className="library-section">
                    <div className="library-heading"><div><p className="eyebrow">Your archive</p><h2>Previous videos</h2></div><span>{library.length} {library.length === 1 ? "video" : "videos"}</span></div>
                    {library.length === 0 ? <p className="empty-library">Generated lessons will appear here for replay. </p> : <div className="library-grid">{library.map((video) => <article className="video-card" key={video.id}><video controls preload="metadata" src={`${API_BASE}${video.url}`} /><div className="video-card-info"><h3>{video.title}</h3><p>{video.filename}</p></div></article>)}</div>}
                </section>
            </section>
            <footer className="footer"><span>EDUGEN AI</span><span>Plan · animate · explain</span></footer>
        </main>
    );
}

export default App;
```

- [ ] **Step 2: Append the styles to `frontend/src/index.css`**

```css
.stage.failed .stage-icon { border-color: #ee927b; color: #ee927b; }
.stage.failed strong { color: #ee927b; }
.stage-hint { margin: 29px 0 0; color: #5f685a; font-size: 12px; line-height: 1.6; }
.result-panel { flex-wrap: wrap; }
.result-video { display: block; flex-basis: 100%; width: 100%; aspect-ratio: 16 / 9; background: #090a08; border: 1px solid #353c31; }
.result-link { color: #b5d85d; font: 11px "DM Mono", monospace; text-decoration: none; }
.result-link:hover { text-decoration: underline; }
```

- [ ] **Step 3: Type-check, build and lint**

Run in `frontend/`: `bun run build` then `bun run lint` (use `npm run build` / `npm run lint` if bun is not installed).
Expected: `tsc -b` and `vite build` finish without errors; lint reports no errors (warnings that already existed are fine). Fix any type error in `App.tsx` before continuing.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/index.css
git commit -m "Show real pipeline progress and play the generated video" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Final verification (full suite and a live run)

**Files:** none modified (scratch scripts go in `backend/scratch_*.py` and are not committed).

- [ ] **Step 1: Full suite including slow tests**

Run in `backend/`: `python -m pytest -q -m "slow or not slow"`
Expected: everything passes (163 before this branch, plus the new tests). Fix any failure before continuing.

- [ ] **Step 2: Start the backend and run a real job**

Start the server in the background: `python -m uvicorn main:app --port 8000` from `backend/`. Then run this script (save as `backend/scratch_job_run.py`, delete afterwards):

```python
import json, time, urllib.request

def call(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())

job_id = call("http://localhost:8000/lesson/jobs", {"request": "Explain binary search to a beginner"})["job_id"]
last = None
while True:
    status = call(f"http://localhost:8000/lesson/jobs/{job_id}")
    line = [f"{s['key']}={s['state']}" for s in status["stages"]]
    detail = next((s["detail"] for s in status["stages"] if s["state"] == "current"), None)
    summary = (status["status"], line, detail)
    if summary != last:
        print(round(status["elapsed_seconds"]), *summary)
        last = summary
    if status["status"] != "running":
        break
    time.sleep(1)
print("error:", status["error"])
print("video_url:", status["result"] and status["result"]["video_url"])
print("output_dir:", status["result"] and status["result"]["output_dir"])
```
Expected: a changing sequence of lines showing the stages moving `analyze` -> `knowledge` -> `plan` -> `script` -> `route` -> `animate` (detail "Section N of M · ...") -> `assemble`, ending with `completed`, a `video_url` and an `output_dir`. This takes several minutes (Gemini and Manim).

- [ ] **Step 3: Check the LLM log**

In the printed `output_dir` confirm `llm_calls.md` and `llm_calls.json` exist. Run (replace `RUN`):

```bash
python - <<'PYEOF'
import json, pathlib
run = pathlib.Path(r"RUN")
data = json.loads((run / "llm_calls.json").read_text(encoding="utf-8"))
print(data["status"], len(data["calls"]), "calls")
for call in data["calls"]:
    print(call["seq"], call["label"], call["schema"], call["duration_seconds"], "ERR" if call["error"] else "ok")
PYEOF
```
Expected: status `completed`; labels in order `lesson analyzer`, `knowledge base`, `lesson planner`, `script writer`, `router`, then `section N · storyboard` / `section N · codegen` / `section N · narrator`. Open `llm_calls.md` and read one prompt/output pair to confirm it is readable.

- [ ] **Step 4: Check the video file and Range support**

Run (replace `RUN`):
```bash
curl -s -o /dev/null -D - -H "Range: bytes=0-99" http://localhost:8000/media/RUN_FOLDER_NAME/lesson_demo.mp4 | head -8
curl -s http://localhost:8000/videos | python -c "import sys,json; v=json.load(sys.stdin); print(len(v), 'videos', v[0]['url'])"
```
Expected: `HTTP/1.1 206`, `content-range: bytes 0-99/<size>`, `accept-ranges: bytes`; the library lists all videos.

- [ ] **Step 5: Manual check in the browser (user)**

Start the frontend (`bun run dev` in `frontend/`), open it, generate a short lesson, and confirm: (a) the pipeline panel moves through the stages as the backend works and shows "Section N of M"; (b) when finished, the video plays in the result panel and seeks; (c) the library cards show a first frame and play; (d) a stopped backend mid-run ends with "Lost connection to the server." after about five seconds. Report anything that does not match; do not claim success on checks that were not performed.

- [ ] **Step 6: Report**

Write the result in chat: stage sequence observed, LLM call count and any errors in the log, Range response, which manual checks the user confirmed. Stop the server, delete `backend/scratch_job_run.py`. Anything failing goes back to the owning task, not into a quick patch.

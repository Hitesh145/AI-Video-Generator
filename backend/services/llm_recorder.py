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

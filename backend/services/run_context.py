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

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

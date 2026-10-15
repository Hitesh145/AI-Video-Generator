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

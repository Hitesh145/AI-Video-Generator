from pathlib import Path

import pytest

from animation.codegen.generator import (
    EXAMPLES_DIR,
    CodegenFailed,
    CodegenRenderer,
    default_scene_renderer,
)
from animation.codegen.validator import validate_scene_code
from animation.schemas import RenderSection
from animation.templates.render import RenderError
from animation.timing import probe_duration
from fakes import FakeLLM


SECTION = RenderSection(index=2, title="Why it matters", narration="Algorithms are everywhere.")
GOOD_CODE = (EXAMPLES_DIR / "title_card.py").read_text(encoding="utf-8")


class RecordingRenderer:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list[Path] = []

    def __call__(self, scene_file, scene_name, work_dir, output_path):
        self.calls.append(scene_file)
        assert (scene_file.parent / "kit.py").exists()
        if len(self.calls) <= self.failures:
            raise RenderError("NameError: name 'Circl' is not defined")
        output_path.write_bytes(b"video")
        return output_path


def run(llm, renderer, tmp_path):
    return CodegenRenderer(llm, scene_renderer=renderer).render(
        SECTION, 6.0, tmp_path / "work", tmp_path / "out.mp4", tmp_path / "artifacts"
    )


def test_examples_pass_validator():
    for example in EXAMPLES_DIR.glob("*.py"):
        assert validate_scene_code(example.read_text(encoding="utf-8")) == [], example.name


def test_success_on_first_attempt(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}])
    renderer = RecordingRenderer()

    assert run(llm, renderer, tmp_path) == tmp_path / "out.mp4"
    assert "Why it matters" in llm.prompts[0]
    assert "6.0 seconds" in llm.prompts[0]
    assert (tmp_path / "artifacts" / "section_2_attempt_1.py").exists()


def test_validator_rejection_is_fed_back(tmp_path):
    llm = FakeLLM([{"code": "import os\n" + GOOD_CODE}, {"code": GOOD_CODE}])
    renderer = RecordingRenderer()

    run(llm, renderer, tmp_path)

    assert len(renderer.calls) == 1
    assert "import of 'os' is not allowed" in llm.prompts[1]
    assert (tmp_path / "artifacts" / "section_2_attempt_1.log").exists()


def test_render_error_is_fed_back(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}, {"code": GOOD_CODE}])
    run(llm, RecordingRenderer(failures=1), tmp_path)

    assert "Circl" in llm.prompts[1]


def test_gives_up_after_three_attempts(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}] * 3)

    with pytest.raises(CodegenFailed) as info:
        run(llm, RecordingRenderer(failures=3), tmp_path)

    assert len(info.value.errors) == 3


def test_llm_errors_count_as_attempts(tmp_path):
    llm = FakeLLM([RuntimeError("quota"), RuntimeError("quota"), RuntimeError("quota")])

    with pytest.raises(CodegenFailed):
        run(llm, RecordingRenderer(), tmp_path)


@pytest.mark.slow
@pytest.mark.parametrize("example", ["title_card.py", "process_flow.py"])
def test_examples_render_for_real(tmp_path, example):
    code = (EXAMPLES_DIR / example).read_text(encoding="utf-8")
    out = CodegenRenderer(FakeLLM([{"code": code}]), scene_renderer=default_scene_renderer).render(
        SECTION, 4.0, tmp_path / "work", tmp_path / "out.mp4", tmp_path / "artifacts"
    )

    assert probe_duration(out) > 1.0

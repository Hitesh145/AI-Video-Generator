import json
from pathlib import Path

import pytest

from animation.codegen import generator, kit
from animation.codegen.generator import (
    BEAT_DURATIONS_ENV,
    BEAT_REPORT_ENV,
    EXAMPLES_DIR,
    CodegenFailed,
    CodegenRenderer,
    CodegenResult,
    check_beat_report,
    default_scene_renderer,
)
from animation.codegen.validator import validate_scene_code
from animation.schemas import RenderSection
from animation.storyboard import PlannedBeat
from animation.templates.render import RenderError
from animation.timing import probe_duration
from fakes import FakeLLM


SECTION = RenderSection(index=2, title="Why it matters", narration="Algorithms are everywhere.")
BEATS = [
    PlannedBeat("Algorithms are everywhere in daily life.", "a ring of small app icons"),
    PlannedBeat("They follow clear steps to reach a result.", "three boxes joined by arrows"),
]
DURATIONS = [3.0, 4.0]
GOOD_CODE = (EXAMPLES_DIR / "title_card.py").read_text(encoding="utf-8")


def rows(*overruns):
    # expected_end is the running total of DURATIONS, as the real BeatClock reports it
    ends = [sum(DURATIONS[: i + 1]) if i < len(DURATIONS) else float(i + 1) for i in range(len(overruns))]
    return [
        {"beat": i + 1, "start": 0.0, "expected_end": end, "actual_end": end + o, "overrun": o}
        for i, (end, o) in enumerate(zip(ends, overruns))
    ]


class RecordingRenderer:
    """Fake scene renderer. reports maps call number -> report rows (None = no report written)."""

    def __init__(self, failures: int = 0, reports: dict | None = None) -> None:
        self.failures = failures
        self.reports = reports or {}
        self.calls: list[Path] = []
        self.envs: list[dict] = []

    def __call__(self, scene_file, scene_name, work_dir, output_path, extra_env):
        self.calls.append(scene_file)
        self.envs.append(extra_env)
        assert (scene_file.parent / "kit.py").exists()
        number = len(self.calls)
        if number <= self.failures:
            raise RenderError("NameError: name 'Circl' is not defined")
        output_path.write_bytes(f"video{number}".encode())
        report = self.reports.get(number, rows(0.0, 0.0))
        if report is not None:
            Path(extra_env[BEAT_REPORT_ENV]).write_text(json.dumps(report), encoding="utf-8")
        return output_path


def run(llm, renderer, tmp_path, beats=BEATS, durations=DURATIONS):
    return CodegenRenderer(llm, scene_renderer=renderer).render(
        SECTION, beats, durations, tmp_path / "work", tmp_path / "out.mp4", tmp_path / "artifacts"
    )


def test_examples_pass_validator():
    for example in EXAMPLES_DIR.glob("*.py"):
        assert validate_scene_code(example.read_text(encoding="utf-8")) == [], example.name


def test_env_names_match_the_kit():
    assert generator.BEAT_DURATIONS_ENV == kit.BEAT_DURATIONS_ENV
    assert generator.BEAT_REPORT_ENV == kit.BEAT_REPORT_ENV


def test_success_on_first_attempt(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}])
    renderer = RecordingRenderer()

    result = run(llm, renderer, tmp_path)

    assert result == CodegenResult(path=tmp_path / "out.mp4", warnings=[])
    assert (tmp_path / "out.mp4").read_bytes() == b"video1"
    assert (tmp_path / "artifacts" / "section_2_attempt_1.py").exists()


def test_prompt_lists_every_beat_with_duration_text_and_visual(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}])

    run(llm, RecordingRenderer(), tmp_path)

    prompt = llm.prompts[0]
    assert "Why it matters" in prompt
    assert "Beat 1 (3.0 s)" in prompt and "Beat 2 (4.0 s)" in prompt
    assert "Algorithms are everywhere in daily life." in prompt
    assert "three boxes joined by arrows" in prompt
    assert "BeatClock" in prompt
    assert "exactly 2 times" in prompt


def test_scene_receives_durations_and_report_path_in_its_environment(tmp_path):
    renderer = RecordingRenderer()

    run(FakeLLM([{"code": GOOD_CODE}]), renderer, tmp_path)

    env = renderer.envs[0]
    assert json.loads(env[BEAT_DURATIONS_ENV]) == [3.0, 4.0]
    assert Path(env[BEAT_REPORT_ENV]).is_absolute()


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


def test_scene_that_never_calls_end_beat_fails_and_is_told_so(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}] * 3)
    renderer = RecordingRenderer(reports={1: None, 2: None, 3: None})

    with pytest.raises(CodegenFailed):
        run(llm, renderer, tmp_path)

    assert "never called clock.end_beat()" in llm.prompts[1]


def test_wrong_end_beat_count_fails_and_is_never_accepted(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}] * 3)
    renderer = RecordingRenderer(reports={1: rows(0.0), 2: rows(0.0), 3: rows(0.0)})

    with pytest.raises(CodegenFailed):
        run(llm, renderer, tmp_path)

    assert "1 times but there are 2 beats" in llm.prompts[1]
    assert not (tmp_path / "out.mp4").exists()


def test_late_scene_is_retried_with_a_precise_message(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}, {"code": GOOD_CODE}])
    renderer = RecordingRenderer(reports={1: rows(0.0, 2.5)})

    result = run(llm, renderer, tmp_path)

    assert result.warnings == []
    assert len(renderer.calls) == 2
    assert "Beat 2 ended 2.5 s after its audio ended" in llm.prompts[1]
    assert (tmp_path / "out.mp4").read_bytes() == b"video2"


def test_small_overrun_is_accepted_without_retry(tmp_path):
    renderer = RecordingRenderer(reports={1: rows(0.0, 0.9)})

    result = run(FakeLLM([{"code": GOOD_CODE}]), renderer, tmp_path)

    assert result.warnings == []
    assert len(renderer.calls) == 1


def test_best_late_render_is_accepted_with_a_warning(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}] * 3)
    renderer = RecordingRenderer(reports={1: rows(0.0, 3.0), 2: rows(0.0, 1.5), 3: rows(0.0, 2.0)})

    result = run(llm, renderer, tmp_path)

    assert (tmp_path / "out.mp4").read_bytes() == b"video2"
    assert len(result.warnings) == 1
    assert "ran late" in result.warnings[0] and "1.5" in result.warnings[0]
    assert "Why it matters" in result.warnings[0]


def test_beats_and_durations_must_line_up(tmp_path):
    with pytest.raises(ValueError):
        run(FakeLLM([]), RecordingRenderer(), tmp_path, durations=[3.0])
    with pytest.raises(ValueError):
        run(FakeLLM([]), RecordingRenderer(), tmp_path, beats=[], durations=[])


def test_check_beat_report_reports_the_first_late_beat_range(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(rows(0.0, 0.4, 2.2)), encoding="utf-8")

    check = check_beat_report(path, 3)

    assert check.hard is False
    assert check.worst_overrun == pytest.approx(2.2)
    assert "Beat 3 ended 2.2 s" in check.error
    assert "beats 2-3" in check.error


def test_check_beat_report_unreadable_is_hard(tmp_path):
    path = tmp_path / "r.json"
    path.write_text("{not json", encoding="utf-8")

    check = check_beat_report(path, 2)

    assert check.hard is True


@pytest.mark.slow
@pytest.mark.parametrize("example", ["title_card.py", "process_flow.py", "three_d_layers.py"])
def test_examples_render_for_real_on_the_beat_clock(tmp_path, example):
    code = (EXAMPLES_DIR / example).read_text(encoding="utf-8")
    beats = [PlannedBeat("one", "a"), PlannedBeat("two", "b"), PlannedBeat("three", "c")]

    result = CodegenRenderer(FakeLLM([{"code": code}]), scene_renderer=default_scene_renderer).render(
        SECTION, beats, [2.5, 2.5, 2.5], tmp_path / "work", tmp_path / "out.mp4", tmp_path / "artifacts"
    )

    assert result.warnings == []
    assert probe_duration(result.path) == pytest.approx(7.5, abs=0.2)


def test_clock_created_after_animations_is_a_hard_failure(tmp_path):
    late_start = [dict(row, start=2.0) for row in rows(0.0, 0.0)]
    llm = FakeLLM([{"code": GOOD_CODE}] * 3)
    renderer = RecordingRenderer(reports={1: late_start, 2: late_start, 3: late_start})

    with pytest.raises(CodegenFailed):
        run(llm, renderer, tmp_path)

    assert "BeatClock(self)" in llm.prompts[1] and "first line" in llm.prompts[1]
    assert not (tmp_path / "out.mp4").exists()


def test_scene_that_uses_its_own_durations_is_a_hard_failure(tmp_path):
    wrong = [dict(row, expected_end=row["expected_end"] + 1.0) for row in rows(0.0, 0.0)]
    llm = FakeLLM([{"code": GOOD_CODE}] * 3)
    renderer = RecordingRenderer(reports={1: wrong, 2: wrong, 3: wrong})

    with pytest.raises(CodegenFailed):
        run(llm, renderer, tmp_path)

    assert "own durations" in llm.prompts[1]


def test_tiny_early_overrun_does_not_blame_the_first_beat(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(rows(0.01, 0.0, 3.0)), encoding="utf-8")

    check = check_beat_report(path, 3)

    assert "Beat 3 ended 3.0 s" in check.error
    assert "beats 1" not in check.error


def test_validator_problems_survive_into_the_final_error(tmp_path):
    llm = FakeLLM([{"code": "import os\n" + GOOD_CODE}] * 3)

    with pytest.raises(CodegenFailed) as info:
        run(llm, RecordingRenderer(), tmp_path)

    assert "import of 'os' is not allowed" in info.value.errors[0]


def test_the_3d_example_exists_and_passes_the_validator():
    code = (EXAMPLES_DIR / "three_d_layers.py").read_text(encoding="utf-8")

    assert "class SectionScene(ThreeDScene):" in code
    assert "clock = BeatClock(self)" in code and code.count("clock.end_beat()") == 3
    assert validate_scene_code(code) == []


def test_a_threed_scene_with_one_class_named_section_scene_is_valid():
    code = "from manim import *\nfrom kit import *\n\n\nclass SectionScene(ThreeDScene):\n    def construct(self):\n        pass\n"

    assert validate_scene_code(code) == []


def test_the_codegen_prompt_mentions_the_3d_rule_and_includes_the_3d_example(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}])
    run(llm, RecordingRenderer(), tmp_path)

    prompt = " ".join(llm.prompts[0].split())
    assert ("When a beat is about something spatial (layers of a network, matrices as grids, vectors, planes, stacks), "
            "you may use class SectionScene(ThreeDScene): follow the 3D example; keep labels fixed in frame.") in prompt
    assert "--- three_d_layers.py ---" in prompt

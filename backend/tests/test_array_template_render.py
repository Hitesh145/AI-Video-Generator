import pytest

from animation.schemas import ArrayState, TraceStep
from animation.templates.render import ArrayTemplateRenderer
from animation.timing import probe_duration
from animation.tracers.base import ArrayInput
from animation.tracers.bubble_sort import BubbleSortTracer


def test_rejects_mismatched_durations(tmp_path):
    steps = [TraceStep(state=ArrayState(values=[1, 2]), event="start")]
    with pytest.raises(ValueError):
        ArrayTemplateRenderer().render("T", steps, [1.0, 2.0], tmp_path, tmp_path / "out.mp4")


def test_swapped_cells_stay_swapped(tmp_path, monkeypatch):
    import json

    from manim import tempconfig

    from animation.templates.array_scene import ArrayScene
    from animation.templates.render import ARRAY_SCENE_DATA_ENV

    steps = BubbleSortTracer().trace(ArrayInput(values=[3, 1, 2]))
    data_path = tmp_path / "data.json"
    data_path.write_text(json.dumps({
        "title": "Bubble sort",
        "states": [step.state.model_dump(mode="json") for step in steps],
        "durations": [1.0] * len(steps),
    }))
    monkeypatch.setenv(ARRAY_SCENE_DATA_ENV, str(data_path))

    with tempconfig({"dry_run": True, "media_dir": str(tmp_path / "media")}):
        scene = ArrayScene()
        scene.render()

    left_to_right = sorted(scene.cells, key=lambda cell: cell.get_center()[0])
    assert [cell[1].text for cell in left_to_right] == ["1", "2", "3"]


@pytest.mark.slow
def test_renders_bubble_sort_with_expected_length(tmp_path):
    steps = BubbleSortTracer().trace(ArrayInput(values=[3, 1, 2]))
    durations = [1.0] * len(steps)

    out = ArrayTemplateRenderer().render(
        "Bubble sort", steps, durations, tmp_path / "work", tmp_path / "out.mp4"
    )

    assert out.exists()
    assert probe_duration(out) == pytest.approx(sum(durations), abs=0.3)


@pytest.mark.slow
def test_renders_widest_array(tmp_path):
    values = [-99, 999, 500, 12, 7, 0, 123, 456, 789, -5, 42, 1]
    steps = [
        TraceStep(state=ArrayState(values=values, pointers={"lo": 0, "mid": 0, "hi": 0}), event="start"),
        TraceStep(state=ArrayState(values=values, pointers={"lo": 11, "hi": 11}, dimmed=list(range(11)), found=11), event="end"),
    ]

    out = ArrayTemplateRenderer().render(
        "Widest array", steps, [1.0, 1.0], tmp_path / "work", tmp_path / "out.mp4"
    )

    assert probe_duration(out) == pytest.approx(2.0, abs=0.3)

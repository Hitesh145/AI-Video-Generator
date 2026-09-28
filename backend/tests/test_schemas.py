import pytest
from pydantic import ValidationError

from animation.schemas import ArrayState, build_render_sections
from schemas.lesson import LessonScript, ScriptSection


def make_script(intro: str = "Intro text.", conclusion: str = "Wrap up.") -> LessonScript:
    return LessonScript(
        introduction=intro,
        sections=[
            ScriptSection(section_title="How it works", narration="Step by step."),
            ScriptSection(section_title="Cost", narration="It is fast."),
        ],
        conclusion=conclusion,
    )


def test_builds_sections_in_video_order():
    sections = build_render_sections(make_script())

    assert [s.title for s in sections] == ["Introduction", "How it works", "Cost", "Conclusion"]
    assert [s.index for s in sections] == [0, 1, 2, 3]
    assert sections[1].narration == "Step by step."


def test_skips_blank_intro_and_conclusion():
    sections = build_render_sections(make_script(intro="  ", conclusion=""))

    assert [s.title for s in sections] == ["How it works", "Cost"]
    assert [s.index for s in sections] == [0, 1]


def test_array_state_rejects_out_of_range_indices():
    with pytest.raises(ValidationError):
        ArrayState(values=[1, 2, 3], pointers={"lo": 3})


def test_array_state_round_trips_through_json():
    state = ArrayState(values=[3, 1], swapped=(0, 1), sorted_indices=[1], found=None)

    assert ArrayState.model_validate(state.model_dump(mode="json")) == state

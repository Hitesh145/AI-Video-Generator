import pytest

from animation.narrator import NarratedSegment, StepNarrator, segments_from_narration
from animation.schemas import ArrayState, RenderSection, StepNarration, TraceStep
from fakes import FakeLLM


SECTION = RenderSection(index=1, title="Sorting", narration="We sort the list.")
STEPS = [
    TraceStep(state=ArrayState(values=[2, 1]), event=f"event {i}")
    for i in range(4)
]


def test_groups_steps_under_previous_sentence():
    narration = StepNarration(
        sentences=["First.", "Then the rest."],
        group_with_previous=[False, False, True, True],
    )

    assert segments_from_narration(4, narration) == [
        NarratedSegment("First.", (0,)),
        NarratedSegment("Then the rest.", (1, 2, 3)),
    ]


@pytest.mark.parametrize(
    "sentences,groups",
    [
        (["a", "b"], [False, False, False]),       # wrong flag count
        (["a"], [True, False, False, False]),      # first step grouped
        (["a", "b", "c"], [False, False, True, True]),  # sentence count mismatch
        (["a", " "], [False, False, True, True]),  # blank sentence
    ],
)
def test_rejects_inconsistent_narration(sentences, groups):
    with pytest.raises(ValueError):
        segments_from_narration(4, StepNarration(sentences=sentences, group_with_previous=groups))


def test_narrate_uses_llm_result_and_prompt_lists_events():
    llm = FakeLLM([{"sentences": ["a", "b", "c", "d"], "group_with_previous": [False] * 4}])

    segments, warnings = StepNarrator(llm).narrate(SECTION, STEPS)

    assert [s.text for s in segments] == ["a", "b", "c", "d"]
    assert warnings == []
    assert "event 3" in llm.prompts[0]
    assert "We sort the list." in llm.prompts[0]


def test_narrate_retries_once_then_succeeds():
    bad = {"sentences": ["a"], "group_with_previous": [False] * 4}
    good = {"sentences": ["a", "b", "c", "d"], "group_with_previous": [False] * 4}

    segments, warnings = StepNarrator(FakeLLM([bad, good])).narrate(SECTION, STEPS)

    assert len(segments) == 4
    assert warnings == []


def test_narrate_falls_back_to_events():
    bad = {"sentences": ["a"], "group_with_previous": [False] * 4}

    segments, warnings = StepNarrator(FakeLLM([bad, bad])).narrate(SECTION, STEPS)

    assert [s.text for s in segments] == ["event 0", "event 1", "event 2", "event 3"]
    assert len(warnings) == 1

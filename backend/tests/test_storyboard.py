import pytest

from animation.schemas import RenderSection
from animation.storyboard import (
    FALLBACK_VISUAL,
    Beat,
    PlannedBeat,
    Storyboard,
    Storyboarder,
    beats_from_storyboard,
    fallback_beats,
    merge_short_beats,
    split_sentences,
)
from fakes import FakeLLM


def test_split_sentences_basic():
    assert split_sentences("One. Two! Three?  ") == ["One.", "Two!", "Three?"]


def test_split_sentences_keeps_closing_quote_attached():
    text = 'He said "stop." Then left.'

    assert split_sentences(text) == ['He said "stop."', "Then left."]


def test_split_sentences_does_not_split_decimals():
    assert split_sentences("We have 3.5 apples. Good.") == ["We have 3.5 apples.", "Good."]


def test_split_sentences_empty():
    assert split_sentences("   ") == []


SENTENCES = ["A one.", "B two.", "C three.", "D four."]


def board(*pairs):
    return Storyboard(beats=[Beat(sentence_count=n, visual=v) for n, v in pairs])


def test_beats_from_storyboard_maps_text_verbatim():
    beats = beats_from_storyboard(SENTENCES, board((1, "box"), (3, "arrows")))

    assert beats == [
        PlannedBeat("A one.", "box"),
        PlannedBeat("B two. C three. D four.", "arrows"),
    ]


@pytest.mark.parametrize("pairs", [
    [(1, "x"), (1, "y")],       # sums to 2, not 4
    [(5, "x")],                 # sums to 5
    [(0, "x"), (4, "y")],       # zero count
    [(-1, "x"), (5, "y")],      # negative count
    [(4, "  ")],                # blank visual
    [],                         # no beats
])
def test_beats_from_storyboard_rejects_bad_plans(pairs):
    with pytest.raises(ValueError):
        beats_from_storyboard(SENTENCES, board(*pairs))


def test_beats_from_storyboard_rejects_more_than_eight_beats():
    sentences = [f"S{i}." for i in range(9)]

    with pytest.raises(ValueError, match="1 to 8 beats"):
        beats_from_storyboard(sentences, board(*[(1, "v")] * 9))


def test_merge_short_beat_in_the_middle_goes_to_next():
    long = "word " * 10
    beats = [PlannedBeat(long, "a"), PlannedBeat("Tiny one.", "b"), PlannedBeat(long, "c")]

    merged = merge_short_beats(beats)

    assert len(merged) == 2
    assert merged[1].text == f"Tiny one. {long}"
    assert merged[1].visual == "b c"


def test_merge_short_last_beat_goes_to_previous():
    long = "word " * 10
    merged = merge_short_beats([PlannedBeat(long, "a"), PlannedBeat("Tiny.", "b")])

    assert len(merged) == 1
    assert merged[0].text.endswith("Tiny.")
    assert merged[0].visual == "a b"


def test_merge_all_short_collapses_to_one_beat():
    beats = [PlannedBeat("One.", "a"), PlannedBeat("Two.", "b"), PlannedBeat("Three.", "c")]

    merged = merge_short_beats(beats)

    assert len(merged) == 1
    assert merged[0].text == "One. Two. Three."


def test_merge_leaves_long_beats_alone():
    long = "word " * 10
    beats = [PlannedBeat(long, "a"), PlannedBeat(long, "b")]

    assert merge_short_beats(beats) == beats


def test_fallback_groups_sentences_into_long_enough_beats():
    sentences = [" ".join(["w"] * 10) + "."] * 6      # 60 words

    beats = fallback_beats(sentences, min_words=25)

    assert [len(b.text.split()) for b in beats] == [30, 30]
    assert {b.visual for b in beats} == {FALLBACK_VISUAL}


def test_fallback_merges_a_short_leftover_into_the_last_group():
    sentences = [" ".join(["w"] * 10) + "."] * 3 + ["Short end."]   # 32 words

    beats = fallback_beats(sentences, min_words=25)

    assert len(beats) == 1
    assert beats[0].text.endswith("Short end.")


def test_fallback_never_exceeds_eight_beats():
    sentences = [" ".join(["w"] * 30) + "."] * 20      # 600 words

    assert len(fallback_beats(sentences)) <= 8


def test_fallback_of_nothing_is_empty():
    assert fallback_beats([]) == []


S1 = "Binary search looks at the middle of a sorted list first."
S2 = "If the middle is too big it throws away the right half."
S3 = "Then it repeats the same trick on what is left over."
NARRATION = f"{S1} {S2} {S3}"
SECTION = RenderSection(index=1, title="How it works", narration=NARRATION)


def reply(*pairs):
    return {"beats": [{"sentence_count": n, "visual": v} for n, v in pairs]}


def test_storyboarder_maps_a_valid_plan_to_verbatim_text():
    llm = FakeLLM([reply((1, "a sorted row of boxes"), (2, "the right half fades"))])

    beats, warnings = Storyboarder(llm).plan(SECTION)

    assert beats == [
        PlannedBeat(S1, "a sorted row of boxes"),
        PlannedBeat(f"{S2} {S3}", "the right half fades"),
    ]
    assert warnings == []


def test_storyboarder_prompt_numbers_the_sentences():
    llm = FakeLLM([reply((3, "one picture"))])

    Storyboarder(llm).plan(SECTION)

    assert "How it works" in llm.prompts[0]
    assert f"1. {S1}" in llm.prompts[0]
    assert f"3. {S3}" in llm.prompts[0]


def test_storyboarder_merges_short_beats():
    section = RenderSection(index=0, title="T", narration=f"Short one. {S1} {S2}")
    llm = FakeLLM([reply((1, "a"), (1, "b"), (1, "c"))])

    beats, _ = Storyboarder(llm).plan(section)

    assert [b.visual for b in beats] == ["a b", "c"]


def test_storyboarder_retries_once_and_tells_the_llm_why():
    llm = FakeLLM([reply((1, "a")), reply((3, "all of it"))])

    beats, warnings = Storyboarder(llm).plan(SECTION)

    assert [b.visual for b in beats] == ["all of it"]
    assert warnings == []
    assert "was rejected" in llm.prompts[1]
    assert "add up to 1" in llm.prompts[1]
    assert "was rejected" not in llm.prompts[0]


def test_storyboarder_falls_back_after_two_bad_plans():
    llm = FakeLLM([reply((1, "a")), reply((9, "b"))])

    beats, warnings = Storyboarder(llm).plan(SECTION)

    assert beats == fallback_beats([S1, S2, S3])
    assert len(warnings) == 1
    assert "How it works" in warnings[0] and "storyboard failed" in warnings[0]


def test_storyboarder_falls_back_when_the_llm_errors():
    llm = FakeLLM([RuntimeError("quota"), RuntimeError("quota")])

    beats, warnings = Storyboarder(llm).plan(SECTION)

    assert beats == fallback_beats([S1, S2, S3])
    assert "quota" in warnings[0]


def test_empty_narration_uses_the_title_as_the_only_sentence():
    section = RenderSection(index=0, title="Introduction", narration="   ")
    llm = FakeLLM([reply((1, "title card"))])

    beats, warnings = Storyboarder(llm).plan(section)

    assert beats == [PlannedBeat("Introduction", "title card")]
    assert warnings == []


def test_empty_narration_with_failing_llm_still_returns_a_beat():
    section = RenderSection(index=0, title="Introduction", narration="")

    beats, warnings = Storyboarder(FakeLLM([RuntimeError("x"), RuntimeError("x")])).plan(section)

    assert [b.text for b in beats] == ["Introduction"]
    assert len(warnings) == 1


def test_split_sentences_does_not_split_ellipsis_before_lowercase():
    assert split_sentences("Wait... what happens next? Good.") == ["Wait... what happens next?", "Good."]


def test_split_sentences_splits_ellipsis_before_a_new_sentence():
    assert split_sentences("Hmm... Then it stops.") == ["Hmm...", "Then it stops."]


def test_split_sentences_keeps_step_numbers_with_their_sentence():
    assert split_sentences("Step 1. Add water. Step 2. Stir.") == ["Step 1. Add water.", "Step 2. Stir."]


def test_split_sentences_keeps_double_closing_quotes_attached():
    text = "He said “she said ‘stop.’” Then left."

    assert split_sentences(text) == ["He said “she said ‘stop.’”", "Then left."]


def storyboard_prompt():
    llm = FakeLLM([{"beats": [{"sentence_count": 2, "visual": "two boxes"}]}])
    Storyboarder(llm).plan(RenderSection(index=1, title="Why", narration="It is fast. It is simple."))
    return " ".join(llm.prompts[0].split())


def test_the_storyboard_prompt_limits_items_and_asks_where_each_one_sits():
    prompt = storyboard_prompt()

    assert "Plan at most 6 labelled items per beat and say where each one sits (left, right, top, bottom, centre)." in prompt


def test_the_storyboard_prompt_allows_3d_visuals_for_spatial_ideas():
    prompt = storyboard_prompt()

    assert "A visual may be described as 3D when the idea is spatial (layers, matrices, vectors, stacks)." in prompt

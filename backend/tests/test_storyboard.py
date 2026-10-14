import pytest

from animation.storyboard import (
    FALLBACK_VISUAL,
    Beat,
    PlannedBeat,
    Storyboard,
    beats_from_storyboard,
    fallback_beats,
    merge_short_beats,
    split_sentences,
)


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

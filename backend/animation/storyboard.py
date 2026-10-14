import math
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field


MAX_BEATS = 8
MIN_BEAT_WORDS = 8
FALLBACK_BEAT_WORDS = 25
FALLBACK_VISUAL = "Illustrate what the narration says."

# Closing quotes and brackets stay attached to their sentence: the lookbehind
# includes them instead of consuming them. Each alternative is fixed width.
_CLOSERS = "\"')’”"
_SENTENCE_BREAK = re.compile(rf"(?<=[.!?])\s+|(?<=[.!?][{_CLOSERS}])\s+")


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_BREAK.split(text.strip()) if part.strip()]


class Beat(BaseModel):
    sentence_count: int = Field(description="How many consecutive narration sentences this beat covers.")
    visual: str = Field(description="What is on screen while those sentences are spoken.")


class Storyboard(BaseModel):
    beats: list[Beat] = Field(description="Beats in order; sentence_count values sum to the sentence total.")


@dataclass(frozen=True)
class PlannedBeat:
    text: str
    visual: str


def _words(text: str) -> int:
    return len(text.split())


def beats_from_storyboard(sentences: list[str], storyboard: Storyboard) -> list[PlannedBeat]:
    beats = storyboard.beats
    if not 1 <= len(beats) <= MAX_BEATS:
        raise ValueError(f"A storyboard needs 1 to {MAX_BEATS} beats, got {len(beats)}.")
    if any(beat.sentence_count < 1 for beat in beats):
        raise ValueError("Every beat must cover at least one sentence.")
    total = sum(beat.sentence_count for beat in beats)
    if total != len(sentences):
        raise ValueError(f"Beat sentence counts add up to {total} but there are {len(sentences)} sentences.")
    if any(not beat.visual.strip() for beat in beats):
        raise ValueError("Every beat needs a visual description.")

    planned: list[PlannedBeat] = []
    position = 0
    for beat in beats:
        text = " ".join(sentences[position:position + beat.sentence_count])
        planned.append(PlannedBeat(text=text, visual=beat.visual.strip()))
        position += beat.sentence_count
    return planned


def merge_short_beats(beats: list[PlannedBeat], min_words: int = MIN_BEAT_WORDS) -> list[PlannedBeat]:
    merged = list(beats)
    while len(merged) > 1:
        short = next((i for i, beat in enumerate(merged) if _words(beat.text) < min_words), None)
        if short is None:
            break
        other = short + 1 if short + 1 < len(merged) else short - 1
        first, second = sorted((short, other))
        merged[first:second + 1] = [
            PlannedBeat(
                text=f"{merged[first].text} {merged[second].text}",
                visual=f"{merged[first].visual} {merged[second].visual}",
            )
        ]
    return merged


def fallback_beats(sentences: list[str], min_words: int = FALLBACK_BEAT_WORDS) -> list[PlannedBeat]:
    total = sum(_words(sentence) for sentence in sentences)
    target = max(min_words, math.ceil(total / MAX_BEATS))

    groups: list[list[str]] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        current.append(sentence)
        count += _words(sentence)
        if count >= target:
            groups.append(current)
            current, count = [], 0
    if current:
        if groups and count < min_words:
            groups[-1].extend(current)
        else:
            groups.append(current)

    return [PlannedBeat(text=" ".join(group), visual=FALLBACK_VISUAL) for group in groups]

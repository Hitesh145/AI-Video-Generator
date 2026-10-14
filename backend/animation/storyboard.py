import math
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from animation.schemas import RenderSection


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


class StructuredGenerator(Protocol):
    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        ...


class Storyboarder:
    def __init__(self, llm: StructuredGenerator, max_attempts: int = 2) -> None:
        self.llm = llm
        self.max_attempts = max_attempts

    def plan(self, section: RenderSection) -> tuple[list[PlannedBeat], list[str]]:
        sentences = split_sentences(section.narration) or [section.title]
        error: str | None = None

        for _ in range(self.max_attempts):
            prompt = self._build_prompt(section, sentences, error)
            try:
                result = self.llm.generate_structured(prompt, Storyboard)
                storyboard = Storyboard.model_validate(result.model_dump())
                beats = beats_from_storyboard(sentences, storyboard)
            except Exception as exc:
                error = str(exc)
                continue
            return merge_short_beats(beats), []

        warning = f"Section '{section.title}': storyboard failed ({error}); using plain narration beats."
        return fallback_beats(sentences), [warning]

    def _build_prompt(self, section: RenderSection, sentences: list[str], error: str | None) -> str:
        numbered = "\n".join(f"{number}. {sentence}" for number, sentence in enumerate(sentences, start=1))
        rejected = ""
        if error is not None:
            rejected = f"\nYour previous plan was rejected: {error}\nFix it and return a corrected plan.\n"

        return f"""
You are planning the visuals for one section of an educational video.

Section title: {section.title}

The narration is split into {len(sentences)} numbered sentences:
{numbered}

Group the sentences, in order, into between 1 and {MAX_BEATS} beats. For each beat give
sentence_count (how many consecutive sentences it covers) and visual (what is on screen
while those sentences are spoken). The sentence_count values must add up to exactly {len(sentences)}.

Rules:
1. Group sentences that explain one showable idea. Each beat should cover at least about 15 words.
2. A visual may only depict what its sentences actually state. Do not invent numbers,
   examples or steps that the narration does not mention. If the narration is abstract,
   describe an abstract diagram, not a worked example.
3. Keep objects and layout consistent from one beat to the next (the same box stays the same box).
4. Text on screen is short labels only, never the narration itself.
5. Describe shapes, arrows, diagrams and motion in one or two plain sentences per beat.
{rejected}
"""

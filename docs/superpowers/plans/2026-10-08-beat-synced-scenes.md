# Beat-Synced Scenes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LLM-written (codegen) scenes show each sentence's visual while that sentence is spoken, by planning beats, timing audio per beat, and forcing the scene to follow a beat clock.

**Architecture:** Narration is split into sentences, a Storyboarder LLM call groups them into beats with a visual description each, and each beat is synthesized separately so its duration is known. The codegen prompt receives beats plus durations and must use `BeatClock` (in the style kit), which pads each beat to its exact audio end and writes a timing report. The generator reads the report and retries on mismatch. Trace sections are untouched.

**Tech Stack:** Python 3, FastAPI backend, Pydantic, Manim Community 0.21 (subprocess render), ffmpeg, edge-tts, Gemini via `LLMService.generate_structured`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-08-beat-synced-scenes-design.md`

## Global Constraints

- All commands run from `backend/` (`cd backend`). Default tests: `python -m pytest -q` (excludes `slow`). Full: `python -m pytest -q -m "slow or not slow"`.
- Tests import fakes with `from fakes import FakeLLM`. `FakeLLM(responses)` returns queued dicts/models or raises queued exceptions, and records `.prompts`.
- Manim: Community 0.21, subprocess only, 854x480, 30 fps, `Text` only (no LaTeX). `scene.renderer.time` advances exactly by each `play`/`wait` `run_time`.
- `animation/codegen/kit.py` is copied next to generated scenes and must import only `manim` plus the standard library.
- Generated code AST allowlist stays `manim, math, random, numpy, kit`; `validator.py` is unchanged.
- The script text is not rewritten by the storyboard step; speech and subtitles show the script verbatim.
- Trace sections, the router, `LessonScript`, the API response shape and the slideshow renderer are not changed.
- Gemini gotchas: no JSON-in-a-string fields, no optional fields in LLM schemas, no nested lists of lists; validate in code, not in schema bounds.
- Commits end with the trailer `Co-Authored-By: Claude Code <noreply@anthropic.com>`. Stage files by name; never `git add -A` (the working tree has many unrelated `backend/output/**` deletions).

## Review Focus

1. **Empty or whitespace narration:** `Storyboarder.plan` must still return one beat (the section title as the sentence), not crash. Tested in Task 2.
2. **Quotes and decimals in narration:** a closing quote stays attached to its sentence; `3.5 apples` is not split. Tested in Task 1.
3. **Scene never calls, or miscounts, `clock.end_beat()`:** the attempt fails with a precise message and is retried; never silently accepted. Tested in Task 4.
4. **Garbage storyboard (counts not summing, zero count, 9+ beats, blank visual, LLM error):** retried once, then deterministic fallback beats plus a warning. Tested in Tasks 1-2.
5. **A TTS failure for one beat, and many tiny beats:** a failed beat becomes silence with a warning without losing the other beats; tiny beats are merged so no beat is under 8 words. Tested in Tasks 1 and 5.

## File Structure

- Create `backend/animation/storyboard.py` - sentence splitting, beat schemas, validation, merge, fallback, `Storyboarder`.
- Modify `backend/animation/codegen/kit.py` - add `BeatClock`.
- Modify `backend/animation/codegen/generator.py` - beats and durations in, `CodegenResult` out, timing report check.
- Modify `backend/animation/codegen/examples/title_card.py`, `process_flow.py` - use `BeatClock`.
- Modify `backend/animation/section_animator.py` - codegen branch becomes per-beat.
- Modify `backend/main.py` - wire `Storyboarder`.
- Modify `backend/services/script_writer_service.py` - three prompt rules.
- Tests: create `tests/test_storyboard.py`, `tests/test_beat_clock.py`, `tests/test_script_writer.py`; rewrite `tests/test_codegen_generator.py`, `tests/test_section_animator.py`; update `tests/test_end_to_end.py`.

## Deviations from the spec (decided while planning)

- Beat durations reach the scene through env var `BEAT_DURATIONS` (JSON list), next to `BEAT_REPORT`; both go through the existing `extra_env` of `render_manim_scene`. This avoids templating numbers into LLM-written code.
- `CodegenRenderer.render` returns `CodegenResult(path, warnings)` so a late-but-accepted render can carry a warning.
- "Accept on the last attempt" is generalised: after all attempts, the render with the smallest overrun (soft failure only) is accepted with a warning. A wrong or missing `end_beat` count is never accepted.

---

### Task 1: Storyboard pure functions

**Files:**
- Create: `backend/animation/storyboard.py`
- Test: `backend/tests/test_storyboard.py`

**Interfaces:**
- Consumes: nothing.
- Produces (all in `animation.storyboard`):
  - constants `MAX_BEATS = 8`, `MIN_BEAT_WORDS = 8`, `FALLBACK_BEAT_WORDS = 25`, `FALLBACK_VISUAL`
  - `split_sentences(text: str) -> list[str]`
  - pydantic `Beat(sentence_count: int, visual: str)`, `Storyboard(beats: list[Beat])`
  - frozen dataclass `PlannedBeat(text: str, visual: str)`
  - `beats_from_storyboard(sentences: list[str], storyboard: Storyboard) -> list[PlannedBeat]` (raises `ValueError`)
  - `merge_short_beats(beats: list[PlannedBeat], min_words: int = 8) -> list[PlannedBeat]`
  - `fallback_beats(sentences: list[str], min_words: int = 25) -> list[PlannedBeat]`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_storyboard.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_storyboard.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'animation.storyboard'`.

- [ ] **Step 3: Implement**

Create `backend/animation/storyboard.py`:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_storyboard.py -q`
Expected: all pass. If the closing-quote test fails, the regex lookbehind is the cause: each alternative must stay fixed width.

- [ ] **Step 5: Commit**

```bash
git add animation/storyboard.py tests/test_storyboard.py
git commit -m "Add sentence splitting and beat planning helpers" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: Storyboarder (LLM call, retry, fallback)

**Files:**
- Modify: `backend/animation/storyboard.py` (imports at top, class appended)
- Test: `backend/tests/test_storyboard.py` (append)

**Interfaces:**
- Consumes (Task 1): `split_sentences`, `Storyboard`, `PlannedBeat`, `beats_from_storyboard`, `merge_short_beats`, `fallback_beats`. Also `animation.schemas.RenderSection(index, title, narration)`.
- Produces: `Storyboarder(llm, max_attempts: int = 2)` with `plan(section: RenderSection) -> tuple[list[PlannedBeat], list[str]]` (beats, warnings). Never raises for LLM or validation problems; always returns at least one beat. `llm` is anything with `generate_structured(prompt, schema)`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_storyboard.py` (add `Storyboarder` to the existing import list from `animation.storyboard`, and add `from animation.schemas import RenderSection` and `from fakes import FakeLLM` at the top):

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_storyboard.py -q`
Expected: `ImportError: cannot import name 'Storyboarder'`.

- [ ] **Step 3: Implement**

In `backend/animation/storyboard.py` change the imports to:

```python
import math
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from animation.schemas import RenderSection
```

Append to the end of the file:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_storyboard.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add animation/storyboard.py tests/test_storyboard.py
git commit -m "Add Storyboarder that plans beats with a deterministic fallback" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: BeatClock in the style kit

**Files:**
- Modify: `backend/animation/codegen/kit.py`
- Test: `backend/tests/test_beat_clock.py` (create)

**Interfaces:**
- Consumes: Manim `Scene` objects (needs `scene.renderer.time` and `scene.wait(seconds)`).
- Produces (importable by generated scenes via `from kit import *`):
  - `BEAT_DURATIONS_ENV = "BEAT_DURATIONS"` (env var holding a JSON list of beat durations in seconds)
  - `BEAT_REPORT_ENV = "BEAT_REPORT"` (env var holding the report file path)
  - `BeatClock(scene, durations: list[float] | None = None)`; `durations=None` reads `BEAT_DURATIONS`, and raises `ValueError` if it is unset
  - `BeatClock.end_beat()`: waits until the cumulative end of the next beat; raises `ValueError("end_beat() was called N times but there are only M beats.")` on the extra call; rewrites the report after every call
  - Report file format: JSON list of `{"beat": int (1-based), "expected_end": float, "actual_end": float, "overrun": float}`; times are seconds relative to the clock's start, overrun is `max(0, actual - expected)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_beat_clock.py`:

```python
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from animation.codegen import kit
from animation.codegen.kit import BEAT_DURATIONS_ENV, BEAT_REPORT_ENV, BeatClock
from animation.templates.render import render_manim_scene
from animation.timing import probe_duration


class FakeScene:
    def __init__(self, start: float = 0.0) -> None:
        self.renderer = SimpleNamespace(time=start)
        self.waits: list[float] = []

    def advance(self, seconds: float) -> None:
        self.renderer.time += seconds

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.renderer.time += seconds


def test_end_beat_waits_until_the_beat_end(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene()
    clock = BeatClock(scene, [1.0, 2.0])

    scene.advance(0.4)
    clock.end_beat()
    scene.advance(0.5)
    clock.end_beat()

    assert scene.renderer.time == pytest.approx(3.0)
    assert scene.waits == pytest.approx([0.6, 1.5])
    assert [r["overrun"] for r in clock.report] == [0.0, 0.0]


def test_overrunning_beat_is_reported_and_next_beat_recovers(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene()
    clock = BeatClock(scene, [1.0, 1.0, 1.0])

    scene.advance(1.6)          # beat 1 is 0.6 s late
    clock.end_beat()
    scene.advance(0.1)
    clock.end_beat()            # absolute end is 2.0, we are at 1.7: waits 0.3
    scene.advance(0.2)
    clock.end_beat()

    assert [r["overrun"] for r in clock.report] == pytest.approx([0.6, 0.0, 0.0])
    assert scene.renderer.time == pytest.approx(3.0)


def test_clock_is_relative_to_where_the_scene_already_is(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene(start=5.0)
    clock = BeatClock(scene, [2.0])

    clock.end_beat()

    assert scene.renderer.time == pytest.approx(7.0)
    assert clock.report[0]["expected_end"] == pytest.approx(2.0)


def test_tiny_remainders_are_not_waited(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene()
    clock = BeatClock(scene, [1.0])

    scene.advance(0.99)
    clock.end_beat()

    assert scene.waits == []


def test_extra_end_beat_raises(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    clock = BeatClock(FakeScene(), [1.0])
    clock.end_beat()

    with pytest.raises(ValueError, match="called 2 times but there are only 1 beats"):
        clock.end_beat()


def test_report_is_rewritten_after_every_call(monkeypatch, tmp_path):
    report = tmp_path / "report.json"
    monkeypatch.setenv(BEAT_REPORT_ENV, str(report))
    clock = BeatClock(FakeScene(), [1.0, 1.0])

    clock.end_beat()
    assert [r["beat"] for r in json.loads(report.read_text(encoding="utf-8"))] == [1]
    clock.end_beat()
    assert [r["beat"] for r in json.loads(report.read_text(encoding="utf-8"))] == [1, 2]


def test_durations_come_from_the_environment(monkeypatch):
    monkeypatch.setenv(BEAT_DURATIONS_ENV, json.dumps([1.5, 2.5]))
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene()
    clock = BeatClock(scene)

    clock.end_beat()
    clock.end_beat()

    assert scene.renderer.time == pytest.approx(4.0)


def test_missing_durations_raise(monkeypatch):
    monkeypatch.delenv(BEAT_DURATIONS_ENV, raising=False)

    with pytest.raises(ValueError, match=BEAT_DURATIONS_ENV):
        BeatClock(FakeScene())


SCENE = """
from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
        clock = BeatClock(self)
        self.play(FadeIn(Square()), run_time=0.5)
        clock.end_beat()
        self.play(FadeIn(Circle()), run_time=1.6)
        clock.end_beat()
        self.play(FadeIn(Triangle()), run_time=0.2)
        clock.end_beat()
"""


@pytest.mark.slow
def test_real_manim_render_follows_the_beat_clock(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    shutil.copyfile(Path(kit.__file__), work / "kit.py")
    scene_file = work / "section_scene.py"
    scene_file.write_text(SCENE, encoding="utf-8")
    report = tmp_path / "report.json"

    out = render_manim_scene(
        scene_file,
        "SectionScene",
        work,
        tmp_path / "out.mp4",
        extra_env={BEAT_DURATIONS_ENV: json.dumps([1.0, 1.0, 1.0]), BEAT_REPORT_ENV: str(report)},
        pythonpath=work,
        timeout_seconds=120,
    )

    rows = json.loads(report.read_text(encoding="utf-8"))
    assert [r["overrun"] for r in rows] == pytest.approx([0.0, 0.6, 0.0], abs=0.05)
    assert probe_duration(out) == pytest.approx(3.0, abs=0.15)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_beat_clock.py -q`
Expected: `ImportError: cannot import name 'BEAT_DURATIONS_ENV' from 'animation.codegen.kit'`.

- [ ] **Step 3: Implement**

In `backend/animation/codegen/kit.py` change the import block at the top to:

```python
import json
import os

from manim import DOWN, LEFT, UP, RIGHT, Mobject, Text, VGroup, config
```

and append at the end of the file:

```python
BEAT_DURATIONS_ENV = "BEAT_DURATIONS"
BEAT_REPORT_ENV = "BEAT_REPORT"
_MIN_WAIT = 0.04


class BeatClock:
    """Keeps a scene on its audio schedule.

    Call end_beat() after the animations of each beat. It waits until the
    cumulative end time of that beat, so an early beat is padded and a late
    beat does not push later beats off their absolute schedule. The report is
    rewritten after every call so a scene that crashes later still leaves a
    partial report.
    """

    def __init__(self, scene, durations=None):
        if durations is None:
            raw = os.environ.get(BEAT_DURATIONS_ENV)
            if not raw:
                raise ValueError(f"{BEAT_DURATIONS_ENV} is not set; pass durations explicitly.")
            durations = json.loads(raw)

        self.scene = scene
        self.durations = [float(duration) for duration in durations]
        self.ends = []
        total = 0.0
        for duration in self.durations:
            total += duration
            self.ends.append(total)
        self.start = scene.renderer.time
        self.report = []

    def end_beat(self):
        done = len(self.report)
        if done >= len(self.durations):
            raise ValueError(
                f"end_beat() was called {done + 1} times but there are only {len(self.durations)} beats."
            )

        expected = self.start + self.ends[done]
        remaining = expected - self.scene.renderer.time
        if remaining > _MIN_WAIT:
            self.scene.wait(remaining)

        actual = self.scene.renderer.time
        self.report.append({
            "beat": done + 1,
            "expected_end": round(expected - self.start, 3),
            "actual_end": round(actual - self.start, 3),
            "overrun": round(max(0.0, actual - expected), 3),
        })
        self._write_report()

    def _write_report(self):
        path = os.environ.get(BEAT_REPORT_ENV)
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.report, handle)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_beat_clock.py -q` then `python -m pytest tests/test_beat_clock.py -q -m slow`
Expected: 8 fast tests pass, then the slow real render passes (about 10-20 s).

- [ ] **Step 5: Commit**

```bash
git add animation/codegen/kit.py tests/test_beat_clock.py
git commit -m "Add BeatClock to the style kit" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: CodegenRenderer takes beats and checks the timing report

**Files:**
- Modify: `backend/animation/codegen/generator.py` (rewrite)
- Modify: `backend/animation/codegen/examples/title_card.py`, `backend/animation/codegen/examples/process_flow.py`
- Test: `backend/tests/test_codegen_generator.py` (rewrite)

**Interfaces:**
- Consumes (Task 1): `PlannedBeat(text, visual)`. Consumes (Task 3): `BeatClock` and the env var names, which the generator re-declares (importing `kit` would pull Manim into the server process); a test pins them equal.
- Produces (in `animation.codegen.generator`):
  - `BEAT_DURATIONS_ENV`, `BEAT_REPORT_ENV`, `MAX_OVERRUN_SECONDS = 1.0`
  - `SceneRenderer = Callable[[Path, str, Path, Path, dict[str, str]], Path]` (scene file, scene name, work dir, output path, extra env)
  - `default_scene_renderer(scene_file, scene_name, work_dir, output_path, extra_env) -> Path`
  - `CodegenResult(path: Path, warnings: list[str])` (frozen dataclass)
  - `TimingCheck(error: str | None, hard: bool, worst_overrun: float)` and `check_beat_report(report_path: Path, beat_count: int) -> TimingCheck`
  - `CodegenRenderer(llm, scene_renderer=default_scene_renderer, max_attempts=3).render(section, beats, durations, work_dir, output_path, artifacts_dir) -> CodegenResult`; raises `ValueError` if `beats` is empty or `len(beats) != len(durations)`; raises `CodegenFailed(errors)` when no attempt is usable.
  - Unchanged: `GeneratedScene`, `CodegenFailed`, `EXAMPLES_DIR`, `KIT_FILE`, `MAX_ATTEMPTS`.
- Failure classes: a missing/unreadable report or a wrong `end_beat` count is **hard** (attempt fails, never accepted). An overrun above `MAX_OVERRUN_SECONDS` is **soft** (attempt fails and is retried; if the attempts run out, the soft one with the smallest worst overrun is accepted with a warning).

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/test_codegen_generator.py` with:

```python
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
    return [
        {"beat": i + 1, "expected_end": float(i + 1), "actual_end": float(i + 1) + o, "overrun": o}
        for i, o in enumerate(overruns)
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
@pytest.mark.parametrize("example", ["title_card.py", "process_flow.py"])
def test_examples_render_for_real_on_the_beat_clock(tmp_path, example):
    code = (EXAMPLES_DIR / example).read_text(encoding="utf-8")
    beats = [PlannedBeat("one", "a"), PlannedBeat("two", "b"), PlannedBeat("three", "c")]

    result = CodegenRenderer(FakeLLM([{"code": code}]), scene_renderer=default_scene_renderer).render(
        SECTION, beats, [2.5, 2.5, 2.5], tmp_path / "work", tmp_path / "out.mp4", tmp_path / "artifacts"
    )

    assert result.warnings == []
    assert probe_duration(result.path) == pytest.approx(7.5, abs=0.2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_codegen_generator.py -q`
Expected: `ImportError: cannot import name 'BEAT_DURATIONS_ENV' from 'animation.codegen.generator'`.

- [ ] **Step 3: Rewrite the generator**

Replace `backend/animation/codegen/generator.py` with:

````python
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from pydantic import BaseModel, Field

from animation.codegen.validator import validate_scene_code
from animation.schemas import RenderSection
from animation.storyboard import PlannedBeat
from animation.templates.render import RenderError, render_manim_scene


KIT_FILE = Path(__file__).with_name("kit.py")
EXAMPLES_DIR = Path(__file__).with_name("examples")
MAX_ATTEMPTS = 3
RENDER_TIMEOUT_SECONDS = 120
MAX_OVERRUN_SECONDS = 1.0

# Must equal the constants in kit.py (a test pins this); the kit cannot be
# imported here because it pulls Manim into the server process.
BEAT_DURATIONS_ENV = "BEAT_DURATIONS"
BEAT_REPORT_ENV = "BEAT_REPORT"

SceneRenderer = Callable[[Path, str, Path, Path, dict[str, str]], Path]


class StructuredGenerator(Protocol):
    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        ...


class GeneratedScene(BaseModel):
    code: str = Field(description="Complete Python source of the Manim scene file.")


class CodegenFailed(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Generated animation failed: " + " | ".join(errors))


@dataclass(frozen=True)
class CodegenResult:
    path: Path
    warnings: list[str]


@dataclass(frozen=True)
class TimingCheck:
    error: str | None
    hard: bool
    worst_overrun: float


def default_scene_renderer(
    scene_file: Path,
    scene_name: str,
    work_dir: Path,
    output_path: Path,
    extra_env: dict[str, str],
) -> Path:
    return render_manim_scene(
        scene_file,
        scene_name,
        work_dir,
        output_path,
        extra_env=extra_env,
        pythonpath=work_dir,
        timeout_seconds=RENDER_TIMEOUT_SECONDS,
    )


def check_beat_report(report_path: Path, beat_count: int) -> TimingCheck:
    if not report_path.exists():
        return TimingCheck(
            "The scene never called clock.end_beat(). Create `clock = BeatClock(self)` first and "
            "call clock.end_beat() at the end of every beat.",
            True,
            0.0,
        )
    try:
        rows = json.loads(report_path.read_text(encoding="utf-8"))
        overruns = [float(row["overrun"]) for row in rows]
    except Exception as exc:
        return TimingCheck(f"The beat report could not be read ({exc}).", True, 0.0)

    if len(overruns) != beat_count:
        return TimingCheck(
            f"The scene called clock.end_beat() {len(overruns)} times but there are {beat_count} beats. "
            "Call it exactly once at the end of each beat.",
            True,
            0.0,
        )

    worst = max(overruns)
    if worst > MAX_OVERRUN_SECONDS:
        last = overruns.index(worst) + 1
        first = next(i for i, overrun in enumerate(overruns) if overrun > 0) + 1
        where = f"beat {last}" if first == last else f"beats {first}-{last}"
        return TimingCheck(
            f"Beat {last} ended {worst:.1f} s after its audio ended; the animations in {where} ran too long. "
            "Shorten them so the animations of each beat take at most 85% of its duration.",
            False,
            worst,
        )
    return TimingCheck(None, False, worst)


class CodegenRenderer:
    def __init__(
        self,
        llm: StructuredGenerator,
        scene_renderer: SceneRenderer = default_scene_renderer,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.llm = llm
        self.scene_renderer = scene_renderer
        self.max_attempts = max_attempts

    def render(
        self,
        section: RenderSection,
        beats: list[PlannedBeat],
        durations: list[float],
        work_dir: Path,
        output_path: Path,
        artifacts_dir: Path,
    ) -> CodegenResult:
        if not beats or len(beats) != len(durations):
            raise ValueError("render needs at least one beat and exactly one duration per beat.")

        artifacts_dir.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        previous_code: str | None = None
        previous_error: str | None = None
        best_late: tuple[float, Path, str] | None = None

        for attempt in range(1, self.max_attempts + 1):
            stem = artifacts_dir / f"section_{section.index}_attempt_{attempt}"
            prompt = self._build_prompt(section, beats, durations, previous_code, previous_error)

            try:
                result = self.llm.generate_structured(prompt, GeneratedScene)
                code = GeneratedScene.model_validate(result.model_dump()).code
            except Exception as exc:
                error = f"LLM call failed: {exc}"
                stem.with_suffix(".log").write_text(error, encoding="utf-8")
                errors.append(f"attempt {attempt}: {error}")
                continue

            stem.with_suffix(".py").write_text(code, encoding="utf-8")
            problems = validate_scene_code(code)
            if problems:
                error = "Code rejected by validator:\n" + "\n".join(problems)
            else:
                attempt_dir = work_dir / f"attempt_{attempt}"
                attempt_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(KIT_FILE, attempt_dir / "kit.py")
                scene_file = attempt_dir / "section_scene.py"
                scene_file.write_text(code, encoding="utf-8")
                report_path = (attempt_dir / "beat_report.json").resolve()
                report_path.unlink(missing_ok=True)
                attempt_output = attempt_dir / "scene.mp4"
                env = {BEAT_DURATIONS_ENV: json.dumps(durations), BEAT_REPORT_ENV: str(report_path)}
                try:
                    self.scene_renderer(scene_file, "SectionScene", attempt_dir, attempt_output, env)
                except RenderError as exc:
                    error = f"Render failed:\n{exc}"
                else:
                    check = check_beat_report(report_path, len(beats))
                    if check.error is None:
                        shutil.copyfile(attempt_output, output_path)
                        return CodegenResult(output_path, [])
                    error = check.error
                    if not check.hard and (best_late is None or check.worst_overrun < best_late[0]):
                        best_late = (check.worst_overrun, attempt_output, check.error)

            stem.with_suffix(".log").write_text(error, encoding="utf-8")
            errors.append(f"attempt {attempt}: {error.splitlines()[0]}")
            previous_code = code
            previous_error = error

        if best_late is not None:
            _, late_path, message = best_late
            shutil.copyfile(late_path, output_path)
            warning = f"Section '{section.title}': animation ran late against the narration ({message})"
            return CodegenResult(output_path, [warning])
        raise CodegenFailed(errors)

    def _build_prompt(
        self,
        section: RenderSection,
        beats: list[PlannedBeat],
        durations: list[float],
        previous_code: str | None,
        previous_error: str | None,
    ) -> str:
        examples = "\n\n".join(
            f"--- {path.name} ---\n{path.read_text(encoding='utf-8')}"
            for path in sorted(EXAMPLES_DIR.glob("*.py"))
        )
        beat_lines = "\n\n".join(
            f"Beat {number} ({duration:.1f} s)\nNarration: {beat.text}\nVisual: {beat.visual}"
            for number, (beat, duration) in enumerate(zip(beats, durations), start=1)
        )
        count = len(beats)
        retry = ""
        if previous_code is not None and previous_error is not None:
            retry = f"""
Your previous attempt failed. Fix the problem and return the whole corrected file.

Previous code:
```python
{previous_code}
```

Error:
{previous_error}
"""

        return f"""
You are writing a Manim Community Edition scene for one section of an educational video.
The narration is spoken in {count} beats. Each beat's visuals must be on screen while
that beat's narration is spoken.

Section title: {section.title}

{beat_lines}

Start the file with:
from manim import *
from kit import *

Style kit available from `kit`:
- Colours: BACKGROUND, TEXT_COLOR, MUTED, CELL, CELL_STROKE, HIGHLIGHT, SORTED, FOUND, POINTER, ACCENT
- title(text) -> Text placed at the top edge
- fit_in_frame(mobject) -> scales/shifts the mobject so it stays on screen and above the subtitle area
- bullet_list(items) -> VGroup of bullet lines, already fitted
- caption_safe_area() -> (ymin, ymax); keep everything between these y values, subtitles cover the bottom 15%
- BeatClock(self) -> the beat clock; clock.end_beat() waits until the end of the current beat's audio

Rules:
1. Define exactly one class, `class SectionScene(Scene):`, with a `construct(self)` method. No other classes.
2. Only import from manim, kit, math, random and numpy.
3. Use Text or MarkupText for all text. Never use Tex, MathTex or anything that needs LaTeX.
4. No file, network or OS access. No dunder names, getattr/setattr, eval/exec or open.
5. Keep everything on screen: call fit_in_frame on large groups.
6. Visualise the idea with shapes, arrows, diagrams and motion. Keep on-screen text short;
   do not put the narration on screen.
7. Return the complete file in the `code` field.
8. Timing: the first line of construct must be `clock = BeatClock(self)`. Then write one block per
   beat, in order, each starting with a `# beat N` comment and ending with `clock.end_beat()`.
   Call clock.end_beat() exactly {count} times in total.
9. Never use self.wait(...) to pad a beat. clock.end_beat() adds any waiting that is needed.
10. The animations inside a beat must take at most 85% of that beat's duration in total
    (add up the run_time values). A beat that runs longer than its audio makes the video late.
11. Only show what the beat's narration states. Do not invent numbers, examples or steps.
    If the narration is abstract, draw an abstract diagram.
12. Keep objects consistent across beats: reuse and transform what is already on screen
    instead of redrawing it.

Examples of good scenes (they use 3 beats of 2.5 s each):

{examples}
{retry}
"""
````

- [ ] **Step 4: Update the two examples to use the beat clock**

Replace `backend/animation/codegen/examples/title_card.py` with:

```python
from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
        clock = BeatClock(self)
        heading = title("What makes an algorithm?")
        points = bullet_list(["Clear input", "Finite steps", "Correct output"])
        points.next_to(heading, DOWN, buff=0.6)
        fit_in_frame(points)

        # beat 1: the question appears
        self.play(Write(heading), run_time=1.0)
        clock.end_beat()

        # beat 2: first two properties
        self.play(FadeIn(points[0], shift=RIGHT * 0.3), run_time=0.6)
        self.play(FadeIn(points[1], shift=RIGHT * 0.3), run_time=0.6)
        clock.end_beat()

        # beat 3: last property
        self.play(FadeIn(points[2], shift=RIGHT * 0.3), run_time=0.6)
        clock.end_beat()
```

Replace `backend/animation/codegen/examples/process_flow.py` with:

```python
from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
        clock = BeatClock(self)
        heading = title("Input to output")
        boxes = VGroup(*[
            VGroup(
                RoundedRectangle(
                    width=2.6, height=1.2, corner_radius=0.2,
                    color=ACCENT, fill_color=CELL, fill_opacity=1,
                ),
                Text(label, font_size=28, color=TEXT_COLOR),
            )
            for label in ["Input", "Process", "Output"]
        ]).arrange(RIGHT, buff=1.0)
        fit_in_frame(boxes)
        arrows = VGroup(*[
            Arrow(boxes[i].get_right(), boxes[i + 1].get_left(), buff=0.1, color=POINTER)
            for i in range(len(boxes) - 1)
        ])

        # beat 1: something goes in
        self.play(FadeIn(heading), run_time=0.8)
        self.play(FadeIn(boxes[0], shift=UP * 0.3), run_time=0.7)
        clock.end_beat()

        # beat 2: it is processed
        self.play(GrowArrow(arrows[0]), FadeIn(boxes[1], shift=UP * 0.3), run_time=0.8)
        self.play(boxes[1][0].animate.set_fill(HIGHLIGHT, opacity=1), run_time=0.6)
        clock.end_beat()

        # beat 3: a result comes out
        self.play(GrowArrow(arrows[1]), FadeIn(boxes[2], shift=UP * 0.3), run_time=0.8)
        clock.end_beat()
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_codegen_generator.py -q` then `python -m pytest tests/test_codegen_generator.py -q -m slow`
Expected: all fast tests pass; both slow example renders pass with a clip of about 7.5 s and no warnings. If a slow example reports a late beat, shorten its animations (never add `self.wait`).

Note: `tests/test_section_animator.py` and `tests/test_end_to_end.py` still use the old signature and fail until Task 5. That is expected here; do not run the whole suite yet.

- [ ] **Step 6: Commit**

```bash
git add animation/codegen/generator.py animation/codegen/examples/title_card.py animation/codegen/examples/process_flow.py tests/test_codegen_generator.py
git commit -m "Make codegen follow beats and verify timing from the beat report" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: SectionAnimator codegen path, wiring and end-to-end test

**Files:**
- Modify: `backend/animation/section_animator.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_section_animator.py` (rewrite), `backend/tests/test_end_to_end.py` (update)

**Interfaces:**
- Consumes (Task 1-2): `PlannedBeat`, `Storyboarder.plan(section) -> (list[PlannedBeat], list[str])`. Consumes (Task 4): `CodegenResult`, `CodegenRenderer.render(section, beats, durations, work_dir, output_path, artifacts_dir) -> CodegenResult`.
- Produces: `SectionAnimator(router, narrator, storyboarder, registry, synthesizer, template_renderer, codegen_renderer, slideshow_renderer, fit_clip=..., build_audio=...)` (new required `storyboarder`, placed after `narrator`; every caller uses keywords). For codegen and slideshow-fallback sections: one wav per beat at `<section_dir>/audio/beat_NNN.wav`, section audio from `build_audio(beat_paths, beat_durations, <section_dir>/narration.m4a)`, `SectionClip.narration_segments` = beat texts, `segment_durations` = beat durations, video fitted to `sum(beat_durations)`. Trace sections are unchanged.

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/test_section_animator.py` with:

```python
from pathlib import Path

import pytest

from animation.codegen.generator import CodegenResult
from animation.narrator import NarratedSegment
from animation.router import ResolvedRoute, RoutingResult
from animation.schemas import RenderSection
from animation.section_animator import SectionAnimator, SectionRenderError
from animation.storyboard import PlannedBeat
from animation.tracers import default_registry
from animation.tracers.binary_search import BinarySearchInput
from services.tts_service import SceneAudio


TRACE_SECTION = RenderSection(index=0, title="Binary search", narration="Watch it halve.")
TEXT_SECTION = RenderSection(index=1, title="Why", narration="It is fast. It is simple.")
BEATS = [PlannedBeat("It is fast.", "a rocket"), PlannedBeat("It is simple.", "a single arrow")]


class FakeRouter:
    def __init__(self, routes, warnings=()):
        self.result = RoutingResult(list(routes), list(warnings))

    def route(self, sections):
        return self.result


class FakeNarrator:
    def narrate(self, section, steps):
        # one sentence for step 0, everything else grouped under a second sentence
        return [
            NarratedSegment("Start.", (0,)),
            NarratedSegment("Then it narrows.", tuple(range(1, len(steps)))),
        ], []


class FakeStoryboarder:
    def __init__(self, beats=BEATS, warnings=()):
        self.beats = list(beats)
        self.warnings = list(warnings)
        self.sections = []

    def plan(self, section):
        self.sections.append(section)
        return list(self.beats), list(self.warnings)


class FakeSynth:
    def synthesize_text(self, text, output_path):
        return SceneAudio(scene_id=output_path.stem, narration_text=text,
                          audio_path=str(output_path), duration_seconds=3.0)


class FakeRenderer:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def render(self, *args):
        self.calls.append(args)
        if self.fail:
            raise RuntimeError("boom")
        # fake_fit ignores the raw clip path, so any path will do
        return Path(args[3])


class FakeCodegen:
    def __init__(self, fail=False, warnings=()):
        self.fail = fail
        self.warnings = list(warnings)
        self.calls = []

    def render(self, section, beats, durations, work_dir, output_path, artifacts_dir):
        self.calls.append((section, beats, durations))
        if self.fail:
            raise RuntimeError("boom")
        return CodegenResult(path=output_path, warnings=list(self.warnings))


def fake_fit(raw, seconds, out):
    return out


def fake_audio(paths, durations, out):
    return out


def make(routes, template=None, codegen=None, slideshow=None, storyboarder=None):
    template = template or FakeRenderer()
    codegen = codegen or FakeCodegen()
    slideshow = slideshow or FakeRenderer()
    animator = SectionAnimator(
        router=FakeRouter(routes),
        narrator=FakeNarrator(),
        storyboarder=storyboarder or FakeStoryboarder(),
        registry=default_registry(),
        synthesizer=FakeSynth(),
        template_renderer=template,
        codegen_renderer=codegen,
        slideshow_renderer=slideshow,
        fit_clip=fake_fit,
        build_audio=fake_audio,
    )
    return animator, template, codegen, slideshow


TRACE_ROUTE = ResolvedRoute(0, "trace", "binary_search",
                            BinarySearchInput(values=[2, 5, 8, 12, 16, 23, 38], target=23))
CODEGEN_ROUTE = ResolvedRoute(1, "codegen")


def test_trace_path_times_steps_from_segment_audio(tmp_path):
    animator, template, _, _ = make([TRACE_ROUTE])

    clips, warnings = animator.animate([TRACE_SECTION], tmp_path)

    clip = clips[0]
    assert clip.path_used == "trace"
    assert clip.tracer == "binary_search"
    assert clip.narration_segments == ["Start.", "Then it narrows."]
    # 5 steps: segment 1 = step 0 (3.0 s); segment 2 = step 1 narrated + 3 grouped
    # -> max(1.0, 3.0 - 3 * 0.6) + 3 * 0.6 = 3.0 s
    assert clip.segment_durations == pytest.approx([3.0, 3.0])
    title, steps, durations, _, _ = template.calls[0]
    assert len(steps) == len(durations) == 5
    assert durations == pytest.approx([3.0, 1.2, 0.6, 0.6, 0.6])
    assert warnings == []


def test_codegen_route_plans_beats_and_passes_their_durations(tmp_path):
    storyboarder = FakeStoryboarder()
    animator, _, codegen, _ = make([CODEGEN_ROUTE], storyboarder=storyboarder)
    fits = []
    animator.fit_clip = lambda raw, seconds, out: fits.append(seconds) or out

    clips, warnings = animator.animate([TEXT_SECTION], tmp_path)

    clip = clips[0]
    assert clip.path_used == "codegen"
    assert storyboarder.sections == [TEXT_SECTION]
    section, beats, durations = codegen.calls[0]
    assert beats == BEATS
    assert durations == [3.0, 3.0]
    assert fits == [6.0]
    assert clip.narration_segments == ["It is fast.", "It is simple."]
    assert clip.segment_durations == [3.0, 3.0]
    assert warnings == []


def test_codegen_route_builds_section_audio_from_the_beat_wavs(tmp_path):
    animator, _, _, _ = make([CODEGEN_ROUTE])
    built = []
    animator.build_audio = lambda paths, durations, out: built.append((paths, durations, out)) or out

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    paths, durations, out = built[0]
    assert [p.name for p in paths] == ["beat_000.wav", "beat_001.wav"]
    assert durations == [3.0, 3.0]
    assert clips[0].audio_path == str(out)
    assert out.name == "narration.m4a"


def test_storyboard_warnings_are_reported(tmp_path):
    animator, _, _, _ = make([CODEGEN_ROUTE], storyboarder=FakeStoryboarder(warnings=["plan was plain"]))

    clips, warnings = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].warnings == ["plan was plain"]
    assert warnings == ["plan was plain"]


def test_late_render_warning_from_codegen_is_reported(tmp_path):
    animator, _, _, _ = make([CODEGEN_ROUTE], codegen=FakeCodegen(warnings=["ran late"]))

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "codegen"
    assert clips[0].warnings == ["ran late"]


def test_template_failure_falls_back_to_codegen(tmp_path):
    animator, _, codegen, _ = make([TRACE_ROUTE], template=FakeRenderer(fail=True))

    clips, warnings = animator.animate([TRACE_SECTION], tmp_path)

    assert clips[0].path_used == "codegen"
    assert len(codegen.calls) == 1
    assert "trace animation failed" in clips[0].warnings[0]
    assert warnings == clips[0].warnings


def test_codegen_failure_falls_back_to_slideshow_with_the_same_beats(tmp_path):
    animator, _, _, slideshow = make([CODEGEN_ROUTE], codegen=FakeCodegen(fail=True))

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "slideshow"
    assert slideshow.calls[0][1] == 6.0
    assert clips[0].narration_segments == ["It is fast.", "It is simple."]
    assert clips[0].segment_durations == [3.0, 3.0]
    assert "generated animation failed" in clips[0].warnings[0]


def test_everything_failing_raises(tmp_path):
    animator, _, _, _ = make(
        [CODEGEN_ROUTE],
        codegen=FakeCodegen(fail=True),
        slideshow=FakeRenderer(fail=True),
    )

    with pytest.raises(SectionRenderError, match="Why"):
        animator.animate([TEXT_SECTION], tmp_path)


def test_router_warnings_are_returned(tmp_path):
    animator, _, _, _ = make([CODEGEN_ROUTE])
    animator.router = FakeRouter([CODEGEN_ROUTE], ["router said no"])

    _, warnings = animator.animate([TEXT_SECTION], tmp_path)

    assert warnings == ["router said no"]


def test_unreadable_codegen_clip_falls_back_to_slideshow(tmp_path):
    animator, _, _, slideshow = make([CODEGEN_ROUTE])

    def fit(raw, seconds, out):
        if raw.name == "codegen_raw.mp4":
            raise ValueError("Durations must be greater than 0.")
        return out

    animator.fit_clip = fit
    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "slideshow"
    assert len(slideshow.calls) == 1


class FailsOnceSynth:
    def __init__(self, failing_text):
        self.failing_text = failing_text

    def synthesize_text(self, text, output_path):
        if text == self.failing_text:
            raise RuntimeError("edge-tts network error")
        return FakeSynth().synthesize_text(text, output_path)


def test_one_failed_beat_becomes_silence_and_keeps_the_others(tmp_path):
    animator, _, codegen, _ = make([CODEGEN_ROUTE])
    animator.synthesizer = FailsOnceSynth("It is simple.")

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    clip = clips[0]
    assert clip.path_used == "codegen"
    assert clip.segment_durations[0] == 3.0
    assert clip.segment_durations[1] > 0
    assert len(clip.narration_segments) == 2
    assert "narration audio failed" in clip.warnings[0]
    assert codegen.calls[0][2] == clip.segment_durations
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_section_animator.py -q`
Expected: `TypeError: SectionAnimator.__init__() got an unexpected keyword argument 'storyboarder'`.

- [ ] **Step 3: Implement the codegen path**

In `backend/animation/section_animator.py` make these changes (leave `_trace_section` and the other protocols as they are).

Imports - add:

```python
from animation.codegen.generator import CodegenResult
from animation.storyboard import PlannedBeat
```

Replace the `CodegenSectionRenderer` protocol and add a `BeatPlanner` protocol:

```python
class BeatPlanner(Protocol):
    def plan(self, section: RenderSection) -> tuple[list[PlannedBeat], list[str]]:
        ...


class CodegenSectionRenderer(Protocol):
    def render(
        self,
        section: RenderSection,
        beats: list[PlannedBeat],
        durations: list[float],
        work_dir: Path,
        output_path: Path,
        artifacts_dir: Path,
    ) -> CodegenResult:
        ...
```

In `SectionAnimator.__init__` add the parameter `storyboarder: BeatPlanner` directly after `narrator: Narrator` and store `self.storyboarder = storyboarder`.

In `_animate_section`, keep the trace block, and replace everything from `audio = self._synthesize(section, section.narration, ...)` to the end of the method with:

```python
        return self._codegen_section(section, section_dir, output_dir, warnings)
```

Add this method (after `_animate_section`):

```python
    def _codegen_section(
        self,
        section: RenderSection,
        section_dir: Path,
        output_dir: Path,
        warnings: list[str],
    ) -> SectionClip:
        beats, plan_warnings = self.storyboarder.plan(section)
        warnings.extend(plan_warnings)

        beat_paths: list[Path] = []
        durations: list[float] = []
        texts: list[str] = []
        for number, beat in enumerate(beats):
            audio = self._synthesize(
                section,
                beat.text,
                section_dir / "audio" / f"beat_{number:03d}.wav",
                warnings,
            )
            beat_paths.append(Path(audio.audio_path))
            durations.append(audio.duration_seconds)
            texts.append(audio.narration_text or beat.text)

        total = sum(durations)
        section_audio = self.build_audio(beat_paths, durations, section_dir / "narration.m4a")
        path_used: PathUsed = "codegen"
        clip_path = section_dir / "clip.mp4"
        try:
            # Fitting stays inside the try: a scene can "render" yet produce a
            # clip ffprobe cannot measure, and that must fall back, not crash.
            result = self.codegen_renderer.render(
                section,
                beats,
                durations,
                section_dir / "codegen_work",
                section_dir / "codegen_raw.mp4",
                output_dir / "codegen",
            )
            video = self.fit_clip(result.path, total, clip_path)
            warnings.extend(result.warnings)
        except Exception as exc:
            warnings.append(f"Section '{section.title}': generated animation failed ({exc}); using slideshow.")
            path_used = "slideshow"
            try:
                raw = self.slideshow_renderer.render(
                    section,
                    total,
                    section_dir / "slideshow_work",
                    section_dir / "slideshow_raw.mp4",
                )
                video = self.fit_clip(raw, total, clip_path)
            except Exception as slideshow_exc:
                raise SectionRenderError(
                    f"Section '{section.title}' could not be rendered: {slideshow_exc}"
                ) from slideshow_exc

        return SectionClip(
            section_index=section.index,
            title=section.title,
            video_path=str(video),
            audio_path=str(section_audio),
            narration_segments=texts,
            segment_durations=durations,
            path_used=path_used,
            warnings=warnings,
        )
```

In `backend/main.py` add the import `from animation.storyboard import Storyboarder` next to the other `animation` imports, and add `storyboarder=Storyboarder(llm_service),` to the `SectionAnimator(...)` call directly after `narrator=StepNarrator(llm_service),`.

- [ ] **Step 4: Update the end-to-end test**

In `backend/tests/test_end_to_end.py`:

1. Add `from animation.storyboard import Storyboarder` to the imports.
2. Add below the `Writer` class:

```python
ONE_BEAT_SCENE = """
from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
        clock = BeatClock(self)
        self.play(Write(title("Binary search")), run_time=0.3)
        clock.end_beat()
"""
```

3. In `test_full_lesson_renders_with_mixed_paths` delete the `example = ...` line and replace the `FakeLLM([...])` queue with this order (router, intro storyboard, intro code, trace narrator, conclusion storyboard, conclusion code):

```python
    one_beat = {"beats": [{"sentence_count": 1, "visual": "a title card"}]}
    llm = FakeLLM([
        {"routes": [
            {"section_index": 0, "path": "codegen"},
            {"section_index": 1, "path": "trace", "tracer": "binary_search",
             "values": [2, 5, 8, 12, 16, 23, 38], "target": 23},
            {"section_index": 2, "path": "codegen"},
        ]},
        one_beat,                                            # intro storyboard
        {"code": ONE_BEAT_SCENE},                            # intro codegen
        {"sentences": ["a", "b", "c", "d", "e"],             # binary search narration (5 steps)
         "group_with_previous": [False] * 5},
        one_beat,                                            # conclusion storyboard
        {"code": ONE_BEAT_SCENE},                            # conclusion codegen
    ])
```

4. In the `SectionAnimator(...)` call add `storyboarder=Storyboarder(llm),` after `narrator=StepNarrator(llm),`.
5. Remove the now-unused `EXAMPLES_DIR` from the `animation.codegen.generator` import.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest -q` then `python -m pytest tests/test_end_to_end.py -q -m slow`
Expected: the default suite passes (every test), and the slow end-to-end render passes with `qc_warnings == []` and total video length within 0.5 s of the summed scene durations. If the end-to-end run reports "ran late", the inline scene's animation (0.3 s) is longer than the estimated beat; check `FakeTTSService` durations before changing anything else.

- [ ] **Step 6: Commit**

```bash
git add animation/section_animator.py main.py tests/test_section_animator.py tests/test_end_to_end.py
git commit -m "Synthesize and time codegen sections beat by beat" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: Script writer prompt rules

**Files:**
- Modify: `backend/services/script_writer_service.py` (prompt text only; `LessonScript` schema unchanged)
- Test: `backend/tests/test_script_writer.py` (create)

**Interfaces:**
- Consumes: `ScriptWriterService(llm).create_lesson_script(lesson_request, lesson_plan) -> LessonScript`.
- Produces: the prompt gains rules 14-16 and the closing rule becomes 17. No per-section word cap (total length is already governed by duration x 130 words).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_script_writer.py`:

```python
from fakes import FakeLLM
from schemas.lesson import LessonPlan, LessonRequest
from services.script_writer_service import ScriptWriterService


def prompt_for_a_lesson():
    llm = FakeLLM([{
        "introduction": "Hello there.",
        "sections": [{"section_title": "How", "narration": "It works."}],
        "conclusion": "Bye.",
    }])
    request = LessonRequest(topic="Binary Search", audience="beginner", goal="understand it",
                            duration_minutes=2, teaching_depth="introductory")
    plan = LessonPlan(title="Binary Search", learning_objectives=["halve"], sections=["How"])

    ScriptWriterService(llm).create_lesson_script(request, plan)

    return " ".join(llm.prompts[0].split())


def test_prompt_asks_for_short_drawable_sentences_with_a_concrete_example():
    prompt = prompt_for_a_lesson()

    assert "under about 22 words" in prompt
    assert "one idea per sentence" in prompt
    assert "can be drawn" in prompt
    assert "ONE concrete example with specific values" in prompt


def test_prompt_keeps_the_total_length_rule_and_the_closing_rule():
    prompt = prompt_for_a_lesson()

    assert "approximately 260 total words" in prompt
    assert "17. Return only the structured result" in prompt
    assert "14. Return only" not in prompt
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_script_writer.py -q`
Expected: the first test fails on `under about 22 words`; the second on `17. Return only`. (If `LessonRequest`/`LessonPlan` construction fails with a validation error, copy the field values used in `tests/test_end_to_end.py`.)

- [ ] **Step 3: Implement**

In `backend/services/script_writer_service.py` replace the last requirement

```
        14. Return only the structured result matching the provided schema.
```

with

```
        14. Write short sentences, under about 22 words each, with one idea
            per sentence. Never restate the previous sentence.
        15. Prefer ideas that can be drawn as shapes, arrows or diagrams
            over abstract statements, so each sentence can be shown on screen.
        16. Whenever a step-by-step procedure is explained, walk through
            ONE concrete example with specific values (for instance a short
            list of real numbers) instead of only describing it in general.
        17. Return only the structured result matching the provided schema.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_script_writer.py -q`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add services/script_writer_service.py tests/test_script_writer.py
git commit -m "Ask the script writer for short, drawable sentences" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: Final verification (full suite and a live run)

**Files:** none modified (scratch scripts go in `backend/scratch_*.py` and are not committed).

- [ ] **Step 1: Full suite including slow renders**

Run: `python -m pytest -q -m "slow or not slow"`
Expected: everything passes (the previous baseline was 100 tests; this branch adds tests, so the count is higher). Fix any failure before continuing.

- [ ] **Step 2: Live generation**

Start the backend as usual and request "Explain binary search to a beginner" through the existing API/UI (about 20 minutes end to end, dominated by LLM latency). Note the run folder `backend/output/<slug>-<id>/`.

- [ ] **Step 3: Check the timing reports**

For every codegen section in that run, read the winning attempt's report. Each attempt writes `<run>/sections/section_NN/codegen_work/attempt_K/beat_report.json`. Run this inline from `backend/` (replace `RUN`):

```bash
python - <<'PY'
import json, pathlib
run = pathlib.Path("output/RUN")
for report in sorted(run.glob("sections/section_*/codegen_work/attempt_*/beat_report.json")):
    rows = json.loads(report.read_text(encoding="utf-8"))
    worst = max(r["overrun"] for r in rows)
    print(report.parent.parent.parent.name, report.parent.name, "beats", len(rows), "worst overrun", worst)
PY
```

Expected: each codegen section has a report whose last attempt shows at most 1.0 s worst overrun and a beat count equal to its `narration_segments` count in the response.

- [ ] **Step 4: Check the frozen tail**

For each codegen section compare `codegen_raw.mp4` length with `clip.mp4` length (`ffprobe -v error -show_entries format=duration -of csv=p=0 <file>`). Expected: the raw clip is within about 1 s of the final clip (the old run `binary-search-36b78bcf` was 7-19 s short). Also open the final video and confirm the visual for a few sentences appears while they are spoken, and that the SRT has one cue per beat.

- [ ] **Step 5: Report**

Write the result in chat: per-section beats, worst overruns, any `ran late` or `storyboard failed` warnings in the response, and whether the criteria in the spec (section 1) hold. Do not claim success on criteria that were not measured. Anything failing goes back to the owning task, not into a quick patch.


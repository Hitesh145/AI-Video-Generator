# Animated Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the slideshow renderer with real animation: algorithm tracers + Manim templates for CS topics, LLM-generated Manim scenes for everything else, and the existing slideshow as a last-resort fallback.

**Architecture:** The lesson script is split into render sections (intro, each section, conclusion). An LLM router picks, per section, either a registered tracer (real Python runs the algorithm and records full-state steps, which a Manim array template animates in time with per-step narration) or codegen (the LLM writes a Manim scene that is AST-checked and rendered in a subprocess, with error-feedback retries). Each section becomes a clip fitted exactly to its narration audio; clips, audio and subtitles are then concatenated and muxed.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Manim Community Edition (subprocess CLI), ffmpeg/ffprobe, edge-tts, Gemini via existing `LLMService.generate_structured`, pytest, React/TypeScript frontend (bun).

**Spec:** `docs/superpowers/specs/2026-09-27-animated-rendering-design.md`

## Global Constraints

- All backend commands run from `backend/` (imports are top-level: `from schemas...`, `from animation...`).
- Video: 854×480, 30 fps, H.264 `yuv420p`. Every section clip is normalised to this by `fit_clip`.
- Manim: Community Edition, rendered only through `python -m manim render` subprocesses. Text via `Text`/`MarkupText` only — no LaTeX anywhere.
- Tracer inputs: 2–12 values, each an int in −99..999.
- Grouped steps: 0.6 s each; narrated step minimum 1.0 s; codegen speed-up cap 15% (`MAX_SPEEDUP = 1.15`).
- Codegen: max 3 attempts, 120 s render timeout per attempt, imports limited to `manim`, `math`, `random`, `numpy`, `kit`.
- Codegen sandbox is accident protection only — do not expose the API publicly.
- Theme colours live only in `backend/animation/codegen/kit.py`; `kit.py` must import nothing outside `manim` (it is copied next to generated scenes).
- Slow tests (real Manim/ffmpeg) are marked `@pytest.mark.slow` and excluded by default; run them with `python -m pytest -m slow`.
- Do not stage the deleted `backend/output/**` files or anything in `backend/rendering/engine/`, `backend/rendering/renderers/` — commit only the paths listed in each task.
- Every commit message ends with the trailer line: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

## Review Focus

1. **Router proposes unsorted values for binary search** → must be rejected by input validation and the section falls back to codegen with a warning, not crash or animate a wrong search. (Task 2 test `test_rejects_unsorted_values`; Task 9 test `test_invalid_inputs_fall_back_to_codegen`.)
2. **Script with an empty introduction or conclusion** → no empty section is rendered or narrated. (Task 1 test `test_skips_blank_intro_and_conclusion`.)
3. **Widest allowed array (12 values incl. 3-digit and negative numbers)** → renders without error and without overflowing cells. (Task 6 slow test `test_renders_widest_array`.)
4. **Router returns duplicate or missing section indices** → every section uses codegen with one warning instead of misaligned routes. (Task 9 test `test_duplicate_indices_fall_back_to_codegen`.)
5. **Generated scene far longer than its narration** → clip is sped up by at most 15% and trimmed so audio and video stay in sync. (Task 5 slow test `test_fit_clip_trims_long_clip`.)

---

## File Map

| File | Responsibility |
|---|---|
| `.gitignore` | stop ignoring `tests/`, ignore generated media |
| `backend/pytest.ini` | pytest config, `slow` marker |
| `backend/requirements.txt` | add `manim`, `pytest` |
| `backend/animation/schemas.py` | RenderSection, Route, RoutePlan, ArrayState, TraceStep, StepNarration, SectionClip, SectionSummary, `build_render_sections` |
| `backend/animation/tracers/base.py` | Tracer protocol, TracerRegistry, input schemas |
| `backend/animation/tracers/{binary_search,linear_search,bubble_sort,insertion_sort}.py` | tracers |
| `backend/animation/tracers/__init__.py` | `default_registry()` |
| `backend/animation/templates/array_diff.py` | pure op planning + cell styling |
| `backend/animation/timing.py` | ffprobe, step durations, clip fitting, audio/clip concat |
| `backend/animation/codegen/kit.py` | theme + helpers for templates and generated scenes |
| `backend/animation/templates/render.py` | Manim subprocess runner, ArrayTemplateRenderer |
| `backend/animation/templates/array_scene.py` | Manim ArrayScene |
| `backend/animation/codegen/validator.py` | AST allowlist |
| `backend/animation/codegen/generator.py` + `examples/*.py` | CodegenRenderer |
| `backend/animation/router.py` | AnimationRouter |
| `backend/animation/narrator.py` | StepNarrator |
| `backend/animation/slideshow.py` | SlideshowRenderer (wraps existing PIL renderer) |
| `backend/animation/section_animator.py` | per-section orchestration and fallbacks |
| `backend/services/tts_service.py` | add `synthesize_text` |
| `backend/rendering/video_renderer.py` | extract `mux_video` |
| `backend/services/demo_video_service.py`, `backend/schemas/demo.py`, `backend/main.py` | integration |
| `frontend/src/App.tsx`, `frontend/src/index.css` | section path badges |
| `backend/tests/*` | tests |

---

### Task 1: Tooling and core schemas

**Files:**
- Modify: `.gitignore`
- Modify: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Create: `backend/animation/__init__.py` (empty)
- Create: `backend/animation/schemas.py`
- Create: `backend/tests/fakes.py`
- Test: `backend/tests/test_schemas.py`

**Interfaces:**
- Produces: `RenderSection(index: int, title: str, narration: str)`; `build_render_sections(script: LessonScript) -> list[RenderSection]`; `Route(section_index, path: Literal["trace","codegen"], tracer: str | None, inputs_json: str)`; `RoutePlan(routes: list[Route])`; `ArrayState(values, pointers, highlighted, dimmed, swapped, sorted_indices, found)`; `TraceStep(state: ArrayState, event: str)`; `StepNarration(sentences: list[str], group_with_previous: list[bool])`; `SectionClip(section_index, title, video_path, audio_path, narration_segments, segment_durations, path_used, tracer, warnings)`; `SectionSummary(title, path_used, tracer, duration_seconds, warnings)`; `tests/fakes.py::FakeLLM(responses)` with `.prompts`.

- [ ] **Step 1: Fix `.gitignore`**

The current `**/test*` rule would ignore the new `backend/tests/` directory. Replace the whole file with:

```gitignore
venv/
__pycache__/
*.pyc
.env
.pytest_cache/
**/*.test.*
**/*.spec.*

# generated media
backend/output/
backend/test_animation/
backend/test_output/
backend/media/
**/tempCodeRunnerFile.py
```

- [ ] **Step 2: Add dependencies and install**

Append to `backend/requirements.txt`:

```
manim
pytest
```

Run: `python -m pip install manim pytest`
Then: `python -c "import manim; print(manim.__version__)"`
Expected: prints a version ≥ 0.18. If install fails on pycairo/manimpango, stop and report — do not work around it.

- [ ] **Step 3: Create `backend/pytest.ini`**

```ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -m "not slow"
markers =
    slow: renders real video with Manim/ffmpeg (run with: python -m pytest -m slow)
```

- [ ] **Step 4: Create `backend/tests/fakes.py`**

```python
from pydantic import BaseModel


class FakeLLM:
    """Returns queued responses in order; records every prompt."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("FakeLLM ran out of responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, BaseModel):
            return response
        return response_schema.model_validate(response)
```

- [ ] **Step 5: Write the failing tests** — `backend/tests/test_schemas.py`

```python
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
```

- [ ] **Step 6: Run to verify failure**

Run (from `backend/`): `python -m pytest tests/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'animation'`.

- [ ] **Step 7: Implement `backend/animation/schemas.py`** (and create empty `backend/animation/__init__.py`)

```python
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from schemas.lesson import LessonScript


PathUsed = Literal["trace", "codegen", "slideshow"]


class RenderSection(BaseModel):
    index: int = Field(ge=0, description="0-based position of the section in the video.")
    title: str
    narration: str


def build_render_sections(script: LessonScript) -> list[RenderSection]:
    parts: list[tuple[str, str]] = []
    if script.introduction.strip():
        parts.append(("Introduction", script.introduction))
    for section in script.sections:
        parts.append((section.section_title, section.narration))
    if script.conclusion.strip():
        parts.append(("Conclusion", script.conclusion))

    return [
        RenderSection(index=index, title=title, narration=narration)
        for index, (title, narration) in enumerate(parts)
    ]


class Route(BaseModel):
    section_index: int = Field(description="Index of the section this route is for.")
    path: Literal["trace", "codegen"] = Field(
        description="'trace' to animate a registered algorithm tracer, 'codegen' otherwise."
    )
    tracer: str | None = Field(
        default=None,
        description="Tracer name when path is 'trace'.",
    )
    inputs_json: str = Field(
        default="{}",
        description="JSON object string with the tracer inputs when path is 'trace'.",
    )


class RoutePlan(BaseModel):
    routes: list[Route] = Field(description="Exactly one route per section.")


class ArrayState(BaseModel):
    values: list[int | str]
    pointers: dict[str, int] = Field(default_factory=dict)
    highlighted: list[int] = Field(default_factory=list)
    dimmed: list[int] = Field(default_factory=list)
    swapped: tuple[int, int] | None = None
    sorted_indices: list[int] = Field(default_factory=list)
    found: int | None = None

    @model_validator(mode="after")
    def _indices_in_range(self) -> "ArrayState":
        count = len(self.values)
        indices = [
            *self.pointers.values(),
            *self.highlighted,
            *self.dimmed,
            *self.sorted_indices,
        ]
        if self.swapped is not None:
            indices.extend(self.swapped)
        if self.found is not None:
            indices.append(self.found)

        bad = [index for index in indices if not 0 <= index < count]
        if bad:
            raise ValueError(f"State indices out of range for {count} values: {bad}")
        return self


class TraceStep(BaseModel):
    state: ArrayState
    event: str = Field(min_length=1, description="Factual description of what happened.")


class StepNarration(BaseModel):
    sentences: list[str] = Field(
        description="One spoken sentence per step that is not grouped with the previous step."
    )
    group_with_previous: list[bool] = Field(
        description="One flag per step; true means the step plays quickly under the previous sentence."
    )


class SectionClip(BaseModel):
    section_index: int
    title: str
    video_path: str
    audio_path: str
    narration_segments: list[str]
    segment_durations: list[float]
    path_used: PathUsed
    tracer: str | None = None
    warnings: list[str] = Field(default_factory=list)


class SectionSummary(BaseModel):
    title: str
    path_used: PathUsed
    tracer: str | None = None
    duration_seconds: float
    warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 8: Run tests**

Run: `python -m pytest tests/test_schemas.py -v`
Expected: 4 passed.

- [ ] **Step 9: Commit**

```bash
git add .gitignore backend/requirements.txt backend/pytest.ini backend/animation/__init__.py backend/animation/schemas.py backend/tests/fakes.py backend/tests/test_schemas.py
git commit -m "Add animation schemas, pytest setup and manim dependency

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Tracer base, registry and binary search

**Files:**
- Create: `backend/animation/tracers/base.py`
- Create: `backend/animation/tracers/binary_search.py`
- Create: `backend/animation/tracers/__init__.py`
- Test: `backend/tests/test_tracer_registry.py`, `backend/tests/test_binary_search_tracer.py`

**Interfaces:**
- Consumes: `ArrayState`, `TraceStep` (Task 1).
- Produces: `Tracer` protocol (`name`, `description`, `input_schema`, `template`, `trace(inputs) -> list[TraceStep]`); `TracerRegistry(tracers=None)` with `register(tracer)`, `get(name) -> Tracer | None`, `names() -> list[str]`, `catalogue() -> list[dict]`; `ArrayInput(values)`, `SearchInput(values, target)`; `BinarySearchTracer`, `BinarySearchInput`; `default_registry() -> TracerRegistry`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_binary_search_tracer.py`:

```python
import random

import pytest
from pydantic import ValidationError

from animation.tracers.binary_search import BinarySearchInput, BinarySearchTracer


def run(values, target):
    return BinarySearchTracer().trace(BinarySearchInput(values=values, target=target))


def test_found_after_one_discard():
    steps = run([2, 5, 8, 12, 16, 23, 38], 23)

    assert len(steps) == 5  # start, compare, discard, compare, found
    assert [s.state.pointers.get("mid") for s in steps if s.state.highlighted] == [3, 5]
    assert steps[2].state.dimmed == [0, 1, 2, 3]
    assert steps[2].state.pointers == {"lo": 4, "hi": 6}
    assert steps[-1].state.found == 5


def test_not_found_ends_with_empty_range():
    steps = run([1, 3, 5], 4)

    assert len(steps) == 6
    assert steps[-1].state.found is None
    assert steps[-1].state.pointers == {}
    assert steps[-1].state.dimmed == [0, 1, 2]
    assert "not in the array" in steps[-1].event


def test_duplicates_are_allowed():
    steps = run([5, 5, 5], 5)

    assert steps[-1].state.found == 1


def test_rejects_unsorted_values():
    with pytest.raises(ValidationError):
        BinarySearchInput(values=[3, 1, 2], target=1)


@pytest.mark.parametrize("values", [[1], list(range(13))])
def test_rejects_bad_lengths(values):
    with pytest.raises(ValidationError):
        BinarySearchInput(values=values, target=1)


def test_rejects_out_of_range_values():
    with pytest.raises(ValidationError):
        BinarySearchInput(values=[1, 1000], target=1)


def test_random_inputs_agree_with_membership():
    rng = random.Random(7)
    for _ in range(200):
        values = sorted(rng.randint(-99, 999) for _ in range(rng.randint(2, 12)))
        target = rng.choice(values + [rng.randint(-99, 999)])
        steps = run(values, target)
        found = steps[-1].state.found
        if target in values:
            assert found is not None and values[found] == target
        else:
            assert found is None
```

`backend/tests/test_tracer_registry.py`:

```python
import pytest

from animation.tracers import default_registry
from animation.tracers.base import TracerRegistry
from animation.tracers.binary_search import BinarySearchTracer


def test_get_unknown_returns_none():
    assert TracerRegistry().get("nope") is None


def test_duplicate_registration_fails():
    registry = TracerRegistry([BinarySearchTracer()])
    with pytest.raises(ValueError):
        registry.register(BinarySearchTracer())


def test_catalogue_describes_inputs():
    catalogue = TracerRegistry([BinarySearchTracer()]).catalogue()

    assert catalogue[0]["name"] == "binary_search"
    assert "target" in catalogue[0]["inputs_schema"]["properties"]


def test_default_registry_contains_binary_search():
    assert "binary_search" in default_registry().names()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_binary_search_tracer.py tests/test_tracer_registry.py -v`
Expected: FAIL — `No module named 'animation.tracers'`.

- [ ] **Step 3: Implement `backend/animation/tracers/base.py`**

```python
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field

from animation.schemas import TraceStep


ArrayValue = Annotated[int, Field(ge=-99, le=999)]


class ArrayInput(BaseModel):
    values: list[ArrayValue] = Field(
        min_length=2,
        max_length=12,
        description="Array values; prefer 5-8 values so the animation stays readable.",
    )


class SearchInput(ArrayInput):
    target: ArrayValue = Field(description="Value to search for.")


class Tracer(Protocol):
    name: str
    description: str
    input_schema: type[BaseModel]
    template: Literal["array"]

    def trace(self, inputs: Any) -> list[TraceStep]:
        ...


class TracerRegistry:
    def __init__(self, tracers: list[Tracer] | None = None) -> None:
        self._tracers: dict[str, Tracer] = {}
        for tracer in tracers or []:
            self.register(tracer)

    def register(self, tracer: Tracer) -> None:
        if tracer.name in self._tracers:
            raise ValueError(f"Tracer already registered: {tracer.name}")
        self._tracers[tracer.name] = tracer

    def get(self, name: str) -> Tracer | None:
        return self._tracers.get(name)

    def names(self) -> list[str]:
        return list(self._tracers)

    def catalogue(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tracer.name,
                "description": tracer.description,
                "inputs_schema": tracer.input_schema.model_json_schema(),
            }
            for tracer in self._tracers.values()
        ]
```

- [ ] **Step 4: Implement `backend/animation/tracers/binary_search.py`**

```python
from pydantic import model_validator

from animation.schemas import ArrayState, TraceStep
from animation.tracers.base import SearchInput


class BinarySearchInput(SearchInput):
    @model_validator(mode="after")
    def _values_sorted(self) -> "BinarySearchInput":
        if any(a > b for a, b in zip(self.values, self.values[1:])):
            raise ValueError("Binary search needs values sorted in ascending order.")
        return self


class BinarySearchTracer:
    name = "binary_search"
    description = (
        "Binary search for a target in a sorted array: compare the middle element "
        "and discard the half that cannot contain the target."
    )
    input_schema = BinarySearchInput
    template = "array"

    def trace(self, inputs: BinarySearchInput) -> list[TraceStep]:
        values = list(inputs.values)
        target = inputs.target
        lo, hi = 0, len(values) - 1
        dimmed: set[int] = set()

        steps = [
            TraceStep(
                state=ArrayState(values=values, pointers={"lo": lo, "hi": hi}),
                event=f"Search for {target}. The whole array is in range: lo = {lo}, hi = {hi}.",
            )
        ]

        while lo <= hi:
            mid = (lo + hi) // 2
            value = values[mid]
            steps.append(
                TraceStep(
                    state=ArrayState(
                        values=values,
                        pointers={"lo": lo, "mid": mid, "hi": hi},
                        highlighted=[mid],
                        dimmed=sorted(dimmed),
                    ),
                    event=f"mid = ({lo} + {hi}) // 2 = {mid}. Compare values[{mid}] = {value} with {target}.",
                )
            )

            if value == target:
                steps.append(
                    TraceStep(
                        state=ArrayState(
                            values=values,
                            pointers={"mid": mid},
                            dimmed=sorted(dimmed),
                            found=mid,
                        ),
                        event=f"values[{mid}] = {target}. Found the target at index {mid}.",
                    )
                )
                return steps

            if value < target:
                dimmed.update(range(lo, mid + 1))
                event = (
                    f"{value} < {target}, so the target can only be to the right. "
                    f"Rule out indices {lo} to {mid}."
                )
                lo = mid + 1
            else:
                dimmed.update(range(mid, hi + 1))
                event = (
                    f"{value} > {target}, so the target can only be to the left. "
                    f"Rule out indices {mid} to {hi}."
                )
                hi = mid - 1

            pointers = {"lo": lo, "hi": hi} if lo <= hi else {}
            steps.append(
                TraceStep(
                    state=ArrayState(values=values, pointers=pointers, dimmed=sorted(dimmed)),
                    event=event,
                )
            )

        steps.append(
            TraceStep(
                state=ArrayState(values=values, dimmed=sorted(dimmed)),
                event=f"The search range is empty, so {target} is not in the array.",
            )
        )
        return steps
```

- [ ] **Step 5: Implement `backend/animation/tracers/__init__.py`**

```python
from animation.tracers.base import TracerRegistry
from animation.tracers.binary_search import BinarySearchTracer


def default_registry() -> TracerRegistry:
    return TracerRegistry([
        BinarySearchTracer(),
    ])
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_binary_search_tracer.py tests/test_tracer_registry.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/animation/tracers backend/tests/test_binary_search_tracer.py backend/tests/test_tracer_registry.py
git commit -m "Add tracer registry and binary search tracer

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Linear search, bubble sort and insertion sort tracers

**Files:**
- Create: `backend/animation/tracers/linear_search.py`, `bubble_sort.py`, `insertion_sort.py`
- Modify: `backend/animation/tracers/__init__.py`
- Test: `backend/tests/test_array_tracers.py`

**Interfaces:**
- Consumes: `ArrayInput`, `SearchInput`, `ArrayState`, `TraceStep`, `TracerRegistry`.
- Produces: `LinearSearchTracer` (name `linear_search`, input `SearchInput`), `BubbleSortTracer` (`bubble_sort`, `ArrayInput`), `InsertionSortTracer` (`insertion_sort`, `ArrayInput`); `default_registry()` returns all four.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_array_tracers.py`

```python
import random

from animation.tracers import default_registry
from animation.tracers.base import ArrayInput, SearchInput
from animation.tracers.bubble_sort import BubbleSortTracer
from animation.tracers.insertion_sort import InsertionSortTracer
from animation.tracers.linear_search import LinearSearchTracer


def test_linear_search_found():
    steps = LinearSearchTracer().trace(SearchInput(values=[4, 7, 1], target=1))

    assert len(steps) == 4  # start, i=0, i=1, found at 2
    assert steps[-1].state.found == 2
    assert steps[-1].state.dimmed == [0, 1]


def test_linear_search_not_found():
    steps = LinearSearchTracer().trace(SearchInput(values=[4, 7], target=9))

    assert steps[-1].state.found is None
    assert steps[-1].state.dimmed == [0, 1]


def test_bubble_sort_small_example():
    steps = BubbleSortTracer().trace(ArrayInput(values=[3, 1, 2]))

    assert len(steps) == 8
    assert sum(1 for s in steps if s.state.swapped) == 2
    assert steps[-1].state.values == [1, 2, 3]
    assert steps[-1].state.sorted_indices == [0, 1, 2]


def test_bubble_sort_swap_step_shows_post_swap_values():
    steps = BubbleSortTracer().trace(ArrayInput(values=[3, 1]))
    swap = next(s for s in steps if s.state.swapped)

    assert swap.state.swapped == (0, 1)
    assert swap.state.values == [1, 3]


def test_insertion_sort_small_example():
    steps = InsertionSortTracer().trace(ArrayInput(values=[3, 1, 2]))

    assert len(steps) == 7
    assert steps[0].state.sorted_indices == [0]
    assert steps[-1].state.values == [1, 2, 3]
    assert steps[-1].state.sorted_indices == [0, 1, 2]


def test_sorts_agree_with_sorted_on_random_input():
    rng = random.Random(11)
    for tracer in (BubbleSortTracer(), InsertionSortTracer()):
        for _ in range(100):
            values = [rng.randint(-99, 999) for _ in range(rng.randint(2, 12))]
            steps = tracer.trace(ArrayInput(values=values))
            assert steps[-1].state.values == sorted(values)
            assert steps[-1].state.sorted_indices == list(range(len(values)))


def test_linear_search_agrees_with_index_on_random_input():
    rng = random.Random(3)
    for _ in range(100):
        values = [rng.randint(0, 9) for _ in range(rng.randint(2, 12))]
        target = rng.randint(0, 9)
        found = LinearSearchTracer().trace(SearchInput(values=values, target=target))[-1].state.found
        assert found == (values.index(target) if target in values else None)


def test_default_registry_has_all_milestone_tracers():
    assert sorted(default_registry().names()) == [
        "binary_search",
        "bubble_sort",
        "insertion_sort",
        "linear_search",
    ]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_array_tracers.py -v`
Expected: FAIL — `No module named 'animation.tracers.bubble_sort'`.

- [ ] **Step 3: Implement `backend/animation/tracers/linear_search.py`**

```python
from animation.schemas import ArrayState, TraceStep
from animation.tracers.base import SearchInput


class LinearSearchTracer:
    name = "linear_search"
    description = (
        "Linear search: check each element from left to right until the target "
        "is found or the array ends."
    )
    input_schema = SearchInput
    template = "array"

    def trace(self, inputs: SearchInput) -> list[TraceStep]:
        values = list(inputs.values)
        target = inputs.target
        steps = [
            TraceStep(
                state=ArrayState(values=values),
                event=f"Search for {target} by checking each value from left to right.",
            )
        ]

        for index, value in enumerate(values):
            if value == target:
                steps.append(
                    TraceStep(
                        state=ArrayState(
                            values=values,
                            pointers={"i": index},
                            dimmed=list(range(index)),
                            found=index,
                        ),
                        event=f"values[{index}] = {target}. Found the target at index {index}.",
                    )
                )
                return steps

            steps.append(
                TraceStep(
                    state=ArrayState(
                        values=values,
                        pointers={"i": index},
                        highlighted=[index],
                        dimmed=list(range(index)),
                    ),
                    event=f"values[{index}] = {value}, which is not {target}. Move on.",
                )
            )

        steps.append(
            TraceStep(
                state=ArrayState(values=values, dimmed=list(range(len(values)))),
                event=f"Every value has been checked, so {target} is not in the array.",
            )
        )
        return steps
```

- [ ] **Step 4: Implement `backend/animation/tracers/bubble_sort.py`**

```python
from animation.schemas import ArrayState, TraceStep
from animation.tracers.base import ArrayInput


class BubbleSortTracer:
    name = "bubble_sort"
    description = (
        "Bubble sort: compare neighbouring values and swap them when out of order, "
        "so the largest remaining value bubbles to the end on each pass."
    )
    input_schema = ArrayInput
    template = "array"

    def trace(self, inputs: ArrayInput) -> list[TraceStep]:
        values = list(inputs.values)
        count = len(values)
        done: set[int] = set()
        steps = [
            TraceStep(
                state=ArrayState(values=list(values)),
                event="Sort the array by comparing neighbouring values and swapping them when they are out of order.",
            )
        ]

        for end in range(count - 1, 0, -1):
            swapped_any = False
            for j in range(end):
                steps.append(
                    TraceStep(
                        state=ArrayState(
                            values=list(values),
                            pointers={"j": j},
                            highlighted=[j, j + 1],
                            sorted_indices=sorted(done),
                        ),
                        event=f"Compare {values[j]} and {values[j + 1]}.",
                    )
                )
                if values[j] > values[j + 1]:
                    values[j], values[j + 1] = values[j + 1], values[j]
                    swapped_any = True
                    steps.append(
                        TraceStep(
                            state=ArrayState(
                                values=list(values),
                                pointers={"j": j},
                                highlighted=[j, j + 1],
                                sorted_indices=sorted(done),
                                swapped=(j, j + 1),
                            ),
                            event=f"{values[j + 1]} is bigger than {values[j]}, so swap them.",
                        )
                    )

            done.add(end)
            if not swapped_any:
                steps.append(
                    TraceStep(
                        state=ArrayState(values=list(values), sorted_indices=list(range(count))),
                        event="No swaps in this pass, so the array is already sorted.",
                    )
                )
                return steps

            steps.append(
                TraceStep(
                    state=ArrayState(values=list(values), sorted_indices=sorted(done)),
                    event=f"{values[end]} has reached its final position at index {end}.",
                )
            )

        steps.append(
            TraceStep(
                state=ArrayState(values=list(values), sorted_indices=list(range(count))),
                event="The array is sorted.",
            )
        )
        return steps
```

- [ ] **Step 5: Implement `backend/animation/tracers/insertion_sort.py`**

```python
from animation.schemas import ArrayState, TraceStep
from animation.tracers.base import ArrayInput


class InsertionSortTracer:
    name = "insertion_sort"
    description = (
        "Insertion sort: grow a sorted part on the left by taking the next value "
        "and moving it left until it is in place."
    )
    input_schema = ArrayInput
    template = "array"

    def trace(self, inputs: ArrayInput) -> list[TraceStep]:
        values = list(inputs.values)
        steps = [
            TraceStep(
                state=ArrayState(values=list(values), sorted_indices=[0]),
                event="The first value on its own is already sorted.",
            )
        ]

        for i in range(1, len(values)):
            key = values[i]
            steps.append(
                TraceStep(
                    state=ArrayState(
                        values=list(values),
                        pointers={"key": i},
                        highlighted=[i],
                        sorted_indices=list(range(i)),
                    ),
                    event=f"Take {key} and insert it into the sorted part on the left.",
                )
            )

            j = i
            while j > 0 and values[j - 1] > values[j]:
                values[j - 1], values[j] = values[j], values[j - 1]
                steps.append(
                    TraceStep(
                        state=ArrayState(
                            values=list(values),
                            pointers={"key": j - 1},
                            highlighted=[j - 1],
                            sorted_indices=list(range(i)),
                            swapped=(j - 1, j),
                        ),
                        event=f"{values[j]} is bigger than {key}, so {key} moves left.",
                    )
                )
                j -= 1

            steps.append(
                TraceStep(
                    state=ArrayState(values=list(values), sorted_indices=list(range(i + 1))),
                    event=f"{key} is in place. The first {i + 1} values are sorted.",
                )
            )

        return steps
```

- [ ] **Step 6: Register all tracers** — replace `backend/animation/tracers/__init__.py`

```python
from animation.tracers.base import TracerRegistry
from animation.tracers.binary_search import BinarySearchTracer
from animation.tracers.bubble_sort import BubbleSortTracer
from animation.tracers.insertion_sort import InsertionSortTracer
from animation.tracers.linear_search import LinearSearchTracer


def default_registry() -> TracerRegistry:
    return TracerRegistry([
        BinarySearchTracer(),
        LinearSearchTracer(),
        BubbleSortTracer(),
        InsertionSortTracer(),
    ])
```

- [ ] **Step 7: Run tests**

Run: `python -m pytest -v`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add backend/animation/tracers backend/tests/test_array_tracers.py
git commit -m "Add linear search, bubble sort and insertion sort tracers

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Array diff (op planning and cell styling)

**Files:**
- Create: `backend/animation/templates/__init__.py` (empty)
- Create: `backend/animation/templates/array_diff.py`
- Test: `backend/tests/test_array_diff.py`

**Interfaces:**
- Consumes: `ArrayState`.
- Produces: frozen dataclasses `SwapCells(i, j)`, `AddPointer(name, index)`, `MovePointer(name, index)`, `RemovePointer(name)`, `MarkFound(index)`; `plan_ops(prev: ArrayState, curr: ArrayState) -> list[Op]` (order: swaps, pointer adds/moves, pointer removals, found); `CellStyle(role: Literal["normal","highlight","sorted","found"], opacity: float)`; `cell_style(state, index) -> CellStyle`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_array_diff.py`

```python
from animation.schemas import ArrayState
from animation.templates.array_diff import (
    AddPointer,
    CellStyle,
    MarkFound,
    MovePointer,
    RemovePointer,
    SwapCells,
    cell_style,
    plan_ops,
)


def test_pointer_add_move_remove():
    prev = ArrayState(values=[1, 2, 3], pointers={"lo": 0, "hi": 2})
    curr = ArrayState(values=[1, 2, 3], pointers={"lo": 1, "mid": 1})

    assert plan_ops(prev, curr) == [
        MovePointer("lo", 1),
        AddPointer("mid", 1),
        RemovePointer("hi"),
    ]


def test_swap_comes_first():
    prev = ArrayState(values=[3, 1], pointers={"j": 0})
    curr = ArrayState(values=[1, 3], pointers={"j": 0}, swapped=(0, 1))

    assert plan_ops(prev, curr) == [SwapCells(0, 1)]


def test_found_only_when_newly_found():
    prev = ArrayState(values=[1, 2], found=None)
    curr = ArrayState(values=[1, 2], found=1)

    assert plan_ops(prev, curr) == [MarkFound(1)]
    assert plan_ops(curr, curr) == []


def test_cell_style_priority_and_dimming():
    state = ArrayState(
        values=[1, 2, 3, 4],
        highlighted=[1],
        sorted_indices=[1, 2],
        dimmed=[3],
        found=0,
    )

    assert cell_style(state, 0) == CellStyle("found", 1.0)
    assert cell_style(state, 1) == CellStyle("highlight", 1.0)
    assert cell_style(state, 2) == CellStyle("sorted", 1.0)
    assert cell_style(state, 3) == CellStyle("normal", 0.3)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_array_diff.py -v`
Expected: FAIL — `No module named 'animation.templates'`.

- [ ] **Step 3: Implement `backend/animation/templates/array_diff.py`**

```python
"""Pure, Manim-free planning of how one ArrayState turns into the next."""

from dataclasses import dataclass
from typing import Literal

from animation.schemas import ArrayState


DIMMED_OPACITY = 0.3


@dataclass(frozen=True)
class SwapCells:
    i: int
    j: int


@dataclass(frozen=True)
class AddPointer:
    name: str
    index: int


@dataclass(frozen=True)
class MovePointer:
    name: str
    index: int


@dataclass(frozen=True)
class RemovePointer:
    name: str


@dataclass(frozen=True)
class MarkFound:
    index: int


Op = SwapCells | AddPointer | MovePointer | RemovePointer | MarkFound


def plan_ops(prev: ArrayState, curr: ArrayState) -> list[Op]:
    ops: list[Op] = []

    if curr.swapped is not None:
        ops.append(SwapCells(*curr.swapped))

    for name, index in curr.pointers.items():
        if name not in prev.pointers:
            ops.append(AddPointer(name, index))
        elif prev.pointers[name] != index:
            ops.append(MovePointer(name, index))

    for name in prev.pointers:
        if name not in curr.pointers:
            ops.append(RemovePointer(name))

    if curr.found is not None and curr.found != prev.found:
        ops.append(MarkFound(curr.found))

    return ops


@dataclass(frozen=True)
class CellStyle:
    role: Literal["normal", "highlight", "sorted", "found"]
    opacity: float


def cell_style(state: ArrayState, index: int) -> CellStyle:
    opacity = DIMMED_OPACITY if index in state.dimmed else 1.0

    if state.found == index:
        return CellStyle("found", opacity)
    if index in state.highlighted:
        return CellStyle("highlight", opacity)
    if index in state.sorted_indices:
        return CellStyle("sorted", opacity)
    return CellStyle("normal", opacity)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_array_diff.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/animation/templates/__init__.py backend/animation/templates/array_diff.py backend/tests/test_array_diff.py
git commit -m "Add array state diffing for the array template

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Timing — durations, clip fitting, audio and clip concat

**Files:**
- Create: `backend/animation/timing.py`
- Create: `backend/tests/media_helpers.py`
- Test: `backend/tests/test_timing.py`

**Interfaces:**
- Produces: constants `WIDTH=854`, `HEIGHT=480`, `FPS=30`, `GROUPED_STEP_SECONDS=0.6`, `MIN_NARRATED_STEP_SECONDS=1.0`, `MAX_SPEEDUP=1.15`; `probe_duration(path: Path) -> float`; `step_durations_for_segment(audio_seconds: float, grouped_count: int) -> list[float]`; `fit_filter(actual: float, target: float) -> str`; `fit_clip(input_path: Path, target_seconds: float, output_path: Path) -> Path`; `concat_audio_padded(paths: list[Path], durations: list[float], output_path: Path) -> Path`; `concat_clips(paths: list[Path], output_path: Path) -> Path`. `tests/media_helpers.py`: `make_test_clip(path, seconds)`, `make_tone(path, seconds)`.

- [ ] **Step 1: Create `backend/tests/media_helpers.py`**

```python
import subprocess
from pathlib import Path


def make_test_clip(path: Path, seconds: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc=size=854x480:rate=30:duration={seconds}",
            "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )
    return path


def make_tone(path: Path, seconds: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            str(path),
        ],
        check=True,
    )
    return path
```

- [ ] **Step 2: Write the failing tests** — `backend/tests/test_timing.py`

```python
import pytest

from animation.timing import (
    concat_audio_padded,
    concat_clips,
    fit_clip,
    fit_filter,
    probe_duration,
    step_durations_for_segment,
)
from media_helpers import make_test_clip, make_tone


def test_single_step_gets_all_audio_time():
    assert step_durations_for_segment(2.5, 0) == [2.5]


def test_grouped_steps_get_fixed_time():
    assert step_durations_for_segment(3.0, 2) == [1.8, 0.6, 0.6]


def test_narrated_step_has_minimum():
    assert step_durations_for_segment(1.0, 3) == [1.0, 0.6, 0.6, 0.6]


def test_fit_filter_pads_short_clip():
    assert fit_filter(2.0, 3.0) == "tpad=stop_mode=clone:stop_duration=1.000"


def test_fit_filter_speeds_up_slightly_long_clip():
    assert fit_filter(2.2, 2.0) == "setpts=PTS*0.909091"


def test_fit_filter_caps_speedup_for_very_long_clip():
    assert fit_filter(10.0, 2.0) == "setpts=PTS/1.15"


def test_fit_filter_rejects_non_positive():
    with pytest.raises(ValueError):
        fit_filter(0, 2.0)


@pytest.mark.slow
@pytest.mark.parametrize("target", [3.0, 1.8])
def test_fit_clip_hits_target(tmp_path, target):
    clip = make_test_clip(tmp_path / "in.mp4", 2.0)
    fitted = fit_clip(clip, target, tmp_path / "out.mp4")

    assert probe_duration(fitted) == pytest.approx(target, abs=0.1)


@pytest.mark.slow
def test_fit_clip_trims_long_clip(tmp_path):
    clip = make_test_clip(tmp_path / "in.mp4", 6.0)
    fitted = fit_clip(clip, 2.0, tmp_path / "out.mp4")

    assert probe_duration(fitted) == pytest.approx(2.0, abs=0.1)


@pytest.mark.slow
def test_concat_audio_padded_uses_given_durations(tmp_path):
    first = make_tone(tmp_path / "a.wav", 1.0)
    second = make_tone(tmp_path / "b.wav", 1.0)
    out = concat_audio_padded([first, second], [1.5, 2.0], tmp_path / "out.m4a")

    assert probe_duration(out) == pytest.approx(3.5, abs=0.1)


@pytest.mark.slow
def test_concat_clips_sums_durations(tmp_path):
    a = fit_clip(make_test_clip(tmp_path / "a.mp4", 1.0), 1.0, tmp_path / "fa.mp4")
    b = fit_clip(make_test_clip(tmp_path / "b.mp4", 2.0), 2.0, tmp_path / "fb.mp4")
    out = concat_clips([a, b], tmp_path / "out.mp4")

    assert probe_duration(out) == pytest.approx(3.0, abs=0.15)
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_timing.py -v -m "slow or not slow"`
Expected: FAIL — `No module named 'animation.timing'`.

- [ ] **Step 4: Implement `backend/animation/timing.py`**

```python
import subprocess
from pathlib import Path


WIDTH = 854
HEIGHT = 480
FPS = 30
GROUPED_STEP_SECONDS = 0.6
MIN_NARRATED_STEP_SECONDS = 1.0
MAX_SPEEDUP = 1.15


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def step_durations_for_segment(audio_seconds: float, grouped_count: int) -> list[float]:
    """First step is narrated; the grouped steps that follow play quickly under it."""
    narrated = max(
        MIN_NARRATED_STEP_SECONDS,
        audio_seconds - GROUPED_STEP_SECONDS * grouped_count,
    )
    return [round(narrated, 3)] + [GROUPED_STEP_SECONDS] * grouped_count


def fit_filter(actual: float, target: float) -> str:
    if actual <= 0 or target <= 0:
        raise ValueError("Durations must be greater than 0.")
    if actual < target:
        return f"tpad=stop_mode=clone:stop_duration={target - actual:.3f}"
    if actual <= target * MAX_SPEEDUP:
        return f"setpts=PTS*{target / actual:.6f}"
    return f"setpts=PTS/{MAX_SPEEDUP}"


def fit_clip(input_path: Path, target_seconds: float, output_path: Path) -> Path:
    """Re-encode a clip to the house format with exactly target_seconds of video."""
    actual = probe_duration(input_path)
    video_filter = (
        f"{fit_filter(actual, target_seconds)},"
        f"scale={WIDTH}:{HEIGHT}:flags=lanczos,fps={FPS},format=yuv420p"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-i", str(input_path),
            "-vf", video_filter,
            "-an",
            "-c:v", "libx264",
            "-t", f"{target_seconds:.3f}",
            str(output_path),
        ],
        check=True,
    )
    return output_path


def concat_audio_padded(paths: list[Path], durations: list[float], output_path: Path) -> Path:
    """Concatenate audio files, padding or trimming each one to its given duration."""
    if not paths:
        raise ValueError("At least one audio file is required.")
    if len(paths) != len(durations):
        raise ValueError("Audio paths and durations must have the same length.")

    command = ["ffmpeg", "-y", "-v", "error"]
    for path in paths:
        command.extend(["-i", str(path)])

    filters = [
        f"[{index}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono,"
        f"apad=whole_dur={duration:.3f},atrim=0:{duration:.3f}[a{index}]"
        for index, duration in enumerate(durations)
    ]
    labels = "".join(f"[a{index}]" for index in range(len(paths)))
    filters.append(f"{labels}concat=n={len(paths)}:v=0:a=1[out]")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path),
    ])
    subprocess.run(command, check=True)
    return output_path


def concat_clips(paths: list[Path], output_path: Path) -> Path:
    """Concatenate clips that were all normalised by fit_clip."""
    if not paths:
        raise ValueError("At least one clip is required.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_path = output_path.with_suffix(".ffconcat")
    lines = ["ffconcat version 1.0"]
    for path in paths:
        escaped = str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-c", "copy",
            str(output_path),
        ],
        check=True,
    )
    return output_path
```

- [ ] **Step 5: Run fast and slow tests**

Run: `python -m pytest tests/test_timing.py -v -m "slow or not slow"`
Expected: all pass (slow ones need ffmpeg on PATH).

- [ ] **Step 6: Commit**

```bash
git add backend/animation/timing.py backend/tests/media_helpers.py backend/tests/test_timing.py
git commit -m "Add timing helpers for step durations, clip fitting and concat

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Style kit, Manim runner and ArrayScene template

**Files:**
- Create: `backend/animation/codegen/__init__.py` (empty)
- Create: `backend/animation/codegen/kit.py`
- Create: `backend/animation/templates/render.py`
- Create: `backend/animation/templates/array_scene.py`
- Test: `backend/tests/test_array_template_render.py`

**Interfaces:**
- Consumes: `TraceStep`, `ArrayState`, `plan_ops`, op classes, `cell_style`; `WIDTH`, `HEIGHT`, `FPS`, `probe_duration` from timing.
- Produces:
  - `kit.py` constants `BACKGROUND, TEXT_COLOR, MUTED, CELL, CELL_STROKE, HIGHLIGHT, SORTED, FOUND, POINTER, ACCENT`, functions `title(text, font_size=34)`, `caption_safe_area() -> tuple[float, float]`, `fit_in_frame(mobject, margin=0.4)`, `bullet_list(items, font_size=28)`.
  - `render.py`: `RenderError(RuntimeError)`; `tail(text, lines=40) -> str`; `render_manim_scene(scene_file: Path, scene_name: str, work_dir: Path, output_path: Path, extra_env: dict[str, str] | None = None, pythonpath: Path | None = None, timeout_seconds: int = 300) -> Path`; `ARRAY_SCENE_DATA_ENV = "ARRAY_SCENE_DATA"`; `ArrayTemplateRenderer().render(title: str, steps: list[TraceStep], durations: list[float], work_dir: Path, output_path: Path) -> Path`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_array_template_render.py`

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_array_template_render.py -v -m "slow or not slow"`
Expected: FAIL — `No module named 'animation.templates.render'`.

- [ ] **Step 3: Implement `backend/animation/codegen/kit.py`**

```python
"""Style kit shared by the array template and LLM-generated scenes.

Keep this file self-contained (manim imports only): it is copied next to
generated scene files, which cannot import the backend package.
"""

from manim import DOWN, LEFT, UP, RIGHT, Mobject, Text, VGroup, config


BACKGROUND = "#0F172A"
TEXT_COLOR = "#F8FAFC"
MUTED = "#94A3B8"
CELL = "#1E293B"
CELL_STROKE = "#64748B"
HIGHLIGHT = "#F59E0B"
SORTED = "#16A34A"
FOUND = "#22C55E"
POINTER = "#38BDF8"
ACCENT = "#818CF8"

CAPTION_SAFE_FRACTION = 0.15

config.background_color = BACKGROUND


def caption_safe_area() -> tuple[float, float]:
    """(ymin, ymax) for content; subtitles cover the bottom 15% of the frame."""
    half = config.frame_height / 2
    return -half + config.frame_height * CAPTION_SAFE_FRACTION, half


def fit_in_frame(mobject: Mobject, margin: float = 0.4) -> Mobject:
    ymin, ymax = caption_safe_area()
    xmax = config.frame_width / 2
    max_width = config.frame_width - 2 * margin
    max_height = (ymax - ymin) - 2 * margin

    if mobject.width > max_width:
        mobject.scale_to_fit_width(max_width)
    if mobject.height > max_height:
        mobject.scale_to_fit_height(max_height)

    if mobject.get_bottom()[1] < ymin + margin:
        mobject.shift(UP * (ymin + margin - mobject.get_bottom()[1]))
    if mobject.get_top()[1] > ymax - margin:
        mobject.shift(DOWN * (mobject.get_top()[1] - (ymax - margin)))
    if mobject.get_left()[0] < -xmax + margin:
        mobject.shift(RIGHT * (-xmax + margin - mobject.get_left()[0]))
    if mobject.get_right()[0] > xmax - margin:
        mobject.shift(LEFT * (mobject.get_right()[0] - (xmax - margin)))
    return mobject


def title(text: str, font_size: int = 34) -> Text:
    heading = Text(text, font_size=font_size, color=TEXT_COLOR)
    if heading.width > config.frame_width * 0.9:
        heading.scale_to_fit_width(config.frame_width * 0.9)
    return heading.to_edge(UP, buff=0.35)


def bullet_list(items: list[str], font_size: int = 28) -> VGroup:
    rows = VGroup(*[Text(f"• {item}", font_size=font_size, color=TEXT_COLOR) for item in items])
    rows.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    return fit_in_frame(rows)
```

- [ ] **Step 4: Implement `backend/animation/templates/render.py`**

```python
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from animation.schemas import TraceStep
from animation.timing import FPS, HEIGHT, WIDTH


BACKEND_DIR = Path(__file__).resolve().parents[2]
ARRAY_SCENE_FILE = Path(__file__).with_name("array_scene.py")
ARRAY_SCENE_DATA_ENV = "ARRAY_SCENE_DATA"


class RenderError(RuntimeError):
    pass


def tail(text: str, lines: int = 40) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def render_manim_scene(
    scene_file: Path,
    scene_name: str,
    work_dir: Path,
    output_path: Path,
    extra_env: dict[str, str] | None = None,
    pythonpath: Path | None = None,
    timeout_seconds: int = 300,
) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    media_dir = work_dir / "media"
    command = [
        sys.executable, "-m", "manim", "render",
        str(scene_file), scene_name,
        "--resolution", f"{WIDTH},{HEIGHT}",
        "--frame_rate", str(FPS),
        "--format", "mp4",
        "--media_dir", str(media_dir),
        "--output_file", "clip",
        "--disable_caching",
        "--progress_bar", "none",
        "--verbosity", "WARNING",
    ]

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    env.update(extra_env or {})

    try:
        result = subprocess.run(
            command,
            cwd=work_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"Render timed out after {timeout_seconds}s.") from exc

    if result.returncode != 0:
        raise RenderError(tail(result.stderr or result.stdout))

    clips = [
        path for path in media_dir.rglob("clip.mp4")
        if "partial_movie_files" not in path.parts
    ]
    if not clips:
        raise RenderError("Render finished but produced no clip.mp4.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(clips[0], output_path)
    return output_path


class ArrayTemplateRenderer:
    def render(
        self,
        title: str,
        steps: list[TraceStep],
        durations: list[float],
        work_dir: Path,
        output_path: Path,
    ) -> Path:
        if not steps or len(steps) != len(durations):
            raise ValueError("Need one duration per step and at least one step.")

        work_dir.mkdir(parents=True, exist_ok=True)
        data_path = work_dir / "array_scene.json"
        data_path.write_text(
            json.dumps({
                "title": title,
                "states": [step.state.model_dump(mode="json") for step in steps],
                "durations": durations,
            }),
            encoding="utf-8",
        )

        return render_manim_scene(
            ARRAY_SCENE_FILE,
            "ArrayScene",
            work_dir,
            output_path,
            extra_env={ARRAY_SCENE_DATA_ENV: str(data_path.resolve())},
            pythonpath=BACKEND_DIR,
            timeout_seconds=600,
        )
```

- [ ] **Step 5: Implement `backend/animation/templates/array_scene.py`**

```python
import json
import os
from pathlib import Path

import numpy as np
from manim import (
    DOWN, RIGHT, UP, Arrow, FadeIn, FadeOut, Indicate, Scene, Square, Swap, Text, VGroup,
)

from animation.codegen.kit import (
    CELL, CELL_STROKE, FOUND, HIGHLIGHT, MUTED, POINTER, SORTED, TEXT_COLOR, title,
)
from animation.schemas import ArrayState
from animation.templates.array_diff import (
    AddPointer, MarkFound, RemovePointer, SwapCells, cell_style, plan_ops,
)
from animation.templates.render import ARRAY_SCENE_DATA_ENV


ROLE_COLORS = {"normal": CELL, "highlight": HIGHLIGHT, "sorted": SORTED, "found": FOUND}
MAX_ANIMATION_SECONDS = 0.8
POINTER_SPREAD = 0.55


class ArrayScene(Scene):
    def construct(self) -> None:
        data = json.loads(Path(os.environ[ARRAY_SCENE_DATA_ENV]).read_text(encoding="utf-8"))
        states = [ArrayState.model_validate(state) for state in data["states"]]
        durations = [float(duration) for duration in data["durations"]]

        self.side = min(1.0, 11.0 / len(states[0].values))
        self.cells = [self._make_cell(value) for value in states[0].values]
        row = VGroup(*self.cells).arrange(RIGHT, buff=0.12).move_to(UP * 0.6)
        self.slots = [cell.get_center().copy() for cell in self.cells]
        index_labels = VGroup(*[
            Text(str(index), font_size=18, color=MUTED).next_to(cell, DOWN, buff=0.12)
            for index, cell in enumerate(self.cells)
        ])
        self.pointer_top = index_labels.get_bottom()[1] - 0.1
        self.pointers: dict[str, VGroup] = {}

        first = states[0]
        for name in first.pointers:
            self.pointers[name] = self._make_pointer(name)
        targets = self._pointer_targets(first)
        for name, pointer in self.pointers.items():
            pointer.move_to(targets[name])

        intro = [FadeIn(title(data["title"])), FadeIn(row), FadeIn(index_labels)]
        intro += [FadeIn(pointer) for pointer in self.pointers.values()]
        self._play_step([intro, self._style_animations(first)], durations[0])

        for prev, curr, duration in zip(states, states[1:], durations[1:]):
            self._play_step(self._step_phases(prev, curr), duration)

    def _make_cell(self, value: int | str) -> VGroup:
        square = Square(
            side_length=self.side,
            color=CELL_STROKE,
            fill_color=CELL,
            fill_opacity=1,
            stroke_width=2,
        )
        label = Text(str(value), font_size=int(36 * self.side), color=TEXT_COLOR)
        if label.width > self.side * 0.85:
            label.scale_to_fit_width(self.side * 0.85)
        return VGroup(square, label)

    def _make_pointer(self, name: str) -> VGroup:
        arrow = Arrow(
            start=DOWN * 0.6,
            end=[0, 0, 0],
            buff=0,
            color=POINTER,
            stroke_width=4,
            max_tip_length_to_length_ratio=0.35,
        )
        label = Text(name, font_size=20, color=POINTER).next_to(arrow, DOWN, buff=0.06)
        return VGroup(arrow, label)

    def _pointer_targets(self, state: ArrayState) -> dict[str, np.ndarray]:
        by_index: dict[int, list[str]] = {}
        for name, index in state.pointers.items():
            by_index.setdefault(index, []).append(name)

        targets: dict[str, np.ndarray] = {}
        for index, names in by_index.items():
            for k, name in enumerate(names):
                pointer = self.pointers[name]
                x = self.slots[index][0] + (k - (len(names) - 1) / 2) * POINTER_SPREAD
                y = self.pointer_top - pointer.height / 2
                targets[name] = np.array([x, y, 0.0])
        return targets

    def _style_animations(self, state: ArrayState) -> list:
        animations = []
        for index, cell in enumerate(self.cells):
            style = cell_style(state, index)
            animations.append(
                cell[0].animate
                .set_fill(ROLE_COLORS[style.role], opacity=style.opacity)
                .set_stroke(opacity=style.opacity)
            )
            animations.append(cell[1].animate.set_opacity(style.opacity))
        return animations

    def _step_phases(self, prev: ArrayState, curr: ArrayState) -> list[list]:
        structure: list = []
        found: list = []
        new_pointers: set[str] = set()

        for op in plan_ops(prev, curr):
            if isinstance(op, SwapCells):
                structure.append(Swap(self.cells[op.i], self.cells[op.j]))
                self.cells[op.i], self.cells[op.j] = self.cells[op.j], self.cells[op.i]
            elif isinstance(op, AddPointer):
                self.pointers[op.name] = self._make_pointer(op.name)
                new_pointers.add(op.name)
            elif isinstance(op, RemovePointer):
                structure.append(FadeOut(self.pointers.pop(op.name)))
            elif isinstance(op, MarkFound):
                found.append(Indicate(self.cells[op.index], color=FOUND, scale_factor=1.15))

        targets = self._pointer_targets(curr)
        for name, pointer in self.pointers.items():
            if name in new_pointers:
                pointer.move_to(targets[name])
                structure.append(FadeIn(pointer))
            elif not np.allclose(pointer.get_center(), targets[name]):
                structure.append(pointer.animate.move_to(targets[name]))

        return [structure, self._style_animations(curr), found]

    def _play_step(self, phases: list[list], duration: float) -> None:
        phases = [phase for phase in phases if phase]
        animation_seconds = min(MAX_ANIMATION_SECONDS, 0.6 * duration) if phases else 0.0
        for phase in phases:
            self.play(*phase, run_time=animation_seconds / len(phases))
        remaining = duration - animation_seconds
        if remaining > 0.01:
            self.wait(remaining)
```

- [ ] **Step 6: Run tests (including slow)**

Run: `python -m pytest tests/test_array_template_render.py -v -m "slow or not slow"`
Expected: 3 passed. If the Manim CLI rejects a flag, run `python -m manim render --help`, correct the flag name in `render_manim_scene`, and re-run.

- [ ] **Step 7: Eyeball one render**

Run: `python -m pytest tests/test_array_template_render.py::test_renders_bubble_sort_with_expected_length -m slow --basetemp=../tmp_render`
Open `../tmp_render/test_renders_bubble_sort_with_e0/out.mp4` and check: cells centred, pointer `j` under the compared cells, swaps move along arcs, sorted cells turn green, nothing below the lower ~15% of the frame. Fix visual problems in `array_scene.py` before continuing. Delete `../tmp_render` afterwards.

- [ ] **Step 8: Commit**

```bash
git add backend/animation/codegen/__init__.py backend/animation/codegen/kit.py backend/animation/templates/render.py backend/animation/templates/array_scene.py backend/tests/test_array_template_render.py
git commit -m "Add Manim array template, style kit and scene runner

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Generated-code AST validator

**Files:**
- Create: `backend/animation/codegen/validator.py`
- Test: `backend/tests/test_codegen_validator.py`

**Interfaces:**
- Produces: `validate_scene_code(code: str) -> list[str]` (empty list = accepted); `ALLOWED_IMPORTS`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_codegen_validator.py`

```python
import pytest

from animation.codegen.validator import validate_scene_code


GOOD = """
from manim import *
from kit import *
import math


class SectionScene(Scene):
    def construct(self):
        dot = Dot()
        self.play(FadeIn(dot), run_time=math.sqrt(1))
        self.wait(1)
"""


def test_accepts_good_scene():
    assert validate_scene_code(GOOD) == []


@pytest.mark.parametrize(
    "snippet",
    [
        "import os",
        "import subprocess",
        "from pathlib import Path",
        "from . import thing",
        "open('x.txt', 'w')",
        "eval('1')",
        "exec('x = 1')",
        "__import__('os')",
        "getattr(Scene, 'x')",
        "x = Scene.__subclasses__()",
        "import numpy.ctypeslib",
    ],
)
def test_rejects_dangerous_code(snippet):
    code = GOOD + "\n" + snippet + "\n"

    assert validate_scene_code(code) != []


def test_reports_syntax_errors():
    errors = validate_scene_code("class SectionScene(Scene)\n    pass")

    assert errors and errors[0].startswith("SyntaxError")


def test_requires_exactly_one_section_scene():
    assert validate_scene_code("from manim import *\nclass Other(Scene):\n    pass\n") != []
    assert validate_scene_code(GOOD + "\nclass Extra(Scene):\n    pass\n") != []
```

`import numpy.ctypeslib` is rejected because `ctypeslib` is in the forbidden attribute names (the `numpy` root alone is allowed).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_codegen_validator.py -v`
Expected: FAIL — `No module named 'animation.codegen.validator'`.

- [ ] **Step 3: Implement `backend/animation/codegen/validator.py`**

```python
"""Static checks on LLM-generated Manim code. Accident protection, not a sandbox."""

import ast


ALLOWED_IMPORTS = frozenset({"manim", "math", "random", "numpy", "kit"})
FORBIDDEN_NAMES = frozenset({
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "input", "breakpoint", "exit", "quit",
})
FORBIDDEN_ATTRIBUTES = FORBIDDEN_NAMES | frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib", "socket", "importlib", "ctypes", "ctypeslib",
})
SCENE_CLASS = "SectionScene"


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def validate_scene_code(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"SyntaxError on line {exc.lineno}: {exc.msg}"]

    errors: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    errors.append(f"Line {line}: import of '{alias.name}' is not allowed.")
                if any(part in FORBIDDEN_ATTRIBUTES for part in alias.name.split(".")[1:]):
                    errors.append(f"Line {line}: import of '{alias.name}' is not allowed.")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or module.split(".")[0] not in ALLOWED_IMPORTS:
                errors.append(f"Line {line}: import from '{'.' * node.level}{module}' is not allowed.")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or _is_dunder(node.id):
                errors.append(f"Line {line}: use of '{node.id}' is not allowed.")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRIBUTES or _is_dunder(node.attr):
                errors.append(f"Line {line}: attribute '{node.attr}' is not allowed.")

    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    if classes != [SCENE_CLASS]:
        errors.append(
            f"Code must define exactly one top-level class named {SCENE_CLASS}; found {classes or 'none'}."
        )

    return errors
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_codegen_validator.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/animation/codegen/validator.py backend/tests/test_codegen_validator.py
git commit -m "Add AST allowlist validator for generated scenes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Codegen renderer with retry loop and examples

**Files:**
- Create: `backend/animation/codegen/examples/title_card.py`
- Create: `backend/animation/codegen/examples/process_flow.py`
- Create: `backend/animation/codegen/generator.py`
- Test: `backend/tests/test_codegen_generator.py`

**Interfaces:**
- Consumes: `RenderSection`; `validate_scene_code`; `render_manim_scene`, `RenderError`, `tail` (Task 6); `FakeLLM`.
- Produces: `GeneratedScene(code: str)`; `CodegenFailed(errors: list[str])`; `CodegenRenderer(llm, scene_renderer=default_scene_renderer, max_attempts=3)` with `render(section: RenderSection, target_seconds: float, work_dir: Path, output_path: Path, artifacts_dir: Path) -> Path`; `SceneRenderer` callable type `(scene_file, scene_name, work_dir, output_path) -> Path`; `EXAMPLES_DIR`.

- [ ] **Step 1: Create the example scenes**

`backend/animation/codegen/examples/title_card.py`:

```python
from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
        heading = title("What makes an algorithm?")
        points = bullet_list(["Clear input", "Finite steps", "Correct output"])
        points.next_to(heading, DOWN, buff=0.6)
        fit_in_frame(points)

        self.play(Write(heading), run_time=1.0)
        for line in points:
            self.play(FadeIn(line, shift=RIGHT * 0.3), run_time=0.6)
        self.wait(2.0)
```

`backend/animation/codegen/examples/process_flow.py`:

```python
from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
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

        self.play(FadeIn(heading), run_time=0.8)
        self.play(FadeIn(boxes[0], shift=UP * 0.3), run_time=0.7)
        for i, arrow in enumerate(arrows):
            self.play(GrowArrow(arrow), FadeIn(boxes[i + 1], shift=UP * 0.3), run_time=0.8)
        self.play(boxes[1][0].animate.set_fill(HIGHLIGHT, opacity=1), run_time=0.6)
        self.wait(2.0)
```

- [ ] **Step 2: Write the failing tests** — `backend/tests/test_codegen_generator.py`

```python
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
```

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_codegen_generator.py -v`
Expected: FAIL — `No module named 'animation.codegen.generator'`.

- [ ] **Step 4: Implement `backend/animation/codegen/generator.py`**

```python
import shutil
from pathlib import Path
from typing import Callable, Protocol

from pydantic import BaseModel, Field

from animation.codegen.validator import validate_scene_code
from animation.schemas import RenderSection
from animation.templates.render import RenderError, render_manim_scene


KIT_FILE = Path(__file__).with_name("kit.py")
EXAMPLES_DIR = Path(__file__).with_name("examples")
MAX_ATTEMPTS = 3
RENDER_TIMEOUT_SECONDS = 120

SceneRenderer = Callable[[Path, str, Path, Path], Path]


class StructuredGenerator(Protocol):
    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        ...


class GeneratedScene(BaseModel):
    code: str = Field(description="Complete Python source of the Manim scene file.")


class CodegenFailed(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Generated animation failed: " + " | ".join(errors))


def default_scene_renderer(scene_file: Path, scene_name: str, work_dir: Path, output_path: Path) -> Path:
    return render_manim_scene(
        scene_file,
        scene_name,
        work_dir,
        output_path,
        pythonpath=work_dir,
        timeout_seconds=RENDER_TIMEOUT_SECONDS,
    )


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
        target_seconds: float,
        work_dir: Path,
        output_path: Path,
        artifacts_dir: Path,
    ) -> Path:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        previous_code: str | None = None
        previous_error: str | None = None

        for attempt in range(1, self.max_attempts + 1):
            stem = artifacts_dir / f"section_{section.index}_attempt_{attempt}"
            prompt = self._build_prompt(section, target_seconds, previous_code, previous_error)

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
                try:
                    return self.scene_renderer(scene_file, "SectionScene", attempt_dir, output_path)
                except RenderError as exc:
                    error = f"Render failed:\n{exc}"

            stem.with_suffix(".log").write_text(error, encoding="utf-8")
            errors.append(f"attempt {attempt}: {error.splitlines()[0]}")
            previous_code = code
            previous_error = error

        raise CodegenFailed(errors)

    def _build_prompt(
        self,
        section: RenderSection,
        target_seconds: float,
        previous_code: str | None,
        previous_error: str | None,
    ) -> str:
        examples = "\n\n".join(
            f"--- {path.name} ---\n{path.read_text(encoding='utf-8')}"
            for path in sorted(EXAMPLES_DIR.glob("*.py"))
        )
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

Section title: {section.title}

Narration spoken while the animation plays:
{section.narration}

Target duration: {target_seconds:.1f} seconds. Use run_time and self.wait(...) so the
total runtime is close to this.

Start the file with:
from manim import *
from kit import *

Style kit available from `kit`:
- Colours: BACKGROUND, TEXT_COLOR, MUTED, CELL, CELL_STROKE, HIGHLIGHT, SORTED, FOUND, POINTER, ACCENT
- title(text) -> Text placed at the top edge
- fit_in_frame(mobject) -> scales/shifts the mobject so it stays on screen and above the subtitle area
- bullet_list(items) -> VGroup of bullet lines, already fitted
- caption_safe_area() -> (ymin, ymax); keep everything between these y values, subtitles cover the bottom 15%

Rules:
1. Define exactly one class, `class SectionScene(Scene):`, with a `construct(self)` method. No other classes.
2. Only import from manim, kit, math, random and numpy.
3. Use Text or MarkupText for all text. Never use Tex, MathTex or anything that needs LaTeX.
4. No file, network or OS access. No dunder names, getattr/setattr, eval/exec or open.
5. Keep everything on screen: call fit_in_frame on large groups.
6. Visualise the idea with shapes, arrows, diagrams and motion. Keep on-screen text short;
   do not put the narration on screen.
7. Return the complete file in the `code` field.

Examples of good scenes:

{examples}
{retry}
"""
```

- [ ] **Step 5: Run tests (including slow)**

Run: `python -m pytest tests/test_codegen_generator.py -v -m "slow or not slow"`
Expected: all pass. The slow tests prove that `kit.py` imports cleanly from a temp directory with `PYTHONPATH` set to that directory only.

- [ ] **Step 6: Commit**

```bash
git add backend/animation/codegen/generator.py backend/animation/codegen/examples backend/tests/test_codegen_generator.py
git commit -m "Add codegen renderer with validation and error-feedback retries

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Animation router

**Files:**
- Create: `backend/animation/router.py`
- Test: `backend/tests/test_router.py`

**Interfaces:**
- Consumes: `RenderSection`, `Route`, `RoutePlan`, `TracerRegistry`, `default_registry`, `FakeLLM`.
- Produces: `ResolvedRoute(section_index: int, path: Literal["trace","codegen"], tracer: str | None = None, inputs: BaseModel | None = None)` (dataclass); `RoutingResult(routes: list[ResolvedRoute], warnings: list[str])` (dataclass); `AnimationRouter(llm, registry).route(sections: list[RenderSection]) -> RoutingResult`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_router.py`

```python
from animation.router import AnimationRouter
from animation.schemas import RenderSection
from animation.tracers import default_registry
from fakes import FakeLLM


SECTIONS = [
    RenderSection(index=0, title="Introduction", narration="Why search?"),
    RenderSection(index=1, title="Binary search step by step", narration="Look at the middle..."),
]


def route(llm):
    return AnimationRouter(llm, default_registry()).route(SECTIONS)


def plan(*routes):
    return {"routes": list(routes)}


def test_resolves_trace_and_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "binary_search",
         "inputs_json": '{"values": [1, 3, 5, 7], "target": 5}'},
    )]))

    assert [r.path for r in result.routes] == ["codegen", "trace"]
    assert result.routes[1].tracer == "binary_search"
    assert result.routes[1].inputs.target == 5
    assert result.warnings == []


def test_prompt_lists_tracers_and_sections():
    llm = FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "codegen"},
    )])
    route(llm)

    assert "bubble_sort" in llm.prompts[0]
    assert "Binary search step by step" in llm.prompts[0]


def test_unknown_tracer_falls_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "quick_sort", "inputs_json": "{}"},
    )]))

    assert result.routes[1].path == "codegen"
    assert "quick_sort" in result.warnings[0]


def test_invalid_inputs_fall_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "binary_search",
         "inputs_json": '{"values": [5, 1, 3], "target": 1}'},
    )]))

    assert result.routes[1].path == "codegen"
    assert "invalid inputs" in result.warnings[0]


def test_malformed_json_falls_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "binary_search", "inputs_json": "{values:"},
    )]))

    assert result.routes[1].path == "codegen"


def test_duplicate_indices_fall_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 0, "path": "codegen"},
    )]))

    assert [r.path for r in result.routes] == ["codegen", "codegen"]
    assert [r.section_index for r in result.routes] == [0, 1]
    assert len(result.warnings) == 1


def test_llm_failure_falls_back_to_codegen():
    result = route(FakeLLM([RuntimeError("timeout")]))

    assert [r.path for r in result.routes] == ["codegen", "codegen"]
    assert "timeout" in result.warnings[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_router.py -v`
Expected: FAIL — `No module named 'animation.router'`.

- [ ] **Step 3: Implement `backend/animation/router.py`**

```python
import json
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

from animation.schemas import RenderSection, Route, RoutePlan
from animation.tracers.base import TracerRegistry


class StructuredGenerator(Protocol):
    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        ...


@dataclass
class ResolvedRoute:
    section_index: int
    path: Literal["trace", "codegen"]
    tracer: str | None = None
    inputs: BaseModel | None = None


@dataclass
class RoutingResult:
    routes: list[ResolvedRoute]
    warnings: list[str]


class AnimationRouter:
    def __init__(self, llm: StructuredGenerator, registry: TracerRegistry) -> None:
        self.llm = llm
        self.registry = registry

    def route(self, sections: list[RenderSection]) -> RoutingResult:
        if not sections:
            return RoutingResult([], [])

        try:
            result = self.llm.generate_structured(self._build_prompt(sections), RoutePlan)
            plan = RoutePlan.model_validate(result.model_dump())
        except Exception as exc:
            return self._all_codegen(sections, f"Animation router failed ({exc}); all sections use generated animation.")

        indices = [route.section_index for route in plan.routes]
        if sorted(indices) != [section.index for section in sections]:
            return self._all_codegen(
                sections,
                f"Animation router returned routes for sections {indices} but expected "
                f"{[section.index for section in sections]}; all sections use generated animation.",
            )

        by_index = {route.section_index: route for route in plan.routes}
        warnings: list[str] = []
        routes = [self._resolve(section, by_index[section.index], warnings) for section in sections]
        return RoutingResult(routes, warnings)

    def _resolve(self, section: RenderSection, route: Route, warnings: list[str]) -> ResolvedRoute:
        codegen = ResolvedRoute(section.index, "codegen")
        if route.path == "codegen":
            return codegen

        tracer = self.registry.get(route.tracer or "")
        if tracer is None:
            warnings.append(
                f"Section '{section.title}': unknown tracer '{route.tracer}', using generated animation."
            )
            return codegen

        try:
            inputs = tracer.input_schema.model_validate_json(route.inputs_json)
        except ValidationError as exc:
            warnings.append(
                f"Section '{section.title}': invalid inputs for {tracer.name} "
                f"({exc.error_count()} errors), using generated animation."
            )
            return codegen

        return ResolvedRoute(section.index, "trace", tracer.name, inputs)

    def _all_codegen(self, sections: list[RenderSection], warning: str) -> RoutingResult:
        return RoutingResult([ResolvedRoute(section.index, "codegen") for section in sections], [warning])

    def _build_prompt(self, sections: list[RenderSection]) -> str:
        section_text = "\n\n".join(
            f"[section_index {section.index}] {section.title}\n{section.narration}"
            for section in sections
        )
        catalogue = json.dumps(self.registry.catalogue(), indent=2)

        return f"""
Decide how to animate each section of an educational video.

Two paths are available:
- "trace": animate a registered algorithm tracer. Real code runs the algorithm on the
  inputs you choose and every step is animated. Use this only when the section walks
  through one of these algorithms on concrete data.
- "codegen": a custom animation is written for the section. Use this for everything
  else, including introductions, conclusions, definitions and comparisons.

Registered tracers (name, description, JSON schema of inputs):
{catalogue}

Sections:
{section_text}

Rules:
1. Return exactly one route per section, using its section_index.
2. For "trace", set "tracer" to a registered name and "inputs_json" to a JSON object
   string that matches that tracer's input schema.
3. If the narration uses a concrete example (specific numbers or a target), use exactly
   those values. Otherwise choose a small illustrative example: 5-8 values for searches,
   5-7 values for sorts.
4. binary_search values must be sorted ascending.
5. For "codegen", leave tracer empty and inputs_json as "{{}}".
"""
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_router.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/animation/router.py backend/tests/test_router.py
git commit -m "Add animation router that picks tracer or codegen per section

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Step narrator

**Files:**
- Create: `backend/animation/narrator.py`
- Test: `backend/tests/test_narrator.py`

**Interfaces:**
- Consumes: `RenderSection`, `TraceStep`, `StepNarration`, `FakeLLM`.
- Produces: `NarratedSegment(text: str, step_indices: tuple[int, ...])` (frozen dataclass); `segments_from_narration(step_count: int, narration: StepNarration) -> list[NarratedSegment]` (raises `ValueError`); `StepNarrator(llm, max_attempts=2).narrate(section, steps) -> tuple[list[NarratedSegment], list[str]]`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_narrator.py`

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_narrator.py -v`
Expected: FAIL — `No module named 'animation.narrator'`.

- [ ] **Step 3: Implement `backend/animation/narrator.py`**

```python
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from animation.schemas import RenderSection, StepNarration, TraceStep


class StructuredGenerator(Protocol):
    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        ...


@dataclass(frozen=True)
class NarratedSegment:
    text: str
    step_indices: tuple[int, ...]


def segments_from_narration(step_count: int, narration: StepNarration) -> list[NarratedSegment]:
    groups = narration.group_with_previous
    if len(groups) != step_count:
        raise ValueError(f"Expected {step_count} group flags, got {len(groups)}.")
    if groups and groups[0]:
        raise ValueError("The first step cannot be grouped with a previous step.")
    narrated = groups.count(False)
    if len(narration.sentences) != narrated:
        raise ValueError(f"Expected {narrated} sentences, got {len(narration.sentences)}.")
    if any(not sentence.strip() for sentence in narration.sentences):
        raise ValueError("Sentences must not be blank.")

    segments: list[tuple[str, list[int]]] = []
    sentences = iter(narration.sentences)
    for index, grouped in enumerate(groups):
        if grouped:
            segments[-1][1].append(index)
        else:
            segments.append((next(sentences).strip(), [index]))

    return [NarratedSegment(text, tuple(indices)) for text, indices in segments]


class StepNarrator:
    def __init__(self, llm: StructuredGenerator, max_attempts: int = 2) -> None:
        self.llm = llm
        self.max_attempts = max_attempts

    def narrate(
        self,
        section: RenderSection,
        steps: list[TraceStep],
    ) -> tuple[list[NarratedSegment], list[str]]:
        prompt = self._build_prompt(section, steps)
        last_error: Exception | None = None

        for _ in range(self.max_attempts):
            try:
                result = self.llm.generate_structured(prompt, StepNarration)
                narration = StepNarration.model_validate(result.model_dump())
                return segments_from_narration(len(steps), narration), []
            except Exception as exc:
                last_error = exc

        fallback = [NarratedSegment(step.event, (index,)) for index, step in enumerate(steps)]
        warning = (
            f"Section '{section.title}': step narration failed ({last_error}); "
            "using plain step descriptions."
        )
        return fallback, [warning]

    def _build_prompt(self, section: RenderSection, steps: list[TraceStep]) -> str:
        events = "\n".join(f"{index}. {step.event}" for index, step in enumerate(steps))
        return f"""
Write the spoken narration for an animated algorithm walkthrough.

Section title: {section.title}
The lesson script for this section says:
{section.narration}

The animation shows these steps, in order ({len(steps)} steps):
{events}

Return:
- group_with_previous: exactly {len(steps)} booleans, one per step. Use true for small
  repetitive steps that can play quickly under the previous sentence (for example the
  many compare/swap steps of a long sort). Step 0 must be false.
- sentences: one short spoken sentence for every step whose flag is false, in order.

Rules:
1. Each sentence must describe only what its step (and any grouped steps after it)
   actually shows. Never mention values or outcomes that are not in the steps.
2. Keep the tone and level of the lesson script. One sentence each, under 25 words.
3. Plain spoken English: no markdown, no code, no lists.
"""
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_narrator.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/animation/narrator.py backend/tests/test_narrator.py
git commit -m "Add step narrator with grouping and event fallback

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Text TTS and slideshow fallback renderer

**Files:**
- Modify: `backend/services/tts_service.py` (`TTSSynthesizer`, `FakeTTSService`, `EdgeTTSService`)
- Create: `backend/animation/slideshow.py`
- Test: `backend/tests/test_tts_text.py`, `backend/tests/test_slideshow.py`

**Interfaces:**
- Consumes: `SceneAudio`, `normalize_text`, `estimate_speech_duration_seconds`; `GenericFrameRenderer.render_scene(scene, output_path) -> Path`; `render_video_from_frames(frame_paths, output_path, durations, ...)`; `RenderSection`.
- Produces: `synthesize_text(self, text: str, output_path: Path) -> SceneAudio` on `FakeTTSService`, `SilentTTSService`, `EdgeTTSService` (`scene_id` = `output_path.stem`); `SlideshowRenderer(frame_renderer=None).render(section, duration_seconds, work_dir, output_path) -> Path`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tts_text.py`:

```python
from services.tts_service import FakeTTSService


def test_fake_tts_synthesizes_plain_text(tmp_path):
    audio = FakeTTSService().synthesize_text("**Binary** search halves the range.", tmp_path / "seg_001.wav")

    assert audio.scene_id == "seg_001"
    assert audio.narration_text == "Binary search halves the range."
    assert audio.duration_seconds >= 2.0
    assert (tmp_path / "seg_001.wav").exists()


def test_fake_tts_handles_empty_text(tmp_path):
    audio = FakeTTSService().synthesize_text("   ", tmp_path / "empty.wav")

    assert audio.duration_seconds >= 2.0
```

`backend/tests/test_slideshow.py`:

```python
import pytest

from animation.schemas import RenderSection
from animation.slideshow import SlideshowRenderer
from animation.timing import probe_duration


@pytest.mark.slow
def test_slideshow_renders_clip_of_requested_length(tmp_path):
    section = RenderSection(index=0, title="Introduction", narration="Searching is everywhere.")

    out = SlideshowRenderer().render(section, 2.5, tmp_path / "work", tmp_path / "out.mp4")

    assert probe_duration(out) == pytest.approx(2.5, abs=0.2)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_tts_text.py tests/test_slideshow.py -v -m "slow or not slow"`
Expected: FAIL — `AttributeError: 'FakeTTSService' object has no attribute 'synthesize_text'` and `No module named 'animation.slideshow'`.

- [ ] **Step 3: Add `synthesize_text` to the TTS services** (`backend/services/tts_service.py`)

In `TTSSynthesizer`, add below the existing method:

```python
    def synthesize_text(self, text: str, output_path: Path) -> SceneAudio:
        ...
```

Replace `FakeTTSService.synthesize_scene_audio` with:

```python
    def synthesize_scene_audio(
        self,
        scene: VisualScene,
        narration_text: str,
        output_path: Path,
    ) -> SceneAudio:
        normalized = normalize_text(narration_text, fallback=scene.description)
        audio = self.synthesize_text(normalized, output_path)
        return audio.model_copy(update={"scene_id": scene.id})

    def synthesize_text(self, text: str, output_path: Path) -> SceneAudio:
        normalized = normalize_text(text)
        duration = estimate_speech_duration_seconds(normalized)
        _write_silent_wav(output_path, duration)

        return SceneAudio(
            scene_id=output_path.stem,
            narration_text=normalized,
            audio_path=str(output_path),
            duration_seconds=_measure_wav_duration_seconds(output_path),
        )
```

Replace `EdgeTTSService.synthesize_scene_audio` with:

```python
    def synthesize_scene_audio(
        self,
        scene: VisualScene,
        narration_text: str,
        output_path: Path,
    ) -> SceneAudio:
        normalized = normalize_text(narration_text, fallback=scene.description)
        audio = self.synthesize_text(normalized, output_path)
        return audio.model_copy(update={"scene_id": scene.id})

    def synthesize_text(self, text: str, output_path: Path) -> SceneAudio:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is not installed. Install it with: pip install edge-tts"
            ) from exc

        normalized = normalize_text(text)
        if not normalized:
            return FakeTTSService().synthesize_text(text, output_path)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        async def _run() -> None:
            communicate = edge_tts.Communicate(normalized, self.voice)
            await communicate.save(str(output_path))

        asyncio.run(_run())

        try:
            duration = _measure_audio_duration_seconds(output_path)
        except Exception:
            duration = estimate_speech_duration_seconds(normalized)

        return SceneAudio(
            scene_id=output_path.stem,
            narration_text=normalized,
            audio_path=str(output_path),
            duration_seconds=duration,
        )
```

- [ ] **Step 4: Implement `backend/animation/slideshow.py`**

```python
from pathlib import Path

from animation.schemas import RenderSection
from rendering.generic_frame_renderer import GenericFrameRenderer
from rendering.video_renderer import render_video_from_frames
from schemas.visual import VisualAction, VisualElement, VisualScene


class SlideshowRenderer:
    """Last-resort renderer: one static slide for the whole section."""

    def __init__(self, frame_renderer: GenericFrameRenderer | None = None) -> None:
        self.frame_renderer = frame_renderer or GenericFrameRenderer()

    def render(
        self,
        section: RenderSection,
        duration_seconds: float,
        work_dir: Path,
        output_path: Path,
    ) -> Path:
        work_dir.mkdir(parents=True, exist_ok=True)
        scene = VisualScene(
            id=f"section_{section.index}",
            section_title=section.title,
            narration_reference=f"section_{section.index}",
            purpose=section.title,
            visual_type="text",
            description=section.narration,
            elements=[
                VisualElement(
                    id="topic",
                    type="concept",
                    description=section.title,
                    label=section.title,
                )
            ],
            actions=[
                VisualAction(
                    order=1,
                    type="show",
                    target=["topic"],
                    description=f"Show {section.title}",
                )
            ],
            duration_seconds=duration_seconds,
        )
        frame = self.frame_renderer.render_scene(scene, work_dir / "slide.png")
        return render_video_from_frames(
            frame_paths=[frame],
            output_path=output_path,
            durations=[duration_seconds],
        )
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_tts_text.py tests/test_slideshow.py -v -m "slow or not slow"`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/tts_service.py backend/animation/slideshow.py backend/tests/test_tts_text.py backend/tests/test_slideshow.py
git commit -m "Add plain-text TTS synthesis and slideshow section fallback

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Section animator (orchestration and fallbacks)

**Files:**
- Create: `backend/animation/section_animator.py`
- Test: `backend/tests/test_section_animator.py`

**Interfaces:**
- Consumes: `AnimationRouter.route -> RoutingResult`, `ResolvedRoute`; `StepNarrator.narrate -> (list[NarratedSegment], list[str])`; `TracerRegistry.get`; `synthesize_text`; `ArrayTemplateRenderer.render(title, steps, durations, work_dir, output_path)`; `CodegenRenderer.render(section, target_seconds, work_dir, output_path, artifacts_dir)`; `SlideshowRenderer.render(section, duration_seconds, work_dir, output_path)`; `step_durations_for_segment`, `fit_clip`, `concat_audio_padded`.
- Produces: `SectionRenderError(RuntimeError)`; `SectionAnimator(router, narrator, registry, synthesizer, template_renderer, codegen_renderer, slideshow_renderer, fit_clip=fit_clip, build_audio=concat_audio_padded)` with `animate(sections: list[RenderSection], output_dir: Path) -> tuple[list[SectionClip], list[str]]`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_section_animator.py`

```python
from pathlib import Path

import pytest

from animation.narrator import NarratedSegment
from animation.router import ResolvedRoute, RoutingResult
from animation.schemas import RenderSection
from animation.section_animator import SectionAnimator, SectionRenderError
from animation.tracers import default_registry
from animation.tracers.binary_search import BinarySearchInput
from services.tts_service import SceneAudio


TRACE_SECTION = RenderSection(index=0, title="Binary search", narration="Watch it halve.")
TEXT_SECTION = RenderSection(index=1, title="Why", narration="It is fast.")


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


def fake_fit(raw, seconds, out):
    return out


def fake_audio(paths, durations, out):
    return out


def make(routes, template=None, codegen=None, slideshow=None):
    template = template or FakeRenderer()
    codegen = codegen or FakeRenderer()
    slideshow = slideshow or FakeRenderer()
    animator = SectionAnimator(
        router=FakeRouter(routes),
        narrator=FakeNarrator(),
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


def test_codegen_route_uses_section_audio_duration(tmp_path):
    animator, _, codegen, _ = make([ResolvedRoute(1, "codegen")])

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "codegen"
    assert codegen.calls[0][1] == 3.0
    assert clips[0].segment_durations == [3.0]


def test_template_failure_falls_back_to_codegen(tmp_path):
    animator, _, codegen, _ = make([TRACE_ROUTE], template=FakeRenderer(fail=True))

    clips, warnings = animator.animate([TRACE_SECTION], tmp_path)

    assert clips[0].path_used == "codegen"
    assert len(codegen.calls) == 1
    assert "trace animation failed" in clips[0].warnings[0]
    assert warnings == clips[0].warnings


def test_codegen_failure_falls_back_to_slideshow(tmp_path):
    animator, _, _, slideshow = make([ResolvedRoute(1, "codegen")], codegen=FakeRenderer(fail=True))

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "slideshow"
    assert slideshow.calls[0][1] == 3.0


def test_everything_failing_raises(tmp_path):
    animator, _, _, _ = make(
        [ResolvedRoute(1, "codegen")],
        codegen=FakeRenderer(fail=True),
        slideshow=FakeRenderer(fail=True),
    )

    with pytest.raises(SectionRenderError, match="Why"):
        animator.animate([TEXT_SECTION], tmp_path)


def test_router_warnings_are_returned(tmp_path):
    animator, _, _, _ = make([ResolvedRoute(1, "codegen")])
    animator.router = FakeRouter([ResolvedRoute(1, "codegen")], ["router said no"])

    _, warnings = animator.animate([TEXT_SECTION], tmp_path)

    assert warnings == ["router said no"]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_section_animator.py -v`
Expected: FAIL — `No module named 'animation.section_animator'`.

- [ ] **Step 3: Implement `backend/animation/section_animator.py`**

```python
from pathlib import Path
from typing import Callable, Protocol

from animation.narrator import NarratedSegment
from animation.router import ResolvedRoute, RoutingResult
from animation.schemas import PathUsed, RenderSection, SectionClip, TraceStep
from animation.timing import concat_audio_padded, fit_clip, step_durations_for_segment
from animation.tracers.base import TracerRegistry
from services.tts_service import SceneAudio


ClipFitter = Callable[[Path, float, Path], Path]
AudioBuilder = Callable[[list[Path], list[float], Path], Path]


class Router(Protocol):
    def route(self, sections: list[RenderSection]) -> RoutingResult:
        ...


class Narrator(Protocol):
    def narrate(self, section: RenderSection, steps: list[TraceStep]) -> tuple[list[NarratedSegment], list[str]]:
        ...


class TextSynthesizer(Protocol):
    def synthesize_text(self, text: str, output_path: Path) -> SceneAudio:
        ...


class TemplateRenderer(Protocol):
    def render(self, title: str, steps: list[TraceStep], durations: list[float], work_dir: Path, output_path: Path) -> Path:
        ...


class CodegenSectionRenderer(Protocol):
    def render(self, section: RenderSection, target_seconds: float, work_dir: Path, output_path: Path, artifacts_dir: Path) -> Path:
        ...


class SlideshowSectionRenderer(Protocol):
    def render(self, section: RenderSection, duration_seconds: float, work_dir: Path, output_path: Path) -> Path:
        ...


class SectionRenderError(RuntimeError):
    pass


class SectionAnimator:
    def __init__(
        self,
        router: Router,
        narrator: Narrator,
        registry: TracerRegistry,
        synthesizer: TextSynthesizer,
        template_renderer: TemplateRenderer,
        codegen_renderer: CodegenSectionRenderer,
        slideshow_renderer: SlideshowSectionRenderer,
        fit_clip: ClipFitter = fit_clip,
        build_audio: AudioBuilder = concat_audio_padded,
    ) -> None:
        self.router = router
        self.narrator = narrator
        self.registry = registry
        self.synthesizer = synthesizer
        self.template_renderer = template_renderer
        self.codegen_renderer = codegen_renderer
        self.slideshow_renderer = slideshow_renderer
        self.fit_clip = fit_clip
        self.build_audio = build_audio

    def animate(self, sections: list[RenderSection], output_dir: Path) -> tuple[list[SectionClip], list[str]]:
        routing = self.router.route(sections)
        warnings = list(routing.warnings)
        clips: list[SectionClip] = []

        for section, route in zip(sections, routing.routes):
            clip = self._animate_section(section, route, output_dir)
            clips.append(clip)
            warnings.extend(clip.warnings)

        return clips, warnings

    def _animate_section(self, section: RenderSection, route: ResolvedRoute, output_dir: Path) -> SectionClip:
        section_dir = output_dir / "sections" / f"section_{section.index:02d}"
        warnings: list[str] = []

        if route.path == "trace":
            try:
                return self._trace_section(section, route, section_dir)
            except Exception as exc:
                warnings.append(f"Section '{section.title}': trace animation failed ({exc}); using generated animation.")

        audio = self.synthesizer.synthesize_text(section.narration, section_dir / "narration.wav")
        duration = audio.duration_seconds
        path_used: PathUsed = "codegen"
        try:
            raw = self.codegen_renderer.render(
                section,
                duration,
                section_dir / "codegen_work",
                section_dir / "codegen_raw.mp4",
                output_dir / "codegen",
            )
        except Exception as exc:
            warnings.append(f"Section '{section.title}': generated animation failed ({exc}); using slideshow.")
            path_used = "slideshow"
            try:
                raw = self.slideshow_renderer.render(
                    section,
                    duration,
                    section_dir / "slideshow_work",
                    section_dir / "slideshow_raw.mp4",
                )
            except Exception as slideshow_exc:
                raise SectionRenderError(
                    f"Section '{section.title}' could not be rendered: {slideshow_exc}"
                ) from slideshow_exc

        video = self.fit_clip(raw, duration, section_dir / "clip.mp4")
        return SectionClip(
            section_index=section.index,
            title=section.title,
            video_path=str(video),
            audio_path=audio.audio_path,
            narration_segments=[audio.narration_text or section.narration],
            segment_durations=[duration],
            path_used=path_used,
            warnings=warnings,
        )

    def _trace_section(self, section: RenderSection, route: ResolvedRoute, section_dir: Path) -> SectionClip:
        tracer = self.registry.get(route.tracer or "")
        if tracer is None:
            raise ValueError(f"unknown tracer {route.tracer}")

        steps = tracer.trace(route.inputs)
        segments, warnings = self.narrator.narrate(section, steps)

        segment_paths: list[Path] = []
        segment_totals: list[float] = []
        step_durations: list[float] = []
        texts: list[str] = []
        for number, segment in enumerate(segments):
            audio = self.synthesizer.synthesize_text(
                segment.text,
                section_dir / "audio" / f"segment_{number:03d}.wav",
            )
            durations = step_durations_for_segment(audio.duration_seconds, len(segment.step_indices) - 1)
            step_durations.extend(durations)
            segment_paths.append(Path(audio.audio_path))
            segment_totals.append(sum(durations))
            texts.append(audio.narration_text or segment.text)

        section_audio = self.build_audio(segment_paths, segment_totals, section_dir / "narration.m4a")
        raw = self.template_renderer.render(
            section.title,
            steps,
            step_durations,
            section_dir / "template_work",
            section_dir / "template_raw.mp4",
        )
        video = self.fit_clip(raw, sum(segment_totals), section_dir / "clip.mp4")

        return SectionClip(
            section_index=section.index,
            title=section.title,
            video_path=str(video),
            audio_path=str(section_audio),
            narration_segments=texts,
            segment_durations=segment_totals,
            path_used="trace",
            tracer=tracer.name,
            warnings=warnings,
        )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_section_animator.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/animation/section_animator.py backend/tests/test_section_animator.py
git commit -m "Add section animator with trace, codegen and slideshow fallbacks

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Integrate into DemoVideoService, response schema and API

**Files:**
- Modify: `backend/rendering/video_renderer.py` (extract `mux_video`)
- Modify: `backend/schemas/demo.py`
- Modify: `backend/services/demo_video_service.py` (rewrite generation flow)
- Modify: `backend/main.py` (wiring)
- Delete: `backend/rendering/binary_search_render.py`
- Test: `backend/tests/test_demo_video_service.py`

**Interfaces:**
- Consumes: `build_render_sections`, `SectionAnimator.animate`, `SectionClip`, `SectionSummary`, `concat_clips`, `concat_audio_padded`, `write_srt_file(narrations, durations, output_path)`, all tracers/renderers.
- Produces: `mux_video(video_path: Path, output_path: Path, audio_path: Path | None = None, subtitle_path: Path | None = None) -> Path`; `DemoVideoResponse.sections: list[SectionSummary]`; new `DemoVideoService.__init__(lesson_analyzer_service, lesson_planner_service, script_writer_service, section_animator, output_root=Path("output"), knowledge_agent_service=None, enable_subtitles=True, concat_clips=concat_clips, build_audio=concat_audio_padded, mux=mux_video)`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_demo_video_service.py`

```python
from pathlib import Path

from animation.schemas import SectionClip
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, ScriptSection, UserLessonRequest
from services.demo_video_service import DemoVideoService


class Analyzer:
    def analyze_lesson_request(self, request):
        return LessonRequest(topic="Binary Search", audience="beginner", goal="understand it",
                             duration_minutes=2, teaching_depth="introductory")


class Planner:
    def create_lesson_plan(self, lesson_request):
        return LessonPlan(title="Binary Search", learning_objectives=["halve"], sections=["How"])


class Writer:
    def create_lesson_script(self, lesson_request, lesson_plan):
        return LessonScript(introduction="Hi.",
                            sections=[ScriptSection(section_title="How", narration="Halve it.")],
                            conclusion="Bye.")


class Animator:
    def __init__(self):
        self.sections = None

    def animate(self, sections, output_dir):
        self.sections = sections
        clips = [
            SectionClip(section_index=s.index, title=s.title, video_path=f"v{s.index}.mp4",
                        audio_path=f"a{s.index}.m4a", narration_segments=[s.narration, "extra"],
                        segment_durations=[1.0, 2.0], path_used="trace" if s.index == 1 else "codegen",
                        tracer="binary_search" if s.index == 1 else None,
                        warnings=["w"] if s.index == 2 else [])
            for s in sections
        ]
        return clips, ["router warning", "w"]


def test_generates_video_from_section_clips(tmp_path):
    calls = {}
    animator = Animator()

    def concat_clips(paths, out):
        calls["clips"] = paths
        return out

    def build_audio(paths, durations, out):
        calls["audio"] = (paths, durations)
        return out

    def mux(video, out, audio, subtitles):
        calls["mux"] = (video, audio, subtitles)
        out.write_bytes(b"mp4")
        return out

    service = DemoVideoService(
        lesson_analyzer_service=Analyzer(),
        lesson_planner_service=Planner(),
        script_writer_service=Writer(),
        section_animator=animator,
        output_root=tmp_path,
        concat_clips=concat_clips,
        build_audio=build_audio,
        mux=mux,
    )

    response = service.generate_demo_video(UserLessonRequest(request="Explain binary search"))

    assert [s.title for s in animator.sections] == ["Introduction", "How", "Conclusion"]
    assert calls["clips"] == [Path("v0.mp4"), Path("v1.mp4"), Path("v2.mp4")]
    assert calls["audio"][1] == [3.0, 3.0, 3.0]
    assert response.scene_durations == [3.0, 3.0, 3.0]
    assert [s.path_used for s in response.sections] == ["codegen", "trace", "codegen"]
    assert response.sections[1].tracer == "binary_search"
    assert response.sections[2].warnings == ["w"]
    assert "router warning" in response.qc_warnings
    assert response.visual_plan is None
    srt = Path(response.subtitle_path).read_text(encoding="utf-8")
    assert "Halve it." in srt and "extra" in srt
    assert (Path(response.output_dir) / "sections.json").exists()
    assert response.video_path.endswith("lesson_demo.mp4")
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_demo_video_service.py -v`
Expected: FAIL — `TypeError: DemoVideoService.__init__() got an unexpected keyword argument 'section_animator'`.

- [ ] **Step 3: Extract `mux_video` in `backend/rendering/video_renderer.py`**

In `render_video_from_frames`, replace everything from `if audio_path is None and subtitle_path is None:` down to the function's final `return output_path` with:

```python
    if audio_path is None and subtitle_path is None:
        return video_only_path

    return mux_video(video_only_path, output_path, audio_path, subtitle_path)
```

and add this new function directly below `render_video_from_frames` (its body is the moved mux code, unchanged):

```python
def mux_video(
    video_path: Path,
    output_path: Path,
    audio_path: Path | None = None,
    subtitle_path: Path | None = None,
) -> Path:
    """
    Combine a video-only file with optional narration audio and a soft subtitle track.
    """
    if audio_path is not None and not audio_path.exists():
        raise ValueError(f"Audio file not found: {audio_path}")
    if subtitle_path is not None and not subtitle_path.exists():
        raise ValueError(f"Subtitle file not found: {subtitle_path}")

    mux_command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
    ]
    if audio_path is not None:
        mux_command.extend(["-i", str(audio_path)])
    if subtitle_path is not None:
        mux_command.extend(["-i", str(subtitle_path)])

    mux_command.extend(["-map", "0:v:0"])
    if audio_path is not None:
        mux_command.extend(["-map", "1:a:0", "-c:a", "aac", "-b:a", "128k"])
    if subtitle_path is not None:
        subtitle_input_index = 2 if audio_path is not None else 1
        mux_command.extend(
            [
                "-map",
                f"{subtitle_input_index}:s:0",
                "-c:s",
                "mov_text",
                "-metadata:s:s:0",
                "language=eng",
            ]
        )
    mux_command.extend(["-c:v", "copy", "-shortest", str(output_path)])

    subprocess.run(
        mux_command,
        check=True,
    )

    return output_path
```

- [ ] **Step 4: Update `backend/schemas/demo.py`**

Add the import `from animation.schemas import SectionSummary` and change these fields (others unchanged):

```python
    visual_plan: ScenePlan | None = Field(
        default=None,
        description="Legacy slideshow scene plan; empty for animated runs.",
    )
    frame_paths: list[str] = Field(
        default_factory=list,
        description="Legacy raw PNG frame paths; empty for animated runs.",
    )
    captioned_frame_paths: list[str] = Field(
        default_factory=list,
        description="Legacy captioned PNG frame paths; empty for animated runs.",
    )
```

and add after `video_path`:

```python
    sections: list[SectionSummary] = Field(
        default_factory=list,
        description="How each section of the video was animated.",
    )
```

Update the `scene_durations` description to `"Final per-section durations used for video timing."`.

- [ ] **Step 5: Rewrite `backend/services/demo_video_service.py`**

Replace the whole file with:

```python
import json
import re
from pathlib import Path
from typing import Callable, Protocol
from uuid import uuid4

from pydantic import BaseModel

from animation.schemas import RenderSection, SectionClip, SectionSummary, build_render_sections
from animation.timing import concat_audio_padded, concat_clips
from rendering.subtitle_renderer import write_srt_file
from rendering.video_renderer import mux_video
from schemas.demo import DemoVideoResponse
from schemas.knowledge import KnowledgeBase, KnowledgeGap
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, UserLessonRequest


class LessonAnalyzer(Protocol):
    def analyze_lesson_request(
        self,
        request: UserLessonRequest,
    ) -> LessonRequest:
        ...


class KnowledgeAgent(Protocol):
    def create_knowledge_base(
        self,
        lesson_request: LessonRequest,
    ) -> KnowledgeBase:
        ...


class LessonPlanner(Protocol):
    def create_lesson_plan(self, lesson_request: LessonRequest) -> LessonPlan:
        ...


class ScriptWriter(Protocol):
    def create_lesson_script(
        self,
        lesson_request: LessonRequest,
        lesson_plan: LessonPlan,
    ) -> LessonScript:
        ...


class SectionAnimatorLike(Protocol):
    def animate(
        self,
        sections: list[RenderSection],
        output_dir: Path,
    ) -> tuple[list[SectionClip], list[str]]:
        ...


ConcatClips = Callable[[list[Path], Path], Path]
BuildAudio = Callable[[list[Path], list[float], Path], Path]
Mux = Callable[[Path, Path, Path | None, Path | None], Path]


class DemoVideoService:
    def __init__(
        self,
        lesson_analyzer_service: LessonAnalyzer,
        lesson_planner_service: LessonPlanner,
        script_writer_service: ScriptWriter,
        section_animator: SectionAnimatorLike,
        output_root: Path = Path("output"),
        knowledge_agent_service: KnowledgeAgent | None = None,
        enable_subtitles: bool = True,
        concat_clips: ConcatClips = concat_clips,
        build_audio: BuildAudio = concat_audio_padded,
        mux: Mux = mux_video,
    ) -> None:
        self.lesson_analyzer_service = lesson_analyzer_service
        self.lesson_planner_service = lesson_planner_service
        self.script_writer_service = script_writer_service
        self.section_animator = section_animator
        self.output_root = output_root
        self.knowledge_agent_service = knowledge_agent_service
        self.enable_subtitles = enable_subtitles
        self.concat_clips = concat_clips
        self.build_audio = build_audio
        self.mux = mux

    def generate_demo_video(
        self,
        request: UserLessonRequest,
    ) -> DemoVideoResponse:
        lesson_request = self.lesson_analyzer_service.analyze_lesson_request(request)
        lesson_request = self._normalize_lesson_request_topic(request, lesson_request)

        knowledge_base = None
        qc_warnings: list[str] = []
        if self.knowledge_agent_service is not None:
            knowledge_base = self.knowledge_agent_service.create_knowledge_base(
                lesson_request
            )
            qc_warnings = self._build_qc_warnings(knowledge_base)

        lesson_plan = self.lesson_planner_service.create_lesson_plan(lesson_request)
        lesson_script = self.script_writer_service.create_lesson_script(
            lesson_request,
            lesson_plan,
        )

        sections = build_render_sections(lesson_script)
        if not sections:
            raise ValueError("Lesson script has no narration to render.")

        output_dir = self._create_output_dir(lesson_request.topic)
        clips, animation_warnings = self.section_animator.animate(sections, output_dir)
        qc_warnings.extend(animation_warnings)

        clip_durations = [sum(clip.segment_durations) for clip in clips]
        video_only_path = self.concat_clips(
            [Path(clip.video_path) for clip in clips],
            output_dir / "lesson_video_only.mp4",
        )
        audio_path = self.build_audio(
            [Path(clip.audio_path) for clip in clips],
            clip_durations,
            output_dir / "narration.m4a",
        )

        subtitle_path: Path | None = None
        if self.enable_subtitles:
            subtitle_path = write_srt_file(
                [text for clip in clips for text in clip.narration_segments],
                [duration for clip in clips for duration in clip.segment_durations],
                output_dir / "subtitles.srt",
            )

        video_path = self.mux(
            video_only_path,
            output_dir / "lesson_demo.mp4",
            audio_path,
            subtitle_path,
        )

        summaries = [
            SectionSummary(
                title=clip.title,
                path_used=clip.path_used,
                tracer=clip.tracer,
                duration_seconds=duration,
                warnings=clip.warnings,
            )
            for clip, duration in zip(clips, clip_durations)
        ]

        self._write_json_artifacts(
            output_dir=output_dir,
            lesson_request=lesson_request,
            lesson_plan=lesson_plan,
            lesson_script=lesson_script,
            knowledge_base=knowledge_base,
            summaries=summaries,
        )

        return DemoVideoResponse(
            lesson_request=lesson_request,
            knowledge_base=knowledge_base,
            qc_warnings=qc_warnings,
            lesson_plan=lesson_plan,
            lesson_script=lesson_script,
            output_dir=str(output_dir),
            scene_durations=clip_durations,
            audio_path=str(audio_path),
            subtitle_path=str(subtitle_path) if subtitle_path else None,
            video_path=str(video_path),
            sections=summaries,
        )

    def _normalize_lesson_request_topic(
        self,
        request: UserLessonRequest,
        lesson_request: LessonRequest,
    ) -> LessonRequest:
        raw_topic = request.request.lower()

        if "photosynthesis" in raw_topic:
            lesson_request.topic = "Photosynthesis"
            return lesson_request
        if "binary search" in raw_topic or "binary-search" in raw_topic:
            lesson_request.topic = "Binary Search"
            return lesson_request
        if "sorting" in raw_topic:
            lesson_request.topic = "Sorting"
            return lesson_request

        return lesson_request

    def _build_qc_warnings(self, knowledge_base: KnowledgeBase) -> list[str]:
        warnings: list[str] = []

        for gap in knowledge_base.gaps:
            warnings.append(self._format_gap_warning(gap))

        if knowledge_base.conflicting_information:
            for conflict in knowledge_base.conflicting_information:
                warnings.append(f"Conflicting information flagged: {conflict}")

        return warnings

    def _format_gap_warning(self, gap: KnowledgeGap) -> str:
        return f"Knowledge gap: {gap.question} ({gap.reason})"

    def _create_output_dir(self, topic: str) -> Path:
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        if not slug:
            slug = "lesson"

        output_dir = self.output_root / f"{slug}-{uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=False)
        return output_dir

    def _write_json_artifacts(
        self,
        output_dir: Path,
        lesson_request: LessonRequest,
        lesson_plan: LessonPlan,
        lesson_script: LessonScript,
        knowledge_base: KnowledgeBase | None,
        summaries: list[SectionSummary],
    ) -> None:
        artifacts: list[tuple[str, BaseModel]] = [
            ("lesson_request.json", lesson_request),
            ("lesson_plan.json", lesson_plan),
            ("lesson_script.json", lesson_script),
        ]

        if knowledge_base is not None:
            artifacts.append(("knowledge_base.json", knowledge_base))

        for filename, artifact in artifacts:
            (output_dir / filename).write_text(
                artifact.model_dump_json(indent=2),
                encoding="utf-8",
            )

        (output_dir / "sections.json").write_text(
            json.dumps([summary.model_dump() for summary in summaries], indent=2),
            encoding="utf-8",
        )
```

- [ ] **Step 6: Run the service test**

Run: `python -m pytest tests/test_demo_video_service.py -v`
Expected: PASS.

- [ ] **Step 7: Rewire `backend/main.py`**

Replace the imports block and everything up to (not including) `app = FastAPI()` with:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from pathlib import Path

from animation.codegen.generator import CodegenRenderer
from animation.narrator import StepNarrator
from animation.router import AnimationRouter
from animation.section_animator import SectionAnimator
from animation.slideshow import SlideshowRenderer
from animation.templates.render import ArrayTemplateRenderer
from animation.tracers import default_registry
from schemas.demo import DemoVideoResponse
from schemas.lesson import (
    LessonPlan,
    LessonRequest,
    LessonScript,
    LessonScriptRequest,
    UserLessonRequest,
)
from schemas.knowledge import KnowledgeBase
from schemas.visual import ScenePlan
from services.llm_service import LLMService
from services.demo_video_service import DemoVideoService
from services.knowledge_agent_service import KnowledgeAgentService
from services.lesson_analyzer_service import LessonAnalyzerService
from services.lesson_planner_service import LessonPlannerService
from services.script_writer_service import ScriptWriterService
from services.tts_service import EdgeTTSService, SilentTTSService
from services.visual_planner_service import VisualPlannerService


def build_tts_synthesizer() -> EdgeTTSService | SilentTTSService:
    try:
        import edge_tts  # noqa: F401

        return EdgeTTSService()
    except ImportError:
        return SilentTTSService()


```

Replace the block from `llm_service = LLMService()` to the end of the `demo_video_service = DemoVideoService(...)` call with:

```python
llm_service = LLMService()
lesson_analyzer_service = LessonAnalyzerService(llm_service)
knowledge_agent_service = KnowledgeAgentService(llm_service)
lesson_planner_service = LessonPlannerService(llm_service)
script_writer_service = ScriptWriterService(llm_service)
visual_planner_service = VisualPlannerService(llm_service)
tracer_registry = default_registry()
section_animator = SectionAnimator(
    router=AnimationRouter(llm_service, tracer_registry),
    narrator=StepNarrator(llm_service),
    registry=tracer_registry,
    synthesizer=build_tts_synthesizer(),
    template_renderer=ArrayTemplateRenderer(),
    codegen_renderer=CodegenRenderer(llm_service),
    slideshow_renderer=SlideshowRenderer(),
)
demo_video_service = DemoVideoService(
    lesson_analyzer_service=lesson_analyzer_service,
    lesson_planner_service=lesson_planner_service,
    script_writer_service=script_writer_service,
    section_animator=section_animator,
    output_root=output_root,
    knowledge_agent_service=knowledge_agent_service,
)
```

Everything from `@app.get("/")` onward stays unchanged (the `/lesson/visual-plan` endpoint remains).

- [ ] **Step 8: Delete the hard-coded binary search renderer**

Run: `git rm backend/rendering/binary_search_render.py`
Then: `grep -rn "binary_search_render" backend --include=*.py`
Expected: no matches (ignore anything under `backend/output/`).

- [ ] **Step 9: Verify the app imports and all tests pass**

Run: `GEMINI_API_KEY=dummy GEMINI_MODEL=dummy python -c "import main; print('ok')"`
Expected: `ok`.
Run: `python -m pytest -v`
Expected: all non-slow tests pass.

- [ ] **Step 10: Commit**

```bash
git add backend/rendering/video_renderer.py backend/schemas/demo.py backend/services/demo_video_service.py backend/main.py backend/tests/test_demo_video_service.py
git commit -m "Generate lessons from animated section clips

Replace the visual-plan slideshow flow with the section animator, extract
mux_video, add per-section summaries to the response and remove the
hard-coded binary search renderer.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

(`git rm` in Step 8 already staged the deletion; it is included in this commit.)

---

### Task 14: Frontend section badges

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: `DemoVideoResponse.sections` (`title`, `path_used`, `tracer`, `duration_seconds`, `warnings`).

- [ ] **Step 1: Update the response type and stage labels in `App.tsx`**

Replace the `VideoResponse` type with:

```tsx
type SectionSummary = {
    title: string;
    path_used: "trace" | "codegen" | "slideshow";
    tracer: string | null;
    duration_seconds: number;
    warnings: string[];
};
type VideoResponse = {
    lesson_request: { topic: string; audience: string; duration_minutes: number };
    lesson_plan: { title: string; learning_objectives: string[] };
    scene_durations: number[];
    video_path: string;
    audio_path: string | null;
    subtitle_path: string | null;
    sections: SectionSummary[];
};
```

In `stages`, replace the "Designing scenes" and "Rendering motion" entries with:

```tsx
    { label: "Choosing animations", detail: "Matching each section to an algorithm trace or a custom scene" },
    { label: "Animating sections", detail: "Rendering motion with Manim" },
```

Add this helper above `function App()`:

```tsx
function pathLabel(section: SectionSummary): string {
    if (section.path_used === "trace") return `Algorithm trace · ${section.tracer ?? "unknown"}`;
    if (section.path_used === "codegen") return "Custom animation";
    return "Slideshow fallback";
}
```

- [ ] **Step 2: Render the badges in the result panel**

Replace the `{result && <section className="result-panel">...</section>}` line with:

```tsx
                {result && <section className="result-panel"><div><p className="panel-kicker">Export complete</p><h2>{result.lesson_plan.title}</h2><p>{result.lesson_request.audience} lesson · {result.sections.length} sections · narrated video with subtitles</p>{result.sections.length > 0 && <ul className="section-list">{result.sections.map((section, index) => <li key={`${index}-${section.title}`}><span className="section-title">{section.title}</span><span className={`path-badge path-${section.path_used}`}>{pathLabel(section)}</span></li>)}</ul>}</div><div className="result-badge">MP4 ready <span>✓</span></div></section>}
```

- [ ] **Step 3: Add styles to the end of `frontend/src/index.css`**

```css
.section-list {
    list-style: none;
    margin: 0.75rem 0 0;
    padding: 0;
    display: grid;
    gap: 0.4rem;
}

.section-list li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    font-size: 0.9rem;
}

.path-badge {
    border-radius: 999px;
    padding: 0.15rem 0.6rem;
    font-size: 0.75rem;
    font-weight: 600;
    white-space: nowrap;
}

.path-trace {
    background: #dcfce7;
    color: #166534;
}

.path-codegen {
    background: #e0e7ff;
    color: #3730a3;
}

.path-slideshow {
    background: #fef3c7;
    color: #92400e;
}
```

- [ ] **Step 4: Type-check and build**

Run: `cd frontend && bun run build` (if `bun` is not installed: `npm run build`)
Expected: build succeeds with no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/index.css
git commit -m "Show how each video section was animated

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: End-to-end verification

**Files:**
- Test: `backend/tests/test_end_to_end.py`

**Interfaces:**
- Consumes: everything above; `FakeLLM`; `FakeTTSService`; `EXAMPLES_DIR`.

- [ ] **Step 1: Write the slow end-to-end test** — `backend/tests/test_end_to_end.py`

```python
import pytest

from animation.codegen.generator import EXAMPLES_DIR, CodegenRenderer
from animation.narrator import StepNarrator
from animation.router import AnimationRouter
from animation.section_animator import SectionAnimator
from animation.slideshow import SlideshowRenderer
from animation.templates.render import ArrayTemplateRenderer
from animation.timing import probe_duration
from animation.tracers import default_registry
from fakes import FakeLLM
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, ScriptSection, UserLessonRequest
from services.demo_video_service import DemoVideoService
from services.tts_service import FakeTTSService


class Analyzer:
    def analyze_lesson_request(self, request):
        return LessonRequest(topic="Binary Search", audience="beginner", goal="understand it",
                             duration_minutes=1, teaching_depth="introductory")


class Planner:
    def create_lesson_plan(self, lesson_request):
        return LessonPlan(title="Binary Search", learning_objectives=["halve"], sections=["How"])


class Writer:
    def create_lesson_script(self, lesson_request, lesson_plan):
        return LessonScript(
            introduction="Let's find a number fast.",
            sections=[ScriptSection(section_title="How binary search works",
                                    narration="We look for 23 in 2, 5, 8, 12, 16, 23, 38.")],
            conclusion="Halving makes it quick.",
        )


@pytest.mark.slow
def test_full_lesson_renders_with_mixed_paths(tmp_path):
    example = (EXAMPLES_DIR / "title_card.py").read_text(encoding="utf-8")
    llm = FakeLLM([
        {"routes": [
            {"section_index": 0, "path": "codegen"},
            {"section_index": 1, "path": "trace", "tracer": "binary_search",
             "inputs_json": '{"values": [2, 5, 8, 12, 16, 23, 38], "target": 23}'},
            {"section_index": 2, "path": "codegen"},
        ]},
        {"code": example},                                   # intro codegen
        {"sentences": ["a", "b", "c", "d", "e"],             # binary search narration (5 steps)
         "group_with_previous": [False] * 5},
        {"code": example},                                   # conclusion codegen
    ])
    registry = default_registry()
    animator = SectionAnimator(
        router=AnimationRouter(llm, registry),
        narrator=StepNarrator(llm),
        registry=registry,
        synthesizer=FakeTTSService(),
        template_renderer=ArrayTemplateRenderer(),
        codegen_renderer=CodegenRenderer(llm),
        slideshow_renderer=SlideshowRenderer(),
    )
    service = DemoVideoService(
        lesson_analyzer_service=Analyzer(),
        lesson_planner_service=Planner(),
        script_writer_service=Writer(),
        section_animator=animator,
        output_root=tmp_path,
    )

    response = service.generate_demo_video(UserLessonRequest(request="Explain binary search"))

    assert [s.path_used for s in response.sections] == ["codegen", "trace", "codegen"]
    assert response.qc_warnings == []
    assert probe_duration(response.video_path) == pytest.approx(sum(response.scene_durations), abs=0.5)
```

- [ ] **Step 2: Run the full suite including slow tests**

Run: `python -m pytest -v -m "slow or not slow"`
Expected: all pass. This takes a few minutes (real Manim renders).

- [ ] **Step 3: Manual run with the real LLM**

Start the backend: `python -m uvicorn main:app --port 8000` (from `backend/`, with `.env` containing `GEMINI_API_KEY` and `GEMINI_MODEL`).
Start the frontend: `cd frontend && bun run dev`.
Generate `"Explain binary search to a beginner."` in the UI.
Check:
- the result panel shows at least one `Algorithm trace · binary_search` badge;
- the video in the library plays with narration; in the binary-search section the pointers move and halves dim in time with the sentences;
- subtitles are available as a track;
- `backend/output/<lesson>/codegen/` contains the attempt `.py` files for codegen sections.

Then try `"Explain bubble sort"` and `"Explain how photosynthesis works"` (the latter should be all codegen, possibly with slideshow fallbacks — acceptable, but note any warnings).

Record observations (what looked wrong, which sections fell back and why) for the final report. Stop the servers.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_end_to_end.py
git commit -m "Add end-to-end animated lesson test

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

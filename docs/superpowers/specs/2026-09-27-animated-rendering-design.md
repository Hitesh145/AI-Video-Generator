# Animated Rendering — Design Spec

**Date:** 2026-09-27
**Status:** Draft for review
**Branch:** `feature/animated-rendering`

## 1. Goal

Replace the current slideshow output (static PIL frames + burned captions + ffmpeg concat) with real animation: elements that move, highlight and transform in sync with narration.

- **Purpose:** portfolio / learning project — visual quality and a clearly explainable architecture matter more than scale.
- **First domain:** CS / algorithms (arrays, pointers, searching, sorting).
- **Success criterion:** `"Explain binary search to a beginner"` produces a video in which the array, `lo`/`mid`/`hi` pointers and discarded halves animate step by step, each step timed to its own narration sentence, with correct algorithm behaviour guaranteed.

### Assumptions
- Upstream LLM stages (analyzer → knowledge → planner → script writer) stay unchanged.
- TTS stays on edge-tts; ffmpeg is already installed.
- Rendering runs locally on Windows; a synchronous request taking a few minutes is acceptable.

## 2. Architecture

```
UserLessonRequest
  → LessonAnalyzer → KnowledgeAgent → LessonPlanner → ScriptWriter   (unchanged)
  → build RenderSections from script (intro, each section, conclusion)
  → AnimationRouter (1 LLM call): per section → trace | codegen
       ├─ Trace path:    tracer.trace(inputs) → TraceSteps
       │                 → StepNarrator (LLM): one sentence per step
       │                 → TTS per step → step durations
       │                 → Manim template scene → section clip
       ├─ Codegen path:  TTS for section narration → target duration
       │                 → LLM writes Manim SectionScene → AST check → subprocess render
       │                 → retry with error feedback (max 3) → duration fit → section clip
       └─ Fallback:      existing PIL slideshow renderer → section clip
  → ffmpeg concat section clips + concat narration audio
  → SRT from real per-step/per-section timings → mux (existing code)
```

### Key decisions
1. **Unit of rendering = script section.** The script's introduction, each `ScriptSection`, and the conclusion each become one `RenderSection` rendered to its own mp4. Lessons can mix paths; failures degrade one section only.
2. **Router is one structured LLM call** that sees all sections and the tracer catalogue (name, description, input JSON schema) and returns a route per section. Tracer inputs are validated against the tracer's Pydantic schema; invalid → codegen.
3. **Audio is the clock.** Trace path: per-step TTS, template holds each step for exactly its audio duration. Codegen path: LLM receives the section's audio duration; the rendered clip is then padded/sped/trimmed to match.
4. **Slideshow renderer remains as the last-resort fallback** so a lesson always produces a video.
5. **Removed:** the topic special-casing and `rendering/binary_search_render.py` (already deleted in pre-implementation cleanup); `caption_renderer.py` and `render_pipeline.py` are removed during integration. Burned-in captions (`caption_renderer`) are no longer applied to animated clips; subtitles are delivered as a soft track.

## 3. New package layout

```
backend/animation/
  schemas.py            RenderSection, Route, SectionClip, TraceStep, ArrayState
  router.py             AnimationRouter
  narrator.py           StepNarrator
  section_animator.py   SectionAnimator (orchestrates paths + fallbacks per section)
  timing.py             ffprobe duration, pad/speed/trim fit
  tracers/
    base.py             Tracer protocol, TracerRegistry
    binary_search.py
    linear_search.py
    bubble_sort.py
    insertion_sort.py
  templates/
    array_diff.py       pure state-diff → planned animation ops (no Manim import)
    array_scene.py      Manim ArrayScene consuming (steps, durations)
    render.py           render a template scene to mp4 via subprocess
  codegen/
    kit.py              style kit imported by generated scenes
    validator.py        AST allowlist
    generator.py        CodegenRenderer (prompt, retry loop, artifacts)
    examples/           2–3 example scenes used in the prompt
backend/tests/          pytest suite
```

## 4. Data model

```python
class RenderSection(BaseModel):
    index: int                 # 0-based position in the video
    title: str                 # "Introduction", section_title, "Conclusion"
    narration: str

class Route(BaseModel):
    section_index: int
    path: Literal["trace", "codegen"]
    tracer: str | None = None
    inputs_json: str = "{}"    # JSON object string (Gemini structured output handles
                               # open-ended dicts poorly); parsed with the tracer's schema

class RoutePlan(BaseModel):
    routes: list[Route]        # exactly one per section

class ArrayState(BaseModel):
    values: list[int | str]
    pointers: dict[str, int] = {}      # {"lo": 0, "mid": 3, "hi": 6}
    highlighted: list[int] = []        # cells being compared
    dimmed: list[int] = []             # cells ruled out
    swapped: tuple[int, int] | None = None
    sorted_indices: list[int] = []     # cells in final position (left or right side)
    found: int | None = None           # index of located element

class TraceStep(BaseModel):
    state: ArrayState
    event: str                         # factual, machine-written description

class StepNarration(BaseModel):
    sentences: list[str]               # len == number of narrated steps
    group_with_previous: list[bool]    # len == number of steps; step 0 always False

class SectionClip(BaseModel):
    section_index: int
    title: str
    video_path: str
    audio_path: str
    narration_segments: list[str]      # one per timed segment
    segment_durations: list[float]
    path_used: Literal["trace", "codegen", "slideshow"]
    tracer: str | None = None
    warnings: list[str] = []
```

Full-state snapshots (not deltas) make steps self-contained, easy to test, and easy to diff.

## 5. Trace path

### Tracer interface
```python
class Tracer(Protocol):
    name: str
    description: str
    input_schema: type[BaseModel]
    template: Literal["array"]
    def trace(self, inputs: BaseModel) -> list[TraceStep]: ...
```
`TracerRegistry` holds tracers by name and exposes a catalogue for the router prompt. Adding an algorithm = one file + one registration line.

Input limits enforced by each schema: 2–12 values (readability at 854×480), values are ints in −99..999.

### Milestone-1 tracers
| Tracer | Inputs | Notable state |
|---|---|---|
| `binary_search` | sorted `values`, `target` | pointers lo/mid/hi, dimmed ruled-out halves, `found` |
| `linear_search` | `values`, `target` | pointer i, highlighted current, `found` |
| `bubble_sort` | `values` | pointer j, highlighted pair, `swapped`, `sorted_indices` growing from right |
| `insertion_sort` | `values` | pointer key, `swapped`, `sorted_indices` growing from left |

`binary_search` rejects unsorted input at validation time.

### Step narration
`StepNarrator` makes one structured LLM call with the section narration and the list of `event` strings. It returns `StepNarration`. Validation: `group_with_previous` length equals step count, `group_with_previous[0]` is False, and `len(sentences)` equals the number of steps not grouped. Grouped steps are animated quickly (0.6 s each) inside the preceding narrated segment. On validation failure: retry once, then fall back to using each `event` string as its own sentence.

### Timing
Each narrated segment is synthesized with TTS separately; the segment's measured duration is split across its steps (grouped steps get 0.6 s each; the narrated step gets the remainder, minimum 1.0 s). The segment audio files are concatenated into the section audio.

### Array template
- `array_diff.py` is pure and Manim-free:
  - `plan_ops(prev, curr) -> list[Op]` for structural changes: `SwapCells(i, j)`, `AddPointer(name, index)`, `MovePointer(name, index)`, `RemovePointer(name)`, `MarkFound(index)`.
  - `cell_style(state, index) -> CellStyle(role, opacity)` for colouring; role is one of normal / highlight / sorted / found. The template animates every cell to its style each step.
- `ArrayScene` draws a row of cells with value labels and index labels, pointers as labelled arrows below cells, and a section title at the top. For each step it plays the ops (run time ≤ min(0.8 s, 60% of step duration)) and then `wait`s for the rest of the step duration.
- Visual language: highlight = amber fill, dimmed = 30% opacity, sorted = green fill, found = green fill + scale pulse, swap = cells move along arcs.
- Rendered via `manim render` subprocess on `array_scene.py`; steps/durations are written to JSON and the path passed in the `ARRAY_SCENE_DATA` environment variable; 854×480, 30 fps, Manim Community Edition, `Text` only (no LaTeX).

## 6. Codegen path

### Prompt contents
Section title, narration text, target duration in seconds, the style kit API, 2–3 example scenes, and rules:
- exactly one class `SectionScene(Scene)` with `construct`;
- only `Text`/`MarkupText` for text (no `MathTex`/`Tex`);
- keep all mobjects within the frame (use `fit_in_frame`); leave the bottom 15% clear for subtitles (`caption_safe_area`);
- total runtime ≈ target duration (the renderer will pad/trim).

Output schema: `{"code": str}`.

### Style kit (`codegen/kit.py`)
Theme colours shared with the array template, `title(text) -> Mobject`, `caption_safe_area() -> (ymin, ymax)`, `fit_in_frame(mobject) -> mobject`, `bullet_list(items) -> VGroup`.

### Safety
1. **AST allowlist** before any execution: imports limited to `manim`, `math`, `random`, `numpy`, `kit`. Reject names/attributes `open`, `exec`, `eval`, `compile`, `__import__`, `globals`, `locals`, `getattr`, `setattr`, `delattr`, `input`, `breakpoint`, any dunder attribute access, and modules `os`, `sys`, `subprocess`, `shutil`, `pathlib`, `socket`, `importlib`.
2. **Isolated subprocess**: `manim render` in a fresh temp working directory, hard timeout 120 s.
3. This is accident protection, not a security sandbox. Acceptable for local, single-user portfolio use; must not be exposed publicly without a real sandbox.

### Retry loop
Up to 3 attempts. On AST rejection, render error, timeout, or missing output file, the next prompt includes the previous code and the rejection reason or last 40 traceback lines. After 3 failures the section falls back to the slideshow, with a warning.

### Duration fit (`timing.fit_clip`)
Measure with ffprobe. If shorter than target → hold last frame (`tpad=stop_mode=clone`). If longer by ≤ 15% → speed up with `setpts`. If longer by > 15% → speed up by 15% then trim to target.

### Artifacts
`output/<lesson>/codegen/section_<N>_attempt_<K>.py` and `.log` for every attempt.

## 7. Integration

- `DemoVideoService` takes an injected `SectionAnimator` instead of `visual_planner_service`, `render_frames`, `caption_frames` and `render_video`. The existing slideshow pieces are passed into `SectionAnimator` as the fallback renderer.
- TTS: add a text-based method `synthesize_text(text, output_path) -> SceneAudio` to the TTS service (the current method requires a `VisualScene`).
- Final assembly: concat section clips (ffmpeg concat demuxer, re-encode for safety), concat section audio, build SRT from all clips' `narration_segments`/`segment_durations` via existing `write_srt_file`, then mux with the existing mux logic in `rendering/video_renderer.py` (extracted into a `mux_video(video, audio, srt, out)` function).
- `DemoVideoResponse` gains `sections: list[SectionSummary]` (`title`, `path_used`, `tracer`, `duration_seconds`, `warnings`). Existing fields `visual_plan`, `frame_paths`, `captioned_frame_paths` become optional/empty for animated runs.
- Frontend: show per-section path badges from `sections`; no other UI changes.
- Request remains synchronous.

## 8. Error handling

| Failure | Behaviour |
|---|---|
| Router call fails or returns wrong route count | All sections → codegen; warning |
| Unknown tracer / invalid inputs | That section → codegen; warning |
| Tracer raises | That section → codegen; warning |
| Narrator validation fails twice | Use `event` strings as sentences; warning |
| Template render fails | That section → codegen; warning |
| Codegen fails 3× | That section → slideshow; warning |
| Slideshow fails | Request fails with an error naming the section |

All warnings are collected into the response's `qc_warnings` and the per-section summary.

## 9. Testing

pytest under `backend/tests/`; slow tests marked `@pytest.mark.slow`.
- **Tracers** (TDD): expected state sequences for known inputs; binary search found/not-found; sorts end sorted; input validation.
- **`array_diff`**: op planning between hand-written states.
- **AST validator**: allowed and forbidden samples.
- **Router, narrator, codegen retry loop, `SectionAnimator` fallbacks**: fake LLM and fake renderers via the existing `Protocol` style.
- **Timing**: segment splitting math.
- **Slow**: render a 3-step `ArrayScene` at low quality; render a trivial generated scene; `fit_clip` against a real clip; end-to-end lesson with fake LLM and real rendering.

## 10. Dependencies
- `manim` (Community Edition) added to `backend/requirements.txt`. Uses pycairo wheels on Windows; no LaTeX required.
- `pytest` for tests.

## 11. Scope

**Milestone 1 (this spec):** router, step narrator, array template, 4 tracers, codegen path with style kit and validator, slideshow fallback, integration, pytest suite, frontend path badges.

**Housekeeping:** add `backend/output/`, `backend/test_animation/`, `backend/test_output/`, `tempCodeRunnerFile.py`, `__pycache__/` to `.gitignore`. The experimental custom engine (`backend/rendering/engine/`, `primitives/`, `renderers/`) and the hard-coded `binary_search_render.py` were removed on 2026-09-28 ahead of implementation.

**Out of scope:** tree and graph templates (milestone 2), job queue / async generation, voice changes, frontend redesign, production-grade sandboxing.

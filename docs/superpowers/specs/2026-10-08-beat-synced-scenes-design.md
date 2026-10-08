# Beat-Synced Scenes — Design Spec

**Date:** 2026-10-08
**Status:** Draft for review
**Branch:** `feature/beat-synced-scenes` (built on `feature/animated-rendering`, which is not yet merged)

## 1. Goal

Make the visuals of every LLM-written (codegen) section match what is being said at that moment.

- **Problem (measured on run `binary-search-36b78bcf`):** a codegen scene is written from the whole section narration plus one total duration. It hard-codes its own `wait()` pacing, so it finishes 7-19 s early and `fit_clip` freezes the last frame. Concretely: the "What if the dictionary was scrambled?" slide appears at about 17 s but is spoken at about 41 s; the abstract "three things can happen" narration is shown as a full worked example (target 61) that ends at 39 s while the narration is still introducing the cases.
- **Success criteria:**
  1. In a codegen section, each spoken sentence is shown while its beat is on screen; a beat's visuals never start more than 1 s after its audio.
  2. A codegen clip no longer ends in a frozen tail of more than 3 s (outside the final beat).
  3. Scenes only show what the narration states (no invented worked examples).
  4. Subtitles for codegen sections are per beat instead of one block per section.
- **Trace sections are untouched** (already synced per step).

### Assumptions
- Audio stays the clock; ffmpeg, edge-tts, Manim 0.21 and Gemini stay as they are.
- The script text is not rewritten by the new step, so speech and subtitles show exactly what the script wrote.
- A lesson taking tens of minutes end to end is out of scope (upstream LLM latency, no LLM timeout).

## 2. Design

### 2.1 Data flow (codegen path only)

```
RenderSection (narration)
  → split_sentences()                      deterministic
  → Storyboarder (1 LLM call)              beats: how many sentences + a visual description each
  → merge_short_beats()                    deterministic
  → TTS per beat → measured beat durations
  → build_audio(beat wavs)                 section audio, padded per beat
  → CodegenRenderer(beats + durations)     LLM writes SectionScene using BeatClock
  → render → read beat report → accept, or retry with timing feedback
  → fit_clip (small residual only) → SectionClip
     narration_segments = beat texts, segment_durations = beat durations
```

Intro and conclusion sections go through the same path.

### 2.2 Components

**`animation/storyboard.py` (new)**
- `split_sentences(text) -> list[str]`: regex split after `.`, `!`, `?` (optionally followed by a closing quote) and whitespace. Narration is TTS-oriented prose, so abbreviation handling is not needed.
- `Beat` (pydantic): `sentence_count: int`, `visual: str`. `Storyboard`: `beats: list[Beat]`. The LLM-facing schema is just these two fields (no nested lists of lists, no JSON-in-string).
- `Storyboarder.plan(section) -> StoryboardResult` with the validated beats mapped back to verbatim text: `list[PlannedBeat(text, visual)]`.
  - Validation: `sum(sentence_count) == len(sentences)`, every `sentence_count >= 1`, `1 <= len(beats) <= 8`, `visual` not blank. One retry on an invalid plan.
  - Prompt rules: group sentences into beats of one showable idea; every `visual` may only depict what the beat's sentences say; if the narration is abstract, describe an abstract diagram, not a worked example with invented numbers; keep objects and layout consistent across beats; text on screen stays short.
  - On failure after retry: deterministic fallback. Greedy-group sentences into beats of at least 25 words, `visual = "Illustrate what the narration says."`, plus a warning. So the beat clock still applies.
- `merge_short_beats(beats, min_words=8)`: a beat with fewer than 8 words is merged into its next neighbour (previous one if last); visuals are joined. Prevents beats too short to animate.

**`animation/section_animator.py` (changed, codegen branch only)**
- After storyboard: synthesize each beat's text (existing `_synthesize` with the silence fallback), collect durations, build section audio with the existing `concat_audio_padded`, pass beats and durations to the codegen renderer, then `fit_clip` to the sum of the beat durations.
- The slideshow fallback reuses the same beat audio and durations (subtitles stay per beat). The slideshow renderer itself is unchanged.
- `SectionClip.narration_segments`/`segment_durations` become the beats; `demo_video_service` and the SRT writer already consume these fields.

**`animation/codegen/kit.py` (extended): `BeatClock`**
- `BeatClock(scene, durations)` records `scene.renderer.time` as start. `end_beat()` waits (`scene.wait`) until `start + cumulative[i]`, so each beat ends on its absolute audio time regardless of how long the animations inside took. If the scene is already past that time it does not wait and records the overrun.
- After each `end_beat()` it rewrites a JSON report at the path in env var `BEAT_REPORT`: `[{beat, expected_end, actual_end, overrun}]`. Writing on every call keeps partial reports if the scene crashes later. The kit file is not AST-validated, so file writing there is allowed.
- Raises nothing on missing env var (no report written), so the kit stays usable by the array template.

**`animation/codegen/generator.py` (changed)**
- `render(section, beats, durations, work_dir, output_path, artifacts_dir)` replaces the `target_seconds` signature.
- Prompt: lists each beat with index, duration, narration text and visual description; requires one `# beat N` block per beat followed by `clock.end_beat()`, exactly N calls; requires that the animations inside a beat finish within about 85% of its duration (the clock pads the rest); forbids using `self.wait` just to reach the end of a beat; keeps all existing rules and examples (examples are updated to show `BeatClock`).
- The `SceneRenderer` callable gains the report path (passed to `render_manim_scene` through its existing `extra_env`).
- After a successful render the report is read and checked:
  - number of `end_beat` calls must equal the number of beats;
  - the largest overrun must be at most 1.0 s.
  Otherwise the attempt counts as failed and the retry loop feeds back a precise message such as "beat 2 ended 3.1 s late; shorten the animations in beats 1-2".
- On the last attempt a render that only failed the overrun check is accepted with a warning (it is still better than the slideshow); one that failed the call-count check is not.

**`services/script_writer_service.py` (prompt only; schema unchanged)**
- Adds rules: short sentences (under about 22 words), one idea per sentence; whenever a procedure is explained use one concrete example with specific values; no sentence that only restates the previous one; sentences should describe things that can be drawn. No hard word cap per section: total length is already governed by duration x 130 words, and a cap would shorten lessons.

### 2.3 Error handling and fallbacks

| Failure | Result |
|---|---|
| Storyboard LLM error or invalid plan (after one retry) | deterministic beats, warning |
| TTS failure for a beat | silence for that beat (existing behaviour), warning |
| Generated code invalid / render fails (3 attempts) | slideshow, using the same beat audio (existing behaviour) |
| Scene overran by more than 1 s | retry with feedback; last attempt accepted with warning |
| Wrong number of `end_beat` calls | counts as a failed attempt |

### 2.4 Out of scope
- Vision-model check of rendered frames (deferred; revisit if the timing report is not enough).
- LLM call timeout and overall lesson latency.
- Changing trace sections, the router order, `LessonScript`, or the API response shape.
- Slideshow renderer improvements.

## 3. Testing

- `split_sentences`: quotes after a period, `!`/`?`, trailing whitespace.
- `Storyboarder` with `FakeLLM`: valid plan; counts not summing; zero count; too many beats; retry then fallback; verbatim text mapping.
- `merge_short_beats`: short middle, short last, all short.
- `BeatClock`: a small real Manim render proves beats end on schedule within ~1 frame (marked slow), an overrunning beat is reported, and the report is written per call.
- `CodegenRenderer` with a fake scene renderer: prompt contains each beat's duration and text; overrun report triggers retry with the message; last-attempt overrun accepted with warning; wrong call count fails.
- `SectionAnimator`: codegen path synthesizes per beat, passes durations, segments equal beats; storyboard failure uses the deterministic beats; slideshow fallback keeps beat audio.
- Script writer prompt contains the new rules.
- End-to-end test (existing, fakes) updated for the new codegen signature.
- Live check after implementation: regenerate "Explain binary search to a beginner" and compare the beat reports and tail freeze against run `binary-search-36b78bcf`.

## 4. Verified assumption

A scratch Manim 0.21 scene (not kept) showed `scene.renderer.time` advancing by exactly the `run_time` of each `play` (including multi-animation plays) and each `wait`: 1.3 s, 2.0 s and 2.9 s after a 1.3 s play, a 0.7 s play and a 0.9 s wait, and the rendered file was 2.9 s long. `BeatClock` can therefore use `scene.renderer.time` directly.

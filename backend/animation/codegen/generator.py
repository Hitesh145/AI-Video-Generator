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
CLOCK_TOLERANCE_SECONDS = 0.05
# Overruns below this are not worth pointing the LLM at.
NOTICEABLE_OVERRUN_SECONDS = 0.25

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


def check_beat_report(report_path: Path, beat_count: int, durations: list[float] | None = None) -> TimingCheck:
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

    # The report is written by the scene's own clock, so verify the clock itself:
    # it must have started with the scene and run on the real beat durations.
    if any(float(row.get("start", 0.0)) > CLOCK_TOLERANCE_SECONDS for row in rows):
        return TimingCheck(
            "clock = BeatClock(self) was created after animations had already played. "
            "It must be the first line of construct.",
            True,
            0.0,
        )
    if durations is not None:
        total = 0.0
        for number, (row, duration) in enumerate(zip(rows, durations), start=1):
            total += duration
            if abs(float(row["expected_end"]) - total) > CLOCK_TOLERANCE_SECONDS:
                return TimingCheck(
                    f"Beat {number} was timed with the scene's own durations. "
                    "Use `BeatClock(self)` with no second argument so it reads the real beat durations.",
                    True,
                    0.0,
                )

    worst = max(overruns)
    if worst > MAX_OVERRUN_SECONDS:
        last = overruns.index(worst) + 1
        first = next(i for i, overrun in enumerate(overruns) if overrun > NOTICEABLE_OVERRUN_SECONDS) + 1
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
            summary = ""
            if problems:
                error = "Code rejected by validator:\n" + "\n".join(problems)
                summary = "Code rejected by validator: " + "; ".join(problems)
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
                    check = check_beat_report(report_path, len(beats), durations)
                    if check.error is None:
                        shutil.copyfile(attempt_output, output_path)
                        return CodegenResult(output_path, [])
                    error = check.error
                    if not check.hard and (best_late is None or check.worst_overrun < best_late[0]):
                        best_late = (check.worst_overrun, attempt_output, check.error)

            stem.with_suffix(".log").write_text(error, encoding="utf-8")
            errors.append(f"attempt {attempt}: {summary or error.splitlines()[0]}")
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

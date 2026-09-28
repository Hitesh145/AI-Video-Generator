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

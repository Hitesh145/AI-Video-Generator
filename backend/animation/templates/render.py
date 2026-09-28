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
        "--verbosity", "warning",
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

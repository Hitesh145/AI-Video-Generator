from pathlib import Path

from rendering.generic_frame_renderer import GenericFrameRenderer
from rendering.video_renderer import render_video_from_frames
from schemas.visual import ScenePlan


def render_scene_plan_frames(
    scene_plan: ScenePlan,
    output_dir: Path,
) -> list[Path]:
    """
    Render generic visual scenes into PNG frames.
    """
    renderer = GenericFrameRenderer()

    return renderer.render_scene_plan(
        scene_plan=scene_plan,
        output_dir=output_dir,
    )


def _frame_durations_for_scene_plan(scene_plan: ScenePlan, frame_paths: list[Path]) -> list[float]:
    durations: list[float] = []
    frame_index = 0

    for scene in scene_plan.scenes:
        frame_count = 3 if scene.visual_type.lower() == "animation" else 1
        scene_duration = scene.duration_seconds / frame_count
        durations.extend([scene_duration] * frame_count)
        frame_index += frame_count

    if len(durations) != len(frame_paths):
        if len(scene_plan.scenes) == len(frame_paths):
            return [scene.duration_seconds for scene in scene_plan.scenes]
        return [scene.duration_seconds for scene in scene_plan.scenes for _ in range(1)]

    return durations


def render_scene_plan_video(
    scene_plan: ScenePlan,
    output_dir: Path,
    output_name: str = "lesson_demo.mp4",
) -> Path:
    """
    Render generic visual scenes into PNG frames and assemble them into an MP4.
    """
    frame_paths = render_scene_plan_frames(
        scene_plan=scene_plan,
        output_dir=output_dir,
    )

    if not frame_paths:
        raise ValueError("Scene plan did not produce any frames.")

    durations = _frame_durations_for_scene_plan(scene_plan, frame_paths)

    return render_video_from_frames(
        frame_paths=frame_paths,
        durations=durations,
        output_path=output_dir / output_name,
        width=854,
        height=480,
    )

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

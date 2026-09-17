from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from rendering.generic_frame_renderer import (
    LIGHT_TEXT,
    draw_wrapped_text,
    get_font,
    safe_text,
    wrapped_lines,
)
from services.text_normalizer import normalize_text
from schemas.lesson import LessonScript
from schemas.visual import ScenePlan, VisualScene


CAPTION_BACKGROUND = (15, 23, 42)
CAPTION_BORDER = (51, 65, 85)


def narration_for_scene(
    scene: VisualScene,
    lesson_script: LessonScript,
) -> str:
    reference = safe_text(scene.narration_reference).lower()

    if reference in {"introduction", "intro"}:
        return lesson_script.introduction

    if reference == "conclusion":
        return lesson_script.conclusion

    if reference.startswith("script_section_"):
        section_number = reference.removeprefix("script_section_")
        if section_number.isdigit():
            index = int(section_number) - 1
            if 0 <= index < len(lesson_script.sections):
                return lesson_script.sections[index].narration

    for section in lesson_script.sections:
        if section.section_title == scene.section_title:
            return section.narration

    return scene.description


def concise_caption(text: str, max_chars: int = 170) -> str:
    clean_text = normalize_text(text)
    if len(clean_text) <= max_chars:
        return clean_text

    snippet = clean_text[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{snippet}..."


def _frames_per_scene(scene: VisualScene) -> int:
    return 3 if safe_text(scene.visual_type).lower() == "animation" else 1


def apply_script_captions(
    frame_paths: list[Path],
    scene_plan: ScenePlan,
    lesson_script: LessonScript,
    output_dir: Path,
) -> list[Path]:
    expected_count = sum(_frames_per_scene(scene) for scene in scene_plan.scenes)
    if len(frame_paths) != expected_count:
        if len(frame_paths) == len(scene_plan.scenes):
            expected_count = len(scene_plan.scenes)
        else:
            raise ValueError(
                "Frame count must match scene count for captions or render one frame per animation phase."
            )

    caption_dir = output_dir / "captioned_frames"
    caption_dir.mkdir(parents=True, exist_ok=True)

    captioned_paths: list[Path] = []
    frame_index = 0
    for scene in scene_plan.scenes:
        scene_frame_count = _frames_per_scene(scene)
        for _ in range(scene_frame_count):
            if frame_index >= len(frame_paths):
                break
            frame_path = frame_paths[frame_index]
            output_path = caption_dir / frame_path.name
            caption = concise_caption(narration_for_scene(scene, lesson_script))
            apply_caption_to_frame(frame_path, caption, output_path)
            captioned_paths.append(output_path)
            frame_index += 1

    if len(captioned_paths) != len(frame_paths):
        raise ValueError("Captioned frame count does not match rendered frame count.")

    return captioned_paths


def apply_caption_to_frame(
    frame_path: Path,
    caption: str,
    output_path: Path,
) -> Path:
    with Image.open(frame_path) as source:
        image = source.convert("RGB")

    draw = ImageDraw.Draw(image)
    width, height = image.size
    caption_font = get_font(18)

    max_lines = 3
    lines = wrapped_lines(caption, width=82)[:max_lines]
    line_height = 24
    box_height = 34 + len(lines) * line_height
    x1 = 36
    y1 = height - box_height - 20
    x2 = width - 36
    y2 = height - 20

    draw.rounded_rectangle(
        (x1, y1, x2, y2),
        radius=8,
        fill=CAPTION_BACKGROUND,
        outline=CAPTION_BORDER,
        width=2,
    )
    draw.text((x1 + 18, y1 + 10), "Narration", font=get_font(14), fill=(191, 219, 254))
    draw_wrapped_text(
        draw,
        " ".join(lines),
        (x1 + 18, y1 + 31),
        caption_font,
        LIGHT_TEXT,
        line_width=82,
        line_gap=4,
        max_lines=max_lines,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path

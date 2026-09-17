from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from rendering.base import BaseRenderer
from rendering.video_renderer import render_video


WIDTH = 1280
HEIGHT = 720

BACKGROUND = (245, 245, 245)
TEXT = (30, 30, 30)
BOX = (220, 220, 220)
ACTIVE = (180, 220, 180)
HIGHLIGHT = (255, 220, 120)
DISCARDED = (190, 190, 190)
TARGET = (150, 200, 255)


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]

    for font_path in font_paths:
        path = Path(font_path)
        if path.exists():
            return ImageFont.truetype(str(path), size)

    return ImageFont.load_default()


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = box

    text_box = draw.textbbox((0, 0), text, font=font)

    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]

    x = x1 + (x2 - x1 - text_width) / 2
    y = y1 + (y2 - y1 - text_height) / 2

    draw.text((x, y), text, font=font, fill=fill)


def create_frame(
    numbers: list[int],
    target: int,
    middle_index: int | None = None,
    discarded_indices: set[int] | None = None,
    output_path: Path | None = None,
    status_text: str | None = None,
) -> None:
    if discarded_indices is None:
        discarded_indices = set()

    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = get_font(42)
    label_font = get_font(28)
    number_font = get_font(32)

    draw.text(
        (WIDTH // 2, 70),
        "Binary Search",
        font=title_font,
        fill=TEXT,
        anchor="mm",
    )

    draw.text(
        (WIDTH // 2, 140),
        f"Target = {target}",
        font=label_font,
        fill=TEXT,
        anchor="mm",
    )

    box_width = 120
    box_height = 100
    gap = 15

    total_width = len(numbers) * box_width + (len(numbers) - 1) * gap
    start_x = (WIDTH - total_width) // 2
    start_y = 260

    for index, number in enumerate(numbers):
        x1 = start_x + index * (box_width + gap)
        y1 = start_y
        x2 = x1 + box_width
        y2 = y1 + box_height

        if index in discarded_indices:
            fill = DISCARDED
        elif middle_index == index:
            fill = HIGHLIGHT
        elif number == target:
            fill = TARGET
        else:
            fill = ACTIVE

        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=15,
            fill=fill,
            outline=TEXT,
            width=3,
        )

        draw_centered_text(
            draw,
            (x1, y1, x2, y2),
            str(number),
            number_font,
            TEXT,
        )

    if middle_index is not None:
        middle_x = (
            start_x
            + middle_index * (box_width + gap)
            + box_width // 2
        )

        draw.text(
            (middle_x, 430),
            "Middle",
            font=label_font,
            fill=TEXT,
            anchor="mm",
        )

    if status_text is not None:
        draw.text(
            (WIDTH // 2, 520),
            status_text,
            font=label_font,
            fill=TEXT,
            anchor="mm",
        )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)


class BinarySearchRenderer(BaseRenderer):
    """
    Renderer for the binary-search educational animation.
    """

    def render(
        self,
        description: str,
        output_dir: Path,
    ) -> Path:
        return render_binary_search_demo(output_dir)


def render_binary_search_demo(output_dir: Path) -> Path:
    """
    Render a three-step binary-search animation demonstrating how the search
    window shrinks toward the target value.
    """
    frames_dir = output_dir / "binary_search_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    numbers = [2, 5, 8, 12, 16, 23, 38]
    target = 23

    create_frame(
        numbers=numbers,
        target=target,
        middle_index=3,
        status_text="Middle value is 12. 23 > 12, so search the right half.",
        output_path=frames_dir / "frame_01.png",
    )

    create_frame(
        numbers=numbers,
        target=target,
        middle_index=None,
        discarded_indices={0, 1, 2, 3},
        status_text="Left half discarded. The remaining range is now [16, 23, 38].",
        output_path=frames_dir / "frame_02.png",
    )

    create_frame(
        numbers=numbers,
        target=target,
        middle_index=5,
        status_text="Middle value is 23. Match found!",
        output_path=frames_dir / "frame_03.png",
    )

    return frames_dir


def render_binary_search_video(output_dir: Path) -> Path:
    """
    Assemble the binary-search animation frames into an MP4 video.
    """
    frames_dir = render_binary_search_demo(output_dir)
    output_path = output_dir / "binary_search_demo.mp4"

    return render_video(
        frames_dir=frames_dir,
        output_path=output_path,
        seconds_per_frame=1.5,
        fps=24,
        width=854,
        height=480,
    )


def render_binary_search_lesson(output_dir: Path) -> dict[str, Path | str]:
    """
    Bundle the motion renderer with a simple narration summary so the lesson can
    be treated like a real educational output rather than only a set of frames.
    """
    frames_dir = render_binary_search_demo(output_dir)
    video_path = render_binary_search_video(output_dir)

    narration_lines = [
        "Middle value is 12. The target 23 is greater than 12, so we search the right half.",
        "The left side is discarded because it cannot contain the target value.",
        "Middle value is 23. Match found!",
    ]

    narration_path = output_dir / "narration.txt"
    narration_path.write_text("\n".join(narration_lines), encoding="utf-8")

    return {
        "frames_dir": frames_dir,
        "video_path": video_path,
        "narration_path": narration_path,
        "narration": narration_lines,
    }


def main() -> None:
    output_dir = Path("output")

    renderer = BinarySearchRenderer()

    frames_dir = renderer.render(
        description="Show a binary search walkthrough.",
        output_dir=output_dir,
    )

    print(f"Frames created in: {frames_dir}")


if __name__ == "__main__":
    main()
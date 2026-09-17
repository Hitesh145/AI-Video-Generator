from pathlib import Path
import textwrap

from PIL import Image, ImageDraw, ImageFont

from services.text_normalizer import normalize_text
from schemas.visual import ScenePlan, VisualElement, VisualScene


WIDTH = 854
HEIGHT = 480

BACKGROUND = (248, 250, 252)
TEXT = (23, 23, 23)
MUTED_TEXT = (82, 82, 91)
LIGHT_TEXT = (255, 255, 255)
PANEL = (255, 255, 255)
PANEL_BORDER = (203, 213, 225)
ACCENT = (37, 99, 235)
ACCENT_SOFT = (219, 234, 254)
SUCCESS_SOFT = (220, 252, 231)
WARNING_SOFT = (254, 249, 195)
COMPARISON_SOFT = (240, 249, 255)


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_paths = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    for font_path in font_paths:
        path = Path(font_path)
        if path.exists():
            return ImageFont.truetype(str(path), size)

    return ImageFont.load_default()


def safe_text(value: str | None, fallback: str = "") -> str:
    return normalize_text(value, fallback=fallback)


def wrapped_lines(text: str, width: int) -> list[str]:
    clean_text = safe_text(text)
    if not clean_text:
        return []

    return textwrap.wrap(
        clean_text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    position: tuple[int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int],
    line_width: int,
    line_gap: int = 8,
    max_lines: int | None = None,
) -> int:
    x, y = position
    lines = wrapped_lines(text, line_width)
    if max_lines is not None:
        lines = lines[:max_lines]

    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        line_box = draw.textbbox((x, y), line, font=font)
        y += line_box[3] - line_box[1] + line_gap

    return y


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> str:
    clean_text = safe_text(text)
    if draw.textlength(clean_text, font=font) <= max_width:
        return clean_text

    ellipsis = "..."
    while clean_text and draw.textlength(clean_text + ellipsis, font=font) > max_width:
        clean_text = clean_text[:-1]

    return clean_text + ellipsis if clean_text else ellipsis


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


def element_label(element: VisualElement) -> str:
    return safe_text(element.label) or safe_text(element.id.replace("_", " ").title())


class GenericFrameRenderer:
    """
    Deterministic renderer for renderer-neutral ScenePlan objects.
    """

    def __init__(self, width: int = WIDTH, height: int = HEIGHT) -> None:
        self.width = width
        self.height = height
        self.title_font = get_font(30)
        self.body_font = get_font(20)
        self.small_font = get_font(16)
        self.label_font = get_font(18)

    def render_scene_plan(
        self,
        scene_plan: ScenePlan,
        output_dir: Path,
    ) -> list[Path]:
        frames_dir = output_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        frame_paths: list[Path] = []
        for scene in scene_plan.scenes:
            if self._is_animation_scene(scene):
                phase_paths = self.render_animation_scene(scene, frames_dir, len(frame_paths))
                frame_paths.extend(phase_paths)
            else:
                frame_number = len(frame_paths) + 1
                frame_path = frames_dir / f"frame_{frame_number:02d}.png"
                self.render_scene(scene, frame_path)
                frame_paths.append(frame_path)

        return frame_paths

    def _is_animation_scene(self, scene: VisualScene) -> bool:
        return safe_text(scene.visual_type).lower() == "animation"

    def render_animation_scene(
        self,
        scene: VisualScene,
        frames_dir: Path,
        start_index: int,
    ) -> list[Path]:
        phase_count = 3
        phase_paths: list[Path] = []

        for phase in range(phase_count):
            frame_number = start_index + phase + 1
            frame_path = frames_dir / f"frame_{frame_number:02d}.png"
            self.render_animation_phase(scene, frame_path, phase, phase_count)
            phase_paths.append(frame_path)

        return phase_paths

    def render_animation_phase(
        self,
        scene: VisualScene,
        output_path: Path,
        phase: int,
        phase_count: int,
    ) -> Path:
        image = Image.new("RGB", (self.width, self.height), BACKGROUND)
        draw = ImageDraw.Draw(image)

        self._draw_header(draw, scene)

        accent = ACCENT if phase == 1 else (0, 128, 120) if phase == 2 else (124, 58, 237)
        draw.rounded_rectangle(
            (38, 84, self.width - 38, 112),
            radius=8,
            fill=accent,
        )
        draw.text(
            (60, 90),
            f"Animation step {phase + 1}/{phase_count}",
            font=self.small_font,
            fill=LIGHT_TEXT,
        )

        layout_mode = self._resolve_layout_mode(scene)
        if layout_mode == "comparison":
            self._draw_comparison(draw, scene)
        elif layout_mode == "connected":
            self._draw_connected_elements(draw, scene)
        else:
            self._draw_text_scene(draw, scene)

        if phase == 0:
            draw.text((60, 370), "Initial view", font=self.body_font, fill=TEXT)
        elif phase == 1:
            draw.text((60, 370), "Highlight active step", font=self.body_font, fill=TEXT)
        else:
            draw.text((60, 370), "Result after update", font=self.body_font, fill=TEXT)

        self._draw_action_summary(draw, scene)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        return output_path

    def render_scene(self, scene: VisualScene, output_path: Path) -> Path:
        image = Image.new("RGB", (self.width, self.height), BACKGROUND)
        draw = ImageDraw.Draw(image)

        self._draw_header(draw, scene)

        layout_mode = self._resolve_layout_mode(scene)
        if layout_mode == "comparison":
            self._draw_comparison(draw, scene)
        elif layout_mode == "connected":
            self._draw_connected_elements(draw, scene)
        else:
            self._draw_text_scene(draw, scene)

        self._draw_action_summary(draw, scene)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        return output_path

    def _resolve_layout_mode(self, scene: VisualScene) -> str:
        layout = safe_text(scene.layout).lower()
        visual_type = safe_text(scene.visual_type).lower()

        if visual_type == "comparison" or any(
            token in layout
            for token in ("comparison", "side-by-side", "versus", "vs")
        ):
            return "comparison"

        if visual_type == "text" or "title card" in layout or layout == "centered text":
            return "text"

        if visual_type in {
            "diagram",
            "process",
            "animation",
            "mixed",
            "chart",
            "timeline",
            "graph",
        } or any(
            token in layout
            for token in ("flow", "process", "left-to-right", "left to right", "diagram")
        ):
            return "connected"

        return "text"

    def _draw_header(self, draw: ImageDraw.ImageDraw, scene: VisualScene) -> None:
        draw.rounded_rectangle(
            (40, 26, 160, 54),
            radius=6,
            fill=ACCENT,
            outline=ACCENT,
        )
        draw_centered_text(
            draw,
            (40, 26, 160, 54),
            safe_text(scene.visual_type).upper(),
            self.small_font,
            LIGHT_TEXT,
        )
        title = fit_text(
            draw,
            scene.section_title,
            self.title_font,
            max_width=self.width - 220,
        )
        draw.text((180, 22), title, font=self.title_font, fill=TEXT)
        draw_wrapped_text(
            draw,
            scene.purpose or scene.description,
            (40, 72),
            self.small_font,
            MUTED_TEXT,
            line_width=92,
            max_lines=2,
        )

    def _draw_text_scene(self, draw: ImageDraw.ImageDraw, scene: VisualScene) -> None:
        draw.rounded_rectangle(
            (70, 132, self.width - 70, 360),
            radius=8,
            fill=PANEL,
            outline=PANEL_BORDER,
            width=2,
        )
        draw_wrapped_text(
            draw,
            scene.description,
            (100, 162),
            self.body_font,
            TEXT,
            line_width=72,
            max_lines=7,
        )

    def _draw_connected_elements(
        self,
        draw: ImageDraw.ImageDraw,
        scene: VisualScene,
    ) -> None:
        elements = scene.elements[:6]
        boxes = self._element_boxes(len(elements))
        element_boxes = {
            element.id: box for element, box in zip(elements, boxes)
        }

        if scene.relationships:
            for relationship in scene.relationships:
                source_box = element_boxes.get(relationship.source)
                target_box = element_boxes.get(relationship.target)
                if source_box and target_box:
                    self._draw_connection(draw, source_box, target_box)
        else:
            for index in range(max(0, len(boxes) - 1)):
                self._draw_connection(draw, boxes[index], boxes[index + 1])

        highlighted_ids = self._highlighted_element_ids(scene)

        for element, box in zip(elements, boxes):
            fill = WARNING_SOFT if element.id in highlighted_ids else ACCENT_SOFT
            self._draw_element_card(draw, element, box, fill)

        if scene.relationships:
            relationship_text = "; ".join(
                relationship.description for relationship in scene.relationships[:2]
            )
            draw_wrapped_text(
                draw,
                relationship_text,
                (70, 352),
                self.small_font,
                MUTED_TEXT,
                line_width=88,
                max_lines=3,
            )

    def _draw_comparison(
        self,
        draw: ImageDraw.ImageDraw,
        scene: VisualScene,
    ) -> None:
        elements = scene.elements[:4]
        columns = [(70, 145, 405, 335), (450, 145, 785, 335)]

        for index, box in enumerate(columns):
            fill = COMPARISON_SOFT if index == 0 else SUCCESS_SOFT
            draw.rounded_rectangle(
                box,
                radius=8,
                fill=fill,
                outline=PANEL_BORDER,
                width=2,
            )

            if index < len(elements):
                element = elements[index]
                draw.text(
                    (box[0] + 22, box[1] + 22),
                    element_label(element),
                    font=self.body_font,
                    fill=TEXT,
                )
                draw_wrapped_text(
                    draw,
                    element.description,
                    (box[0] + 22, box[1] + 62),
                    self.small_font,
                    MUTED_TEXT,
                    line_width=34,
                    max_lines=5,
                )

    def _draw_action_summary(
        self,
        draw: ImageDraw.ImageDraw,
        scene: VisualScene,
    ) -> None:
        if not scene.actions:
            return

        actions = sorted(scene.actions, key=lambda item: item.order)[:2]
        action_text = " | ".join(action.description for action in actions)
        draw.rounded_rectangle(
            (40, 405, self.width - 40, 450),
            radius=8,
            fill=WARNING_SOFT,
            outline=(234, 179, 8),
            width=1,
        )
        draw.text((60, 416), "Cue:", font=self.small_font, fill=TEXT)
        draw_wrapped_text(
            draw,
            action_text,
            (112, 416),
            self.small_font,
            TEXT,
            line_width=82,
            max_lines=1,
        )

    def _highlighted_element_ids(self, scene: VisualScene) -> set[str]:
        highlighted: set[str] = set()
        for action in sorted(scene.actions, key=lambda item: item.order):
            if action.type.lower() in {"highlight", "reveal", "show", "annotate"}:
                highlighted.update(action.target)
        return highlighted

    def _element_boxes(self, count: int) -> list[tuple[int, int, int, int]]:
        if count <= 0:
            return []

        if count <= 3:
            box_width = 180
            gap = 42
            total_width = count * box_width + (count - 1) * gap
            start_x = (self.width - total_width) // 2
            return [
                (
                    start_x + index * (box_width + gap),
                    178,
                    start_x + index * (box_width + gap) + box_width,
                    305,
                )
                for index in range(count)
            ]

        box_width = 160
        box_height = 92
        positions = []
        for index in range(count):
            row = index // 3
            column = index % 3
            x = 110 + column * 230
            y = 140 + row * 116
            positions.append((x, y, x + box_width, y + box_height))
        return positions

    def _draw_element_card(
        self,
        draw: ImageDraw.ImageDraw,
        element: VisualElement,
        box: tuple[int, int, int, int],
        fill: tuple[int, int, int],
    ) -> None:
        draw.rounded_rectangle(
            box,
            radius=8,
            fill=fill,
            outline=ACCENT,
            width=2,
        )
        label = fit_text(
            draw,
            element_label(element),
            self.label_font,
            max_width=box[2] - box[0] - 24,
        )
        draw_centered_text(
            draw,
            (box[0] + 10, box[1] + 12, box[2] - 10, box[1] + 45),
            label,
            self.label_font,
            TEXT,
        )
        draw_wrapped_text(
            draw,
            element.description,
            (box[0] + 14, box[1] + 55),
            self.small_font,
            MUTED_TEXT,
            line_width=18,
            max_lines=2,
        )

    def _draw_connection(
        self,
        draw: ImageDraw.ImageDraw,
        source_box: tuple[int, int, int, int],
        target_box: tuple[int, int, int, int],
    ) -> None:
        sx1, sy1, sx2, sy2 = source_box
        tx1, ty1, tx2, ty2 = target_box

        if sx2 <= tx1:
            start = (sx2, (sy1 + sy2) // 2)
            end = (tx1, (ty1 + ty2) // 2)
        elif tx2 <= sx1:
            start = (sx1, (sy1 + sy2) // 2)
            end = (tx2, (ty1 + ty2) // 2)
        elif sy2 <= ty1:
            start = ((sx1 + sx2) // 2, sy2)
            end = ((tx1 + tx2) // 2, ty1)
        else:
            start = ((sx1 + sx2) // 2, sy1)
            end = ((tx1 + tx2) // 2, ty2)

        draw.line((start, end), fill=ACCENT, width=3)
        self._draw_arrow_head(draw, start, end)

    def _draw_arrow_head(
        self,
        draw: ImageDraw.ImageDraw,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> None:
        x, y = end
        if end[0] >= start[0]:
            points = [(x, y), (x - 10, y - 6), (x - 10, y + 6)]
        else:
            points = [(x, y), (x + 10, y - 6), (x + 10, y + 6)]
        draw.polygon(points, fill=ACCENT)

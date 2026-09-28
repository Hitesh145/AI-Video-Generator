"""Style kit shared by the array template and LLM-generated scenes.

Keep this file self-contained (manim imports only): it is copied next to
generated scene files, which cannot import the backend package.
"""

from manim import DOWN, LEFT, UP, RIGHT, Mobject, Text, VGroup, config


BACKGROUND = "#0F172A"
TEXT_COLOR = "#F8FAFC"
MUTED = "#94A3B8"
CELL = "#1E293B"
CELL_STROKE = "#64748B"
HIGHLIGHT = "#F59E0B"
SORTED = "#16A34A"
FOUND = "#22C55E"
POINTER = "#38BDF8"
ACCENT = "#818CF8"

CAPTION_SAFE_FRACTION = 0.15

config.background_color = BACKGROUND


def caption_safe_area() -> tuple[float, float]:
    """(ymin, ymax) for content; subtitles cover the bottom 15% of the frame."""
    half = config.frame_height / 2
    return -half + config.frame_height * CAPTION_SAFE_FRACTION, half


def fit_in_frame(mobject: Mobject, margin: float = 0.4) -> Mobject:
    ymin, ymax = caption_safe_area()
    xmax = config.frame_width / 2
    max_width = config.frame_width - 2 * margin
    max_height = (ymax - ymin) - 2 * margin

    if mobject.width > max_width:
        mobject.scale_to_fit_width(max_width)
    if mobject.height > max_height:
        mobject.scale_to_fit_height(max_height)

    if mobject.get_bottom()[1] < ymin + margin:
        mobject.shift(UP * (ymin + margin - mobject.get_bottom()[1]))
    if mobject.get_top()[1] > ymax - margin:
        mobject.shift(DOWN * (mobject.get_top()[1] - (ymax - margin)))
    if mobject.get_left()[0] < -xmax + margin:
        mobject.shift(RIGHT * (-xmax + margin - mobject.get_left()[0]))
    if mobject.get_right()[0] > xmax - margin:
        mobject.shift(LEFT * (mobject.get_right()[0] - (xmax - margin)))
    return mobject


def title(text: str, font_size: int = 34) -> Text:
    heading = Text(text, font_size=font_size, color=TEXT_COLOR)
    if heading.width > config.frame_width * 0.9:
        heading.scale_to_fit_width(config.frame_width * 0.9)
    return heading.to_edge(UP, buff=0.35)


def bullet_list(items: list[str], font_size: int = 28) -> VGroup:
    rows = VGroup(*[Text(f"• {item}", font_size=font_size, color=TEXT_COLOR) for item in items])
    rows.arrange(DOWN, aligned_edge=LEFT, buff=0.3)
    return fit_in_frame(rows)

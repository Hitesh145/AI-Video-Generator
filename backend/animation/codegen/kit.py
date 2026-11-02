"""Style kit shared by the array template and LLM-generated scenes.

Keep this file self-contained (manim imports only): it is copied next to
generated scene files, which cannot import the backend package.
"""

import json
import os
import re

from manim import DOWN, LEFT, UP, RIGHT, MarkupText, Mobject, Text, ThreeDScene, VGroup, VMobject, config


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


OVERLAP_SHARE = 0.10          # two texts overlap when their boxes share more than this part of the smaller box
EDGE_TOLERANCE = 0.05         # frame units
MIN_VISIBLE_OPACITY = 0.05    # fully faded text is not on screen
TOUCH_MARGIN = 0.05           # a line within this distance of a text box counts as touching it
OUTLINE_SAMPLES = 24
CONTAINS_TOLERANCE = 0.02     # a box this close to containing the text still counts as containing it


def _text_leaves(mobjects):
    """Every Text/MarkupText below the given mobjects; a text is one leaf (its glyphs are not walked)."""
    for item in mobjects:
        if isinstance(item, (Text, MarkupText)):
            yield item
        else:
            yield from _text_leaves(item.submobjects)


def _shape_leaves(mobjects):
    """Every non-text VMobject that has an outline of its own (lines, arrows, shapes); texts are skipped."""
    for item in mobjects:
        if isinstance(item, (Text, MarkupText)):
            continue
        if isinstance(item, VMobject) and item.has_points():
            yield item
        yield from _shape_leaves(item.submobjects)


def _outline_points(item):
    try:
        return [item.point_from_proportion(step / OUTLINE_SAMPLES) for step in range(OUTLINE_SAMPLES + 1)]
    except Exception:
        return list(item.get_anchors())


def _label(item) -> str:
    # Manim's own `.text` drops the spaces; `original_text` keeps what the scene wrote. Markup tags are not shown.
    raw = getattr(item, "original_text", None) or getattr(item, "text", "") or ""
    text = " ".join(re.sub(r"<[^>]+>", "", raw).split())
    return text if len(text) <= 30 else text[:29] + "..."


def layout_issues(scene) -> list[str]:
    """Plain sentences for text that overlaps other text, leaves the screen or covers the subtitle area.

    In a ThreeDScene only the text fixed in the frame is judged: positions of world objects are projected by the
    camera, so their boxes cannot be compared.
    """
    if isinstance(scene, ThreeDScene):
        fixed = {id(item) for item in (getattr(scene.camera, "fixed_in_frame_mobjects", None) or ())}
        roots = [item for item in scene.mobjects if id(item) in fixed]
    else:
        roots = list(scene.mobjects)

    leaves = [leaf for leaf in _text_leaves(roots) if leaf.get_fill_opacity() >= MIN_VISIBLE_OPACITY]
    boxes = [(leaf.get_left()[0], leaf.get_right()[0], leaf.get_bottom()[1], leaf.get_top()[1]) for leaf in leaves]
    half_width, half_height = config.frame_width / 2, config.frame_height / 2
    safe_bottom = caption_safe_area()[0]

    issues: list[str] = []
    for leaf, (left, right, bottom, top) in zip(leaves, boxes):
        if (left < -half_width - EDGE_TOLERANCE or right > half_width + EDGE_TOLERANCE
                or top > half_height + EDGE_TOLERANCE or bottom < -half_height - EDGE_TOLERANCE):
            issues.append(f"'{_label(leaf)}' leaves the screen")
        elif bottom < safe_bottom - EDGE_TOLERANCE:
            issues.append(f"'{_label(leaf)}' covers the subtitle area")

    shapes = [
        shape for shape in _shape_leaves(roots)
        if shape.get_stroke_opacity() >= MIN_VISIBLE_OPACITY or shape.get_fill_opacity() >= MIN_VISIBLE_OPACITY
    ]
    outlines = [_outline_points(shape) for shape in shapes]
    shape_boxes = [(s.get_left()[0], s.get_right()[0], s.get_bottom()[1], s.get_top()[1]) for s in shapes]
    for leaf, (left, right, bottom, top) in zip(leaves, boxes):
        inner = (left - TOUCH_MARGIN, right + TOUCH_MARGIN, bottom - TOUCH_MARGIN, top + TOUCH_MARGIN)
        for points, (s_left, s_right, s_bottom, s_top) in zip(outlines, shape_boxes):
            # a shape whose box contains the whole text (a highlight, a surrounding box) is a container, not a crossing
            if (s_left <= left + CONTAINS_TOLERANCE and s_right >= right - CONTAINS_TOLERANCE
                    and s_bottom <= bottom + CONTAINS_TOLERANCE and s_top >= top - CONTAINS_TOLERANCE):
                continue
            if any(inner[0] < point[0] < inner[1] and inner[2] < point[1] < inner[3] for point in points):
                issues.append(f"'{_label(leaf)}' is crossed by or touching a line, arrow or shape edge")
                break

    for first in range(len(leaves)):
        for second in range(first + 1, len(leaves)):
            l1, r1, b1, t1 = boxes[first]
            l2, r2, b2, t2 = boxes[second]
            width, height = min(r1, r2) - max(l1, l2), min(t1, t2) - max(b1, b2)
            if width <= 0 or height <= 0:
                continue
            smaller = min((r1 - l1) * (t1 - b1), (r2 - l2) * (t2 - b2))
            if smaller > 0 and width * height / smaller > OVERLAP_SHARE:
                issues.append(f"'{_label(leaves[first])}' and '{_label(leaves[second])}' overlap")
    return issues


def _safe_layout_issues(scene) -> list[str]:
    try:
        return layout_issues(scene)
    except Exception:       # a layout check must never break a render
        return []


BEAT_DURATIONS_ENV = "BEAT_DURATIONS"
BEAT_REPORT_ENV = "BEAT_REPORT"
_MIN_WAIT = 0.04


class BeatClock:
    """Keeps a scene on its audio schedule.

    Call end_beat() after the animations of each beat. It waits until the
    cumulative end time of that beat, so an early beat is padded and a late
    beat does not push later beats off their absolute schedule. The report is
    rewritten after every call so a scene that crashes later still leaves a
    partial report.
    """

    def __init__(self, scene, durations=None):
        if durations is None:
            raw = os.environ.get(BEAT_DURATIONS_ENV)
            if not raw:
                raise ValueError(f"{BEAT_DURATIONS_ENV} is not set; pass durations explicitly.")
            durations = json.loads(raw)

        self.scene = scene
        self.durations = [float(duration) for duration in durations]
        self.ends = []
        total = 0.0
        for duration in self.durations:
            total += duration
            self.ends.append(total)
        self.start = scene.renderer.time
        self.report = []

    def end_beat(self):
        done = len(self.report)
        if done >= len(self.durations):
            raise ValueError(
                f"end_beat() was called {done + 1} times but there are only {len(self.durations)} beats."
            )

        expected = self.start + self.ends[done]
        remaining = expected - self.scene.renderer.time
        if remaining > _MIN_WAIT:
            self.scene.wait(remaining)

        actual = self.scene.renderer.time
        self.report.append({
            "beat": done + 1,
            "start": round(self.start, 3),
            "expected_end": round(expected - self.start, 3),
            "actual_end": round(actual - self.start, 3),
            "overrun": round(max(0.0, actual - expected), 3),
            "layout": _safe_layout_issues(self.scene),
        })
        self._write_report()

    def _write_report(self):
        path = os.environ.get(BEAT_REPORT_ENV)
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.report, handle)

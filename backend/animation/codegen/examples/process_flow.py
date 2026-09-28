from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
        heading = title("Input to output")
        boxes = VGroup(*[
            VGroup(
                RoundedRectangle(
                    width=2.6, height=1.2, corner_radius=0.2,
                    color=ACCENT, fill_color=CELL, fill_opacity=1,
                ),
                Text(label, font_size=28, color=TEXT_COLOR),
            )
            for label in ["Input", "Process", "Output"]
        ]).arrange(RIGHT, buff=1.0)
        fit_in_frame(boxes)
        arrows = VGroup(*[
            Arrow(boxes[i].get_right(), boxes[i + 1].get_left(), buff=0.1, color=POINTER)
            for i in range(len(boxes) - 1)
        ])

        self.play(FadeIn(heading), run_time=0.8)
        self.play(FadeIn(boxes[0], shift=UP * 0.3), run_time=0.7)
        for i, arrow in enumerate(arrows):
            self.play(GrowArrow(arrow), FadeIn(boxes[i + 1], shift=UP * 0.3), run_time=0.8)
        self.play(boxes[1][0].animate.set_fill(HIGHLIGHT, opacity=1), run_time=0.6)
        self.wait(2.0)

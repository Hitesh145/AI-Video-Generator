from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
        heading = title("What makes an algorithm?")
        points = bullet_list(["Clear input", "Finite steps", "Correct output"])
        points.next_to(heading, DOWN, buff=0.6)
        fit_in_frame(points)

        self.play(Write(heading), run_time=1.0)
        for line in points:
            self.play(FadeIn(line, shift=RIGHT * 0.3), run_time=0.6)
        self.wait(2.0)

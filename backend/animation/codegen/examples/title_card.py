from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
        clock = BeatClock(self)
        heading = title("What makes an algorithm?")
        points = bullet_list(["Clear input", "Finite steps", "Correct output"])
        points.next_to(heading, DOWN, buff=0.6)
        fit_in_frame(points)

        # beat 1: the question appears
        self.play(Write(heading), run_time=1.0)
        clock.end_beat()

        # beat 2: first two properties
        self.play(FadeIn(points[0], shift=RIGHT * 0.3), run_time=0.6)
        self.play(FadeIn(points[1], shift=RIGHT * 0.3), run_time=0.6)
        clock.end_beat()

        # beat 3: last property
        self.play(FadeIn(points[2], shift=RIGHT * 0.3), run_time=0.6)
        clock.end_beat()

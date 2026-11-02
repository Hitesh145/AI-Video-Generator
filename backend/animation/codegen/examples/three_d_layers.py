from manim import *
from kit import *


class SectionScene(ThreeDScene):
    def construct(self):
        clock = BeatClock(self)
        self.set_camera_orientation(phi=65 * DEGREES, theta=-45 * DEGREES)

        # Text and other 2D labels must be fixed in the frame, or the 3D camera turns them with the scene.
        heading = title("A stack of layers")
        legend = VGroup(*[
            Text(label, font_size=26, color=colour)
            for label, colour in [("Layer 3: output", FOUND), ("Layer 2: hidden", POINTER), ("Layer 1: input", ACCENT)]
        ]).arrange(DOWN, aligned_edge=LEFT, buff=0.25)
        legend.to_edge(RIGHT, buff=0.6)
        fit_in_frame(legend)
        self.add_fixed_in_frame_mobjects(heading, legend)
        self.remove(heading, legend)

        layers = [
            Prism(dimensions=[3.2, 3.2, 0.3], fill_color=colour, fill_opacity=0.85, stroke_width=1).move_to([0, 0, z])
            for colour, z in [(ACCENT, 0.0), (POINTER, 1.0), (FOUND, 2.0)]
        ]
        # thin pillars show the flow from one layer to the next (Prism is reliable; thin arrows are not)
        links = [
            Prism(dimensions=[0.14, 0.14, 0.7], fill_color=TEXT_COLOR, fill_opacity=1, stroke_width=0).move_to([0, 0, z])
            for z in (0.5, 1.5)
        ]

        # beat 1: the title and the first layer
        self.play(Write(heading), run_time=0.8)
        self.play(FadeIn(layers[0]), FadeIn(legend[2]), run_time=0.8)
        clock.end_beat()

        # beat 2: the other layers are stacked on top
        self.play(FadeIn(layers[1]), FadeIn(links[0]), FadeIn(legend[1]), run_time=0.9)
        self.play(FadeIn(layers[2]), FadeIn(links[1]), FadeIn(legend[0]), run_time=0.9)
        clock.end_beat()

        # beat 3: the camera circles the whole stack
        self.begin_ambient_camera_rotation(rate=0.25)
        clock.end_beat()
        self.stop_ambient_camera_rotation()

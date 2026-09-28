import json
import os
from pathlib import Path

import numpy as np
from manim import (
    DOWN, RIGHT, UP, Arrow, FadeIn, FadeOut, Indicate, Scene, Square, Swap, Text, VGroup,
)

from animation.codegen.kit import (
    CELL, CELL_STROKE, FOUND, HIGHLIGHT, MUTED, POINTER, SORTED, TEXT_COLOR, title,
)
from animation.schemas import ArrayState
from animation.templates.array_diff import (
    AddPointer, MarkFound, RemovePointer, SwapCells, cell_style, plan_ops,
)
from animation.templates.render import ARRAY_SCENE_DATA_ENV


ROLE_COLORS = {"normal": CELL, "highlight": HIGHLIGHT, "sorted": SORTED, "found": FOUND}
MAX_ANIMATION_SECONDS = 0.8
POINTER_SPREAD = 0.55


class ArrayScene(Scene):
    def construct(self) -> None:
        data = json.loads(Path(os.environ[ARRAY_SCENE_DATA_ENV]).read_text(encoding="utf-8"))
        states = [ArrayState.model_validate(state) for state in data["states"]]
        durations = [float(duration) for duration in data["durations"]]

        self.side = min(1.0, 11.0 / len(states[0].values))
        self.cells = [self._make_cell(value) for value in states[0].values]
        row = VGroup(*self.cells).arrange(RIGHT, buff=0.12).move_to(UP * 0.6)
        self.slots = [cell.get_center().copy() for cell in self.cells]
        index_labels = VGroup(*[
            Text(str(index), font_size=18, color=MUTED).next_to(cell, DOWN, buff=0.12)
            for index, cell in enumerate(self.cells)
        ])
        self.pointer_top = index_labels.get_bottom()[1] - 0.1
        self.pointers: dict[str, VGroup] = {}

        first = states[0]
        for name in first.pointers:
            self.pointers[name] = self._make_pointer(name)
        targets = self._pointer_targets(first)
        for name, pointer in self.pointers.items():
            pointer.move_to(targets[name])

        intro = [FadeIn(title(data["title"])), FadeIn(row), FadeIn(index_labels)]
        intro += [FadeIn(pointer) for pointer in self.pointers.values()]
        self._play_step([intro, lambda: self._style_animations(first)], durations[0])

        for prev, curr, duration in zip(states, states[1:], durations[1:]):
            self._play_step(self._step_phases(prev, curr), duration)

    def _make_cell(self, value: int | str) -> VGroup:
        square = Square(
            side_length=self.side,
            color=CELL_STROKE,
            fill_color=CELL,
            fill_opacity=1,
            stroke_width=2,
        )
        label = Text(str(value), font_size=int(36 * self.side), color=TEXT_COLOR)
        if label.width > self.side * 0.85:
            label.scale_to_fit_width(self.side * 0.85)
        return VGroup(square, label)

    def _make_pointer(self, name: str) -> VGroup:
        arrow = Arrow(
            start=DOWN * 0.6,
            end=[0, 0, 0],
            buff=0,
            color=POINTER,
            stroke_width=4,
            max_tip_length_to_length_ratio=0.35,
        )
        label = Text(name, font_size=20, color=POINTER).next_to(arrow, DOWN, buff=0.06)
        return VGroup(arrow, label)

    def _pointer_targets(self, state: ArrayState) -> dict[str, np.ndarray]:
        by_index: dict[int, list[str]] = {}
        for name, index in state.pointers.items():
            by_index.setdefault(index, []).append(name)

        targets: dict[str, np.ndarray] = {}
        for index, names in by_index.items():
            for k, name in enumerate(names):
                pointer = self.pointers[name]
                x = self.slots[index][0] + (k - (len(names) - 1) / 2) * POINTER_SPREAD
                y = self.pointer_top - pointer.height / 2
                targets[name] = np.array([x, y, 0.0])
        return targets

    def _style_animations(self, state: ArrayState) -> list:
        animations = []
        for index, cell in enumerate(self.cells):
            style = cell_style(state, index)
            animations.append(
                cell[0].animate
                .set_fill(ROLE_COLORS[style.role], opacity=style.opacity)
                .set_stroke(opacity=style.opacity)
            )
            animations.append(cell[1].animate.set_opacity(style.opacity))
        return animations

    def _step_phases(self, prev: ArrayState, curr: ArrayState) -> list:
        structure: list = []
        found: list[int] = []
        new_pointers: set[str] = set()

        for op in plan_ops(prev, curr):
            if isinstance(op, SwapCells):
                structure.append(Swap(self.cells[op.i], self.cells[op.j]))
                self.cells[op.i], self.cells[op.j] = self.cells[op.j], self.cells[op.i]
            elif isinstance(op, AddPointer):
                self.pointers[op.name] = self._make_pointer(op.name)
                new_pointers.add(op.name)
            elif isinstance(op, RemovePointer):
                structure.append(FadeOut(self.pointers.pop(op.name)))
            elif isinstance(op, MarkFound):
                found.append(op.index)

        targets = self._pointer_targets(curr)
        for name, pointer in self.pointers.items():
            if name in new_pointers:
                pointer.move_to(targets[name])
                structure.append(FadeIn(pointer))
            elif not np.allclose(pointer.get_center(), targets[name]):
                structure.append(pointer.animate.move_to(targets[name]))

        # Later phases are built lazily: `.animate` snapshots a mobject when the
        # animation is created, so building them before the swaps play would
        # snap swapped cells back to their old positions.
        return [
            structure,
            lambda: self._style_animations(curr),
            lambda: [
                Indicate(self.cells[index], color=FOUND, scale_factor=1.15)
                for index in found
            ],
        ]

    def _play_step(self, phases: list, duration: float) -> None:
        phases = [phase for phase in phases if callable(phase) or phase]
        animation_seconds = min(MAX_ANIMATION_SECONDS, 0.6 * duration) if phases else 0.0
        played = 0.0
        for phase in phases:
            animations = phase() if callable(phase) else phase
            if animations:
                run_time = animation_seconds / len(phases)
                self.play(*animations, run_time=run_time)
                played += run_time
        remaining = duration - played
        if remaining > 0.01:
            self.wait(remaining)

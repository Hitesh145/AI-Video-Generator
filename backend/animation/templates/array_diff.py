"""Pure, Manim-free planning of how one ArrayState turns into the next."""

from dataclasses import dataclass
from typing import Literal

from animation.schemas import ArrayState


DIMMED_OPACITY = 0.3


@dataclass(frozen=True)
class SwapCells:
    i: int
    j: int


@dataclass(frozen=True)
class AddPointer:
    name: str
    index: int


@dataclass(frozen=True)
class MovePointer:
    name: str
    index: int


@dataclass(frozen=True)
class RemovePointer:
    name: str


@dataclass(frozen=True)
class MarkFound:
    index: int


Op = SwapCells | AddPointer | MovePointer | RemovePointer | MarkFound


def plan_ops(prev: ArrayState, curr: ArrayState) -> list[Op]:
    ops: list[Op] = []

    if curr.swapped is not None:
        ops.append(SwapCells(*curr.swapped))

    for name, index in curr.pointers.items():
        if name not in prev.pointers:
            ops.append(AddPointer(name, index))
        elif prev.pointers[name] != index:
            ops.append(MovePointer(name, index))

    for name in prev.pointers:
        if name not in curr.pointers:
            ops.append(RemovePointer(name))

    if curr.found is not None and curr.found != prev.found:
        ops.append(MarkFound(curr.found))

    return ops


@dataclass(frozen=True)
class CellStyle:
    role: Literal["normal", "highlight", "sorted", "found"]
    opacity: float


def cell_style(state: ArrayState, index: int) -> CellStyle:
    opacity = DIMMED_OPACITY if index in state.dimmed else 1.0

    if state.found == index:
        return CellStyle("found", opacity)
    if index in state.highlighted:
        return CellStyle("highlight", opacity)
    if index in state.sorted_indices:
        return CellStyle("sorted", opacity)
    return CellStyle("normal", opacity)

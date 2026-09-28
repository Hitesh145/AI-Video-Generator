from animation.schemas import ArrayState
from animation.templates.array_diff import (
    AddPointer,
    CellStyle,
    MarkFound,
    MovePointer,
    RemovePointer,
    SwapCells,
    cell_style,
    plan_ops,
)


def test_pointer_add_move_remove():
    prev = ArrayState(values=[1, 2, 3], pointers={"lo": 0, "hi": 2})
    curr = ArrayState(values=[1, 2, 3], pointers={"lo": 1, "mid": 1})

    assert plan_ops(prev, curr) == [
        MovePointer("lo", 1),
        AddPointer("mid", 1),
        RemovePointer("hi"),
    ]


def test_swap_comes_first():
    prev = ArrayState(values=[3, 1], pointers={"j": 0})
    curr = ArrayState(values=[1, 3], pointers={"j": 0}, swapped=(0, 1))

    assert plan_ops(prev, curr) == [SwapCells(0, 1)]


def test_found_only_when_newly_found():
    prev = ArrayState(values=[1, 2], found=None)
    curr = ArrayState(values=[1, 2], found=1)

    assert plan_ops(prev, curr) == [MarkFound(1)]
    assert plan_ops(curr, curr) == []


def test_cell_style_priority_and_dimming():
    state = ArrayState(
        values=[1, 2, 3, 4],
        highlighted=[1],
        sorted_indices=[1, 2],
        dimmed=[3],
        found=0,
    )

    assert cell_style(state, 0) == CellStyle("found", 1.0)
    assert cell_style(state, 1) == CellStyle("highlight", 1.0)
    assert cell_style(state, 2) == CellStyle("sorted", 1.0)
    assert cell_style(state, 3) == CellStyle("normal", 0.3)

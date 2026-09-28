import random

from animation.tracers import default_registry
from animation.tracers.base import ArrayInput, SearchInput
from animation.tracers.bubble_sort import BubbleSortTracer
from animation.tracers.insertion_sort import InsertionSortTracer
from animation.tracers.linear_search import LinearSearchTracer


def test_linear_search_found():
    steps = LinearSearchTracer().trace(SearchInput(values=[4, 7, 1], target=1))

    assert len(steps) == 4  # start, i=0, i=1, found at 2
    assert steps[-1].state.found == 2
    assert steps[-1].state.dimmed == [0, 1]


def test_linear_search_not_found():
    steps = LinearSearchTracer().trace(SearchInput(values=[4, 7], target=9))

    assert steps[-1].state.found is None
    assert steps[-1].state.dimmed == [0, 1]


def test_bubble_sort_small_example():
    steps = BubbleSortTracer().trace(ArrayInput(values=[3, 1, 2]))

    assert len(steps) == 8
    assert sum(1 for s in steps if s.state.swapped) == 2
    assert steps[-1].state.values == [1, 2, 3]
    assert steps[-1].state.sorted_indices == [0, 1, 2]


def test_bubble_sort_swap_step_shows_post_swap_values():
    steps = BubbleSortTracer().trace(ArrayInput(values=[3, 1]))
    swap = next(s for s in steps if s.state.swapped)

    assert swap.state.swapped == (0, 1)
    assert swap.state.values == [1, 3]


def test_insertion_sort_small_example():
    steps = InsertionSortTracer().trace(ArrayInput(values=[3, 1, 2]))

    assert len(steps) == 7
    assert steps[0].state.sorted_indices == [0]
    assert steps[-1].state.values == [1, 2, 3]
    assert steps[-1].state.sorted_indices == [0, 1, 2]


def test_sorts_agree_with_sorted_on_random_input():
    rng = random.Random(11)
    for tracer in (BubbleSortTracer(), InsertionSortTracer()):
        for _ in range(100):
            values = [rng.randint(-99, 999) for _ in range(rng.randint(2, 12))]
            steps = tracer.trace(ArrayInput(values=values))
            assert steps[-1].state.values == sorted(values)
            assert steps[-1].state.sorted_indices == list(range(len(values)))


def test_linear_search_agrees_with_index_on_random_input():
    rng = random.Random(3)
    for _ in range(100):
        values = [rng.randint(0, 9) for _ in range(rng.randint(2, 12))]
        target = rng.randint(0, 9)
        found = LinearSearchTracer().trace(SearchInput(values=values, target=target))[-1].state.found
        assert found == (values.index(target) if target in values else None)


def test_default_registry_has_all_milestone_tracers():
    assert sorted(default_registry().names()) == [
        "binary_search",
        "bubble_sort",
        "insertion_sort",
        "linear_search",
    ]

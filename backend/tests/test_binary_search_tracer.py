import random

import pytest
from pydantic import ValidationError

from animation.tracers.binary_search import BinarySearchInput, BinarySearchTracer


def run(values, target):
    return BinarySearchTracer().trace(BinarySearchInput(values=values, target=target))


def test_found_after_one_discard():
    steps = run([2, 5, 8, 12, 16, 23, 38], 23)

    assert len(steps) == 5  # start, compare, discard, compare, found
    assert [s.state.pointers.get("mid") for s in steps if s.state.highlighted] == [3, 5]
    assert steps[2].state.dimmed == [0, 1, 2, 3]
    assert steps[2].state.pointers == {"lo": 4, "hi": 6}
    assert steps[-1].state.found == 5


def test_not_found_ends_with_empty_range():
    steps = run([1, 3, 5], 4)

    assert len(steps) == 6
    assert steps[-1].state.found is None
    assert steps[-1].state.pointers == {}
    assert steps[-1].state.dimmed == [0, 1, 2]
    assert "not in the array" in steps[-1].event


def test_duplicates_are_allowed():
    steps = run([5, 5, 5], 5)

    assert steps[-1].state.found == 1


def test_rejects_unsorted_values():
    with pytest.raises(ValidationError):
        BinarySearchInput(values=[3, 1, 2], target=1)


@pytest.mark.parametrize("values", [[1], list(range(13))])
def test_rejects_bad_lengths(values):
    with pytest.raises(ValidationError):
        BinarySearchInput(values=values, target=1)


def test_rejects_out_of_range_values():
    with pytest.raises(ValidationError):
        BinarySearchInput(values=[1, 1000], target=1)


def test_random_inputs_agree_with_membership():
    rng = random.Random(7)
    for _ in range(200):
        values = sorted(rng.randint(-99, 999) for _ in range(rng.randint(2, 12)))
        target = rng.choice(values + [rng.randint(-99, 999)])
        steps = run(values, target)
        found = steps[-1].state.found
        if target in values:
            assert found is not None and values[found] == target
        else:
            assert found is None

from animation.tracers.base import TracerRegistry
from animation.tracers.binary_search import BinarySearchTracer
from animation.tracers.bubble_sort import BubbleSortTracer
from animation.tracers.insertion_sort import InsertionSortTracer
from animation.tracers.linear_search import LinearSearchTracer


def default_registry() -> TracerRegistry:
    return TracerRegistry([
        BinarySearchTracer(),
        LinearSearchTracer(),
        BubbleSortTracer(),
        InsertionSortTracer(),
    ])

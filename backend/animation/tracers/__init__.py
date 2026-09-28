from animation.tracers.base import TracerRegistry
from animation.tracers.binary_search import BinarySearchTracer


def default_registry() -> TracerRegistry:
    return TracerRegistry([
        BinarySearchTracer(),
    ])

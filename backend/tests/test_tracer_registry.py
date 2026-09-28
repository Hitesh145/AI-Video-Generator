import pytest

from animation.tracers import default_registry
from animation.tracers.base import TracerRegistry
from animation.tracers.binary_search import BinarySearchTracer


def test_get_unknown_returns_none():
    assert TracerRegistry().get("nope") is None


def test_duplicate_registration_fails():
    registry = TracerRegistry([BinarySearchTracer()])
    with pytest.raises(ValueError):
        registry.register(BinarySearchTracer())


def test_catalogue_describes_inputs():
    catalogue = TracerRegistry([BinarySearchTracer()]).catalogue()

    assert catalogue[0]["name"] == "binary_search"
    assert "target" in catalogue[0]["inputs_schema"]["properties"]


def test_default_registry_contains_binary_search():
    assert "binary_search" in default_registry().names()

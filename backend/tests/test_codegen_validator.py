import pytest

from animation.codegen.validator import validate_scene_code


GOOD = """
from manim import *
from kit import *
import math


class SectionScene(Scene):
    def construct(self):
        dot = Dot()
        self.play(FadeIn(dot), run_time=math.sqrt(1))
        self.wait(1)
"""


def test_accepts_good_scene():
    assert validate_scene_code(GOOD) == []


@pytest.mark.parametrize(
    "snippet",
    [
        "import os",
        "import subprocess",
        "from pathlib import Path",
        "from . import thing",
        "open('x.txt', 'w')",
        "eval('1')",
        "exec('x = 1')",
        "__import__('os')",
        "getattr(Scene, 'x')",
        "x = Scene.__subclasses__()",
        "import numpy.ctypeslib",
    ],
)
def test_rejects_dangerous_code(snippet):
    code = GOOD + "\n" + snippet + "\n"

    assert validate_scene_code(code) != []


def test_reports_syntax_errors():
    errors = validate_scene_code("class SectionScene(Scene)\n    pass")

    assert errors and errors[0].startswith("SyntaxError")


def test_requires_exactly_one_section_scene():
    assert validate_scene_code("from manim import *\nclass Other(Scene):\n    pass\n") != []
    assert validate_scene_code(GOOD + "\nclass Extra(Scene):\n    pass\n") != []

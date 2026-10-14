import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from animation.codegen import kit
from animation.codegen.kit import BEAT_DURATIONS_ENV, BEAT_REPORT_ENV, BeatClock
from animation.templates.render import render_manim_scene
from animation.timing import probe_duration


class FakeScene:
    def __init__(self, start: float = 0.0) -> None:
        self.renderer = SimpleNamespace(time=start)
        self.waits: list[float] = []

    def advance(self, seconds: float) -> None:
        self.renderer.time += seconds

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.renderer.time += seconds


def test_end_beat_waits_until_the_beat_end(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene()
    clock = BeatClock(scene, [1.0, 2.0])

    scene.advance(0.4)
    clock.end_beat()
    scene.advance(0.5)
    clock.end_beat()

    assert scene.renderer.time == pytest.approx(3.0)
    assert scene.waits == pytest.approx([0.6, 1.5])
    assert [r["overrun"] for r in clock.report] == [0.0, 0.0]


def test_overrunning_beat_is_reported_and_next_beat_recovers(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene()
    clock = BeatClock(scene, [1.0, 1.0, 1.0])

    scene.advance(1.6)          # beat 1 is 0.6 s late
    clock.end_beat()
    scene.advance(0.1)
    clock.end_beat()            # absolute end is 2.0, we are at 1.7: waits 0.3
    scene.advance(0.2)
    clock.end_beat()

    assert [r["overrun"] for r in clock.report] == pytest.approx([0.6, 0.0, 0.0])
    assert scene.renderer.time == pytest.approx(3.0)


def test_clock_is_relative_to_where_the_scene_already_is(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene(start=5.0)
    clock = BeatClock(scene, [2.0])

    clock.end_beat()

    assert scene.renderer.time == pytest.approx(7.0)
    assert clock.report[0]["expected_end"] == pytest.approx(2.0)


def test_tiny_remainders_are_not_waited(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene()
    clock = BeatClock(scene, [1.0])

    scene.advance(0.99)
    clock.end_beat()

    assert scene.waits == []


def test_extra_end_beat_raises(monkeypatch):
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    clock = BeatClock(FakeScene(), [1.0])
    clock.end_beat()

    with pytest.raises(ValueError, match="called 2 times but there are only 1 beats"):
        clock.end_beat()


def test_report_is_rewritten_after_every_call(monkeypatch, tmp_path):
    report = tmp_path / "report.json"
    monkeypatch.setenv(BEAT_REPORT_ENV, str(report))
    clock = BeatClock(FakeScene(), [1.0, 1.0])

    clock.end_beat()
    assert [r["beat"] for r in json.loads(report.read_text(encoding="utf-8"))] == [1]
    clock.end_beat()
    assert [r["beat"] for r in json.loads(report.read_text(encoding="utf-8"))] == [1, 2]


def test_durations_come_from_the_environment(monkeypatch):
    monkeypatch.setenv(BEAT_DURATIONS_ENV, json.dumps([1.5, 2.5]))
    monkeypatch.delenv(BEAT_REPORT_ENV, raising=False)
    scene = FakeScene()
    clock = BeatClock(scene)

    clock.end_beat()
    clock.end_beat()

    assert scene.renderer.time == pytest.approx(4.0)


def test_missing_durations_raise(monkeypatch):
    monkeypatch.delenv(BEAT_DURATIONS_ENV, raising=False)

    with pytest.raises(ValueError, match=BEAT_DURATIONS_ENV):
        BeatClock(FakeScene())


SCENE = """
from manim import *
from kit import *


class SectionScene(Scene):
    def construct(self):
        clock = BeatClock(self)
        self.play(FadeIn(Square()), run_time=0.5)
        clock.end_beat()
        self.play(FadeIn(Circle()), run_time=1.6)
        clock.end_beat()
        self.play(FadeIn(Triangle()), run_time=0.2)
        clock.end_beat()
"""


@pytest.mark.slow
def test_real_manim_render_follows_the_beat_clock(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    shutil.copyfile(Path(kit.__file__), work / "kit.py")
    scene_file = work / "section_scene.py"
    scene_file.write_text(SCENE, encoding="utf-8")
    report = tmp_path / "report.json"

    out = render_manim_scene(
        scene_file,
        "SectionScene",
        work,
        tmp_path / "out.mp4",
        extra_env={BEAT_DURATIONS_ENV: json.dumps([1.0, 1.0, 1.0]), BEAT_REPORT_ENV: str(report)},
        pythonpath=work,
        timeout_seconds=120,
    )

    rows = json.loads(report.read_text(encoding="utf-8"))
    assert [r["overrun"] for r in rows] == pytest.approx([0.0, 0.6, 0.0], abs=0.05)
    assert probe_duration(out) == pytest.approx(3.0, abs=0.15)

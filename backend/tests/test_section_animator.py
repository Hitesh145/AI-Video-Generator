from pathlib import Path

import pytest

from animation.narrator import NarratedSegment
from animation.router import ResolvedRoute, RoutingResult
from animation.schemas import RenderSection
from animation.section_animator import SectionAnimator, SectionRenderError
from animation.tracers import default_registry
from animation.tracers.binary_search import BinarySearchInput
from services.tts_service import SceneAudio


TRACE_SECTION = RenderSection(index=0, title="Binary search", narration="Watch it halve.")
TEXT_SECTION = RenderSection(index=1, title="Why", narration="It is fast.")


class FakeRouter:
    def __init__(self, routes, warnings=()):
        self.result = RoutingResult(list(routes), list(warnings))

    def route(self, sections):
        return self.result


class FakeNarrator:
    def narrate(self, section, steps):
        # one sentence for step 0, everything else grouped under a second sentence
        return [
            NarratedSegment("Start.", (0,)),
            NarratedSegment("Then it narrows.", tuple(range(1, len(steps)))),
        ], []


class FakeSynth:
    def synthesize_text(self, text, output_path):
        return SceneAudio(scene_id=output_path.stem, narration_text=text,
                          audio_path=str(output_path), duration_seconds=3.0)


class FakeRenderer:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def render(self, *args):
        self.calls.append(args)
        if self.fail:
            raise RuntimeError("boom")
        # fake_fit ignores the raw clip path, so any path will do
        return Path(args[3])


def fake_fit(raw, seconds, out):
    return out


def fake_audio(paths, durations, out):
    return out


def make(routes, template=None, codegen=None, slideshow=None):
    template = template or FakeRenderer()
    codegen = codegen or FakeRenderer()
    slideshow = slideshow or FakeRenderer()
    animator = SectionAnimator(
        router=FakeRouter(routes),
        narrator=FakeNarrator(),
        registry=default_registry(),
        synthesizer=FakeSynth(),
        template_renderer=template,
        codegen_renderer=codegen,
        slideshow_renderer=slideshow,
        fit_clip=fake_fit,
        build_audio=fake_audio,
    )
    return animator, template, codegen, slideshow


TRACE_ROUTE = ResolvedRoute(0, "trace", "binary_search",
                            BinarySearchInput(values=[2, 5, 8, 12, 16, 23, 38], target=23))


def test_trace_path_times_steps_from_segment_audio(tmp_path):
    animator, template, _, _ = make([TRACE_ROUTE])

    clips, warnings = animator.animate([TRACE_SECTION], tmp_path)

    clip = clips[0]
    assert clip.path_used == "trace"
    assert clip.tracer == "binary_search"
    assert clip.narration_segments == ["Start.", "Then it narrows."]
    # 5 steps: segment 1 = step 0 (3.0 s); segment 2 = step 1 narrated + 3 grouped
    # -> max(1.0, 3.0 - 3 * 0.6) + 3 * 0.6 = 3.0 s
    assert clip.segment_durations == pytest.approx([3.0, 3.0])
    title, steps, durations, _, _ = template.calls[0]
    assert len(steps) == len(durations) == 5
    assert durations == pytest.approx([3.0, 1.2, 0.6, 0.6, 0.6])
    assert warnings == []


def test_codegen_route_uses_section_audio_duration(tmp_path):
    animator, _, codegen, _ = make([ResolvedRoute(1, "codegen")])

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "codegen"
    assert codegen.calls[0][1] == 3.0
    assert clips[0].segment_durations == [3.0]


def test_template_failure_falls_back_to_codegen(tmp_path):
    animator, _, codegen, _ = make([TRACE_ROUTE], template=FakeRenderer(fail=True))

    clips, warnings = animator.animate([TRACE_SECTION], tmp_path)

    assert clips[0].path_used == "codegen"
    assert len(codegen.calls) == 1
    assert "trace animation failed" in clips[0].warnings[0]
    assert warnings == clips[0].warnings


def test_codegen_failure_falls_back_to_slideshow(tmp_path):
    animator, _, _, slideshow = make([ResolvedRoute(1, "codegen")], codegen=FakeRenderer(fail=True))

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "slideshow"
    assert slideshow.calls[0][1] == 3.0


def test_everything_failing_raises(tmp_path):
    animator, _, _, _ = make(
        [ResolvedRoute(1, "codegen")],
        codegen=FakeRenderer(fail=True),
        slideshow=FakeRenderer(fail=True),
    )

    with pytest.raises(SectionRenderError, match="Why"):
        animator.animate([TEXT_SECTION], tmp_path)


def test_router_warnings_are_returned(tmp_path):
    animator, _, _, _ = make([ResolvedRoute(1, "codegen")])
    animator.router = FakeRouter([ResolvedRoute(1, "codegen")], ["router said no"])

    _, warnings = animator.animate([TEXT_SECTION], tmp_path)

    assert warnings == ["router said no"]


def test_unreadable_codegen_clip_falls_back_to_slideshow(tmp_path):
    animator, _, _, slideshow = make([ResolvedRoute(1, "codegen")])

    def fit(raw, seconds, out):
        if raw.name == "codegen_raw.mp4":
            raise ValueError("Durations must be greater than 0.")
        return out

    animator.fit_clip = fit
    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "slideshow"
    assert len(slideshow.calls) == 1


class FailingSynth:
    def synthesize_text(self, text, output_path):
        raise RuntimeError("edge-tts network error")


def test_tts_failure_uses_silent_narration(tmp_path):
    animator, _, codegen, _ = make([ResolvedRoute(1, "codegen")])
    animator.synthesizer = FailingSynth()

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "codegen"
    assert clips[0].segment_durations[0] > 0
    assert "narration audio failed" in clips[0].warnings[0]

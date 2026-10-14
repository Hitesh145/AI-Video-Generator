from pathlib import Path

import pytest

from animation.codegen.generator import CodegenResult
from animation.narrator import NarratedSegment
from animation.router import ResolvedRoute, RoutingResult
from animation.schemas import RenderSection
from animation.section_animator import SectionAnimator, SectionRenderError
from animation.storyboard import PlannedBeat
from animation.tracers import default_registry
from animation.tracers.binary_search import BinarySearchInput
from services.tts_service import SceneAudio


TRACE_SECTION = RenderSection(index=0, title="Binary search", narration="Watch it halve.")
TEXT_SECTION = RenderSection(index=1, title="Why", narration="It is fast. It is simple.")
BEATS = [PlannedBeat("It is fast.", "a rocket"), PlannedBeat("It is simple.", "a single arrow")]


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


class FakeStoryboarder:
    def __init__(self, beats=BEATS, warnings=()):
        self.beats = list(beats)
        self.warnings = list(warnings)
        self.sections = []

    def plan(self, section):
        self.sections.append(section)
        return list(self.beats), list(self.warnings)


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


class FakeCodegen:
    def __init__(self, fail=False, warnings=()):
        self.fail = fail
        self.warnings = list(warnings)
        self.calls = []

    def render(self, section, beats, durations, work_dir, output_path, artifacts_dir):
        self.calls.append((section, beats, durations))
        if self.fail:
            raise RuntimeError("boom")
        return CodegenResult(path=output_path, warnings=list(self.warnings))


def fake_fit(raw, seconds, out):
    return out


def fake_audio(paths, durations, out):
    return out


def make(routes, template=None, codegen=None, slideshow=None, storyboarder=None):
    template = template or FakeRenderer()
    codegen = codegen or FakeCodegen()
    slideshow = slideshow or FakeRenderer()
    animator = SectionAnimator(
        router=FakeRouter(routes),
        narrator=FakeNarrator(),
        storyboarder=storyboarder or FakeStoryboarder(),
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
CODEGEN_ROUTE = ResolvedRoute(1, "codegen")


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


def test_codegen_route_plans_beats_and_passes_their_durations(tmp_path):
    storyboarder = FakeStoryboarder()
    animator, _, codegen, _ = make([CODEGEN_ROUTE], storyboarder=storyboarder)
    fits = []
    animator.fit_clip = lambda raw, seconds, out: fits.append(seconds) or out

    clips, warnings = animator.animate([TEXT_SECTION], tmp_path)

    clip = clips[0]
    assert clip.path_used == "codegen"
    assert storyboarder.sections == [TEXT_SECTION]
    section, beats, durations = codegen.calls[0]
    assert beats == BEATS
    assert durations == [3.0, 3.0]
    assert fits == [6.0]
    assert clip.narration_segments == ["It is fast.", "It is simple."]
    assert clip.segment_durations == [3.0, 3.0]
    assert warnings == []


def test_codegen_route_builds_section_audio_from_the_beat_wavs(tmp_path):
    animator, _, _, _ = make([CODEGEN_ROUTE])
    built = []
    animator.build_audio = lambda paths, durations, out: built.append((paths, durations, out)) or out

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    paths, durations, out = built[0]
    assert [p.name for p in paths] == ["beat_000.wav", "beat_001.wav"]
    assert durations == [3.0, 3.0]
    assert clips[0].audio_path == str(out)
    assert out.name == "narration.m4a"


def test_storyboard_warnings_are_reported(tmp_path):
    animator, _, _, _ = make([CODEGEN_ROUTE], storyboarder=FakeStoryboarder(warnings=["plan was plain"]))

    clips, warnings = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].warnings == ["plan was plain"]
    assert warnings == ["plan was plain"]


def test_late_render_warning_from_codegen_is_reported(tmp_path):
    animator, _, _, _ = make([CODEGEN_ROUTE], codegen=FakeCodegen(warnings=["ran late"]))

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "codegen"
    assert clips[0].warnings == ["ran late"]


def test_template_failure_falls_back_to_codegen(tmp_path):
    animator, _, codegen, _ = make([TRACE_ROUTE], template=FakeRenderer(fail=True))

    clips, warnings = animator.animate([TRACE_SECTION], tmp_path)

    assert clips[0].path_used == "codegen"
    assert len(codegen.calls) == 1
    assert "trace animation failed" in clips[0].warnings[0]
    assert warnings == clips[0].warnings


def test_codegen_failure_falls_back_to_slideshow_with_the_same_beats(tmp_path):
    animator, _, _, slideshow = make([CODEGEN_ROUTE], codegen=FakeCodegen(fail=True))

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "slideshow"
    assert slideshow.calls[0][1] == 6.0
    assert clips[0].narration_segments == ["It is fast.", "It is simple."]
    assert clips[0].segment_durations == [3.0, 3.0]
    assert "generated animation failed" in clips[0].warnings[0]


def test_everything_failing_raises(tmp_path):
    animator, _, _, _ = make(
        [CODEGEN_ROUTE],
        codegen=FakeCodegen(fail=True),
        slideshow=FakeRenderer(fail=True),
    )

    with pytest.raises(SectionRenderError, match="Why"):
        animator.animate([TEXT_SECTION], tmp_path)


def test_router_warnings_are_returned(tmp_path):
    animator, _, _, _ = make([CODEGEN_ROUTE])
    animator.router = FakeRouter([CODEGEN_ROUTE], ["router said no"])

    _, warnings = animator.animate([TEXT_SECTION], tmp_path)

    assert warnings == ["router said no"]


def test_unreadable_codegen_clip_falls_back_to_slideshow(tmp_path):
    animator, _, _, slideshow = make([CODEGEN_ROUTE])

    def fit(raw, seconds, out):
        if raw.name == "codegen_raw.mp4":
            raise ValueError("Durations must be greater than 0.")
        return out

    animator.fit_clip = fit
    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    assert clips[0].path_used == "slideshow"
    assert len(slideshow.calls) == 1


class FailsOnceSynth:
    def __init__(self, failing_text):
        self.failing_text = failing_text

    def synthesize_text(self, text, output_path):
        if text == self.failing_text:
            raise RuntimeError("edge-tts network error")
        return FakeSynth().synthesize_text(text, output_path)


def test_one_failed_beat_becomes_silence_and_keeps_the_others(tmp_path):
    animator, _, codegen, _ = make([CODEGEN_ROUTE])
    animator.synthesizer = FailsOnceSynth("It is simple.")

    clips, _ = animator.animate([TEXT_SECTION], tmp_path)

    clip = clips[0]
    assert clip.path_used == "codegen"
    assert clip.segment_durations[0] == 3.0
    assert clip.segment_durations[1] > 0
    assert len(clip.narration_segments) == 2
    assert "narration audio failed" in clip.warnings[0]
    assert codegen.calls[0][2] == clip.segment_durations


def test_audio_build_failure_in_a_codegen_section_is_a_section_error(tmp_path):
    animator, _, _, _ = make([CODEGEN_ROUTE])

    def broken(paths, durations, out):
        raise RuntimeError("ffmpeg exploded")

    animator.build_audio = broken

    with pytest.raises(SectionRenderError, match="Why.*audio.*ffmpeg exploded"):
        animator.animate([TEXT_SECTION], tmp_path)

from pathlib import Path
from typing import Callable, Protocol

from animation.codegen.generator import CodegenResult
from animation.narrator import NarratedSegment
from animation.router import ResolvedRoute, RoutingResult
from animation.schemas import PathUsed, RenderSection, SectionClip, TraceStep
from animation.storyboard import PlannedBeat
from animation.timing import concat_audio_padded, fit_clip, step_durations_for_segment
from animation.tracers.base import TracerRegistry
from services.run_context import llm_step, report_section, report_stage
from services.tts_service import SceneAudio, SilentTTSService


ClipFitter = Callable[[Path, float, Path], Path]
AudioBuilder = Callable[[list[Path], list[float], Path], Path]


class Router(Protocol):
    def route(self, sections: list[RenderSection]) -> RoutingResult:
        ...


class Narrator(Protocol):
    def narrate(self, section: RenderSection, steps: list[TraceStep]) -> tuple[list[NarratedSegment], list[str]]:
        ...


class TextSynthesizer(Protocol):
    def synthesize_text(self, text: str, output_path: Path) -> SceneAudio:
        ...


class TemplateRenderer(Protocol):
    def render(self, title: str, steps: list[TraceStep], durations: list[float], work_dir: Path, output_path: Path) -> Path:
        ...


class BeatPlanner(Protocol):
    def plan(self, section: RenderSection) -> tuple[list[PlannedBeat], list[str]]:
        ...


class CodegenSectionRenderer(Protocol):
    def render(
        self,
        section: RenderSection,
        beats: list[PlannedBeat],
        durations: list[float],
        work_dir: Path,
        output_path: Path,
        artifacts_dir: Path,
    ) -> CodegenResult:
        ...


class SlideshowSectionRenderer(Protocol):
    def render(self, section: RenderSection, duration_seconds: float, work_dir: Path, output_path: Path) -> Path:
        ...


class SectionRenderError(RuntimeError):
    pass


def _no_announce(activity: str) -> None:
    pass


class SectionAnimator:
    def __init__(
        self,
        router: Router,
        narrator: Narrator,
        storyboarder: BeatPlanner,
        registry: TracerRegistry,
        synthesizer: TextSynthesizer,
        template_renderer: TemplateRenderer,
        codegen_renderer: CodegenSectionRenderer,
        slideshow_renderer: SlideshowSectionRenderer,
        fit_clip: ClipFitter = fit_clip,
        build_audio: AudioBuilder = concat_audio_padded,
    ) -> None:
        self.router = router
        self.narrator = narrator
        self.storyboarder = storyboarder
        self.registry = registry
        self.synthesizer = synthesizer
        self.template_renderer = template_renderer
        self.codegen_renderer = codegen_renderer
        self.slideshow_renderer = slideshow_renderer
        self.fit_clip = fit_clip
        self.build_audio = build_audio

    def animate(
        self, sections: list[RenderSection], output_dir: Path, allow_trace: bool = True
    ) -> tuple[list[SectionClip], list[str]]:
        """Animate every section.

        With ``allow_trace=False`` the router is not consulted and every section uses the generated-animation path,
        which speaks the section's own sentences. The trace path would replace them with narration written by another
        model, which must not happen to a script that was checked against a paper.
        """
        if allow_trace:
            report_stage("route")
            with llm_step("router"):
                routing = self.router.route(sections)
        else:
            report_stage("route", "Using the checked script as written")
            routing = RoutingResult([ResolvedRoute(section.index, "codegen") for section in sections], [])
        warnings = list(routing.warnings)
        clips: list[SectionClip] = []
        total = len(sections)

        for number, (section, route) in enumerate(zip(sections, routing.routes), start=1):
            def announce(activity: str, number: int = number, section: RenderSection = section, path: str = route.path) -> None:
                report_section(number, total, section.title, path, activity)

            announce("starting")
            with llm_step(f"section {number}"):
                clip = self._animate_section(section, route, output_dir, announce)
            clips.append(clip)
            warnings.extend(clip.warnings)

        return clips, warnings

    def _animate_section(
        self,
        section: RenderSection,
        route: ResolvedRoute,
        output_dir: Path,
        announce: Callable[[str], None] = _no_announce,
    ) -> SectionClip:
        section_dir = output_dir / "sections" / f"section_{section.index:02d}"
        warnings: list[str] = []

        if route.path == "trace":
            try:
                return self._trace_section(section, route, section_dir, announce)
            except Exception as exc:
                warnings.append(f"Section '{section.title}': trace animation failed ({exc}); using generated animation.")

        return self._codegen_section(section, section_dir, output_dir, warnings, announce)

    def _codegen_section(
        self,
        section: RenderSection,
        section_dir: Path,
        output_dir: Path,
        warnings: list[str],
        announce: Callable[[str], None] = _no_announce,
    ) -> SectionClip:
        announce("planning beats")
        with llm_step("storyboard"):
            beats, plan_warnings = self.storyboarder.plan(section)
        warnings.extend(plan_warnings)
        announce("narrating")

        beat_paths: list[Path] = []
        durations: list[float] = []
        texts: list[str] = []
        for number, beat in enumerate(beats):
            audio = self._synthesize(
                section,
                beat.text,
                section_dir / "audio" / f"beat_{number:03d}.wav",
                warnings,
            )
            beat_paths.append(Path(audio.audio_path))
            durations.append(audio.duration_seconds)
            texts.append(audio.narration_text or beat.text)

        total = sum(durations)
        try:
            section_audio = self.build_audio(beat_paths, durations, section_dir / "narration.m4a")
        except Exception as exc:
            raise SectionRenderError(f"Section '{section.title}' audio could not be built: {exc}") from exc
        path_used: PathUsed = "codegen"
        clip_path = section_dir / "clip.mp4"
        try:
            # Fitting stays inside the try: a scene can "render" yet produce a
            # clip ffprobe cannot measure, and that must fall back, not crash.
            announce("rendering scene")
            with llm_step("codegen"):
                result = self.codegen_renderer.render(
                    section,
                    beats,
                    durations,
                    section_dir / "codegen_work",
                    section_dir / "codegen_raw.mp4",
                    output_dir / "codegen",
                )
            video = self.fit_clip(result.path, total, clip_path)
            warnings.extend(result.warnings)
        except Exception as exc:
            warnings.append(f"Section '{section.title}': generated animation failed ({exc}); using slideshow.")
            path_used = "slideshow"
            try:
                raw = self.slideshow_renderer.render(
                    section,
                    total,
                    section_dir / "slideshow_work",
                    section_dir / "slideshow_raw.mp4",
                )
                video = self.fit_clip(raw, total, clip_path)
            except Exception as slideshow_exc:
                raise SectionRenderError(
                    f"Section '{section.title}' could not be rendered: {slideshow_exc}"
                ) from slideshow_exc

        return SectionClip(
            section_index=section.index,
            title=section.title,
            video_path=str(video),
            audio_path=str(section_audio),
            narration_segments=texts,
            segment_durations=durations,
            path_used=path_used,
            warnings=warnings,
        )

    def _synthesize(self, section: RenderSection, text: str, output_path: Path, warnings: list[str]) -> SceneAudio:
        try:
            return self.synthesizer.synthesize_text(text, output_path)
        except Exception as exc:
            warnings.append(f"Section '{section.title}': narration audio failed ({exc}); using silence.")
            return SilentTTSService().synthesize_text(text, output_path)

    def _trace_section(
        self,
        section: RenderSection,
        route: ResolvedRoute,
        section_dir: Path,
        announce: Callable[[str], None] = _no_announce,
    ) -> SectionClip:
        tracer = self.registry.get(route.tracer or "")
        if tracer is None:
            raise ValueError(f"unknown tracer {route.tracer}")

        steps = tracer.trace(route.inputs)
        announce("narrating steps")
        with llm_step("narrator"):
            segments, warnings = self.narrator.narrate(section, steps)

        segment_paths: list[Path] = []
        segment_totals: list[float] = []
        step_durations: list[float] = []
        texts: list[str] = []
        for number, segment in enumerate(segments):
            audio = self._synthesize(
                section,
                segment.text,
                section_dir / "audio" / f"segment_{number:03d}.wav",
                warnings,
            )
            durations = step_durations_for_segment(audio.duration_seconds, len(segment.step_indices) - 1)
            step_durations.extend(durations)
            segment_paths.append(Path(audio.audio_path))
            segment_totals.append(sum(durations))
            texts.append(audio.narration_text or segment.text)

        section_audio = self.build_audio(segment_paths, segment_totals, section_dir / "narration.m4a")
        announce("animating algorithm trace")
        raw = self.template_renderer.render(
            section.title,
            steps,
            step_durations,
            section_dir / "template_work",
            section_dir / "template_raw.mp4",
        )
        video = self.fit_clip(raw, sum(segment_totals), section_dir / "clip.mp4")

        return SectionClip(
            section_index=section.index,
            title=section.title,
            video_path=str(video),
            audio_path=str(section_audio),
            narration_segments=texts,
            segment_durations=segment_totals,
            path_used="trace",
            tracer=tracer.name,
            warnings=warnings,
        )

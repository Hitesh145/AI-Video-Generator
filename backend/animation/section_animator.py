from pathlib import Path
from typing import Callable, Protocol

from animation.narrator import NarratedSegment
from animation.router import ResolvedRoute, RoutingResult
from animation.schemas import PathUsed, RenderSection, SectionClip, TraceStep
from animation.timing import concat_audio_padded, fit_clip, step_durations_for_segment
from animation.tracers.base import TracerRegistry
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


class CodegenSectionRenderer(Protocol):
    def render(self, section: RenderSection, target_seconds: float, work_dir: Path, output_path: Path, artifacts_dir: Path) -> Path:
        ...


class SlideshowSectionRenderer(Protocol):
    def render(self, section: RenderSection, duration_seconds: float, work_dir: Path, output_path: Path) -> Path:
        ...


class SectionRenderError(RuntimeError):
    pass


class SectionAnimator:
    def __init__(
        self,
        router: Router,
        narrator: Narrator,
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
        self.registry = registry
        self.synthesizer = synthesizer
        self.template_renderer = template_renderer
        self.codegen_renderer = codegen_renderer
        self.slideshow_renderer = slideshow_renderer
        self.fit_clip = fit_clip
        self.build_audio = build_audio

    def animate(self, sections: list[RenderSection], output_dir: Path) -> tuple[list[SectionClip], list[str]]:
        routing = self.router.route(sections)
        warnings = list(routing.warnings)
        clips: list[SectionClip] = []

        for section, route in zip(sections, routing.routes):
            clip = self._animate_section(section, route, output_dir)
            clips.append(clip)
            warnings.extend(clip.warnings)

        return clips, warnings

    def _animate_section(self, section: RenderSection, route: ResolvedRoute, output_dir: Path) -> SectionClip:
        section_dir = output_dir / "sections" / f"section_{section.index:02d}"
        warnings: list[str] = []

        if route.path == "trace":
            try:
                return self._trace_section(section, route, section_dir)
            except Exception as exc:
                warnings.append(f"Section '{section.title}': trace animation failed ({exc}); using generated animation.")

        audio = self._synthesize(section, section.narration, section_dir / "narration.wav", warnings)
        duration = audio.duration_seconds
        path_used: PathUsed = "codegen"
        clip_path = section_dir / "clip.mp4"
        try:
            # Fitting stays inside the try: a scene can "render" yet produce a
            # clip ffprobe cannot measure, and that must fall back, not crash.
            raw = self.codegen_renderer.render(
                section,
                duration,
                section_dir / "codegen_work",
                section_dir / "codegen_raw.mp4",
                output_dir / "codegen",
            )
            video = self.fit_clip(raw, duration, clip_path)
        except Exception as exc:
            warnings.append(f"Section '{section.title}': generated animation failed ({exc}); using slideshow.")
            path_used = "slideshow"
            try:
                raw = self.slideshow_renderer.render(
                    section,
                    duration,
                    section_dir / "slideshow_work",
                    section_dir / "slideshow_raw.mp4",
                )
                video = self.fit_clip(raw, duration, clip_path)
            except Exception as slideshow_exc:
                raise SectionRenderError(
                    f"Section '{section.title}' could not be rendered: {slideshow_exc}"
                ) from slideshow_exc

        return SectionClip(
            section_index=section.index,
            title=section.title,
            video_path=str(video),
            audio_path=audio.audio_path,
            narration_segments=[audio.narration_text or section.narration],
            segment_durations=[duration],
            path_used=path_used,
            warnings=warnings,
        )

    def _synthesize(self, section: RenderSection, text: str, output_path: Path, warnings: list[str]) -> SceneAudio:
        try:
            return self.synthesizer.synthesize_text(text, output_path)
        except Exception as exc:
            warnings.append(f"Section '{section.title}': narration audio failed ({exc}); using silence.")
            return SilentTTSService().synthesize_text(text, output_path)

    def _trace_section(self, section: RenderSection, route: ResolvedRoute, section_dir: Path) -> SectionClip:
        tracer = self.registry.get(route.tracer or "")
        if tracer is None:
            raise ValueError(f"unknown tracer {route.tracer}")

        steps = tracer.trace(route.inputs)
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

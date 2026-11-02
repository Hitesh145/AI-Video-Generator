import json
import re
from pathlib import Path
from collections.abc import Mapping
from typing import Callable, Protocol
from uuid import uuid4

from pydantic import BaseModel

from animation.schemas import RenderSection, SectionClip, SectionSummary, build_render_sections
from animation.timing import concat_audio_padded, concat_clips
from rendering.subtitle_renderer import write_srt_file
from rendering.video_renderer import mux_video
from schemas.demo import DemoVideoResponse
from schemas.knowledge import KnowledgeBase, KnowledgeGap
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, UserLessonRequest
from services.run_context import bind_run_directory, llm_step, report_stage


class LessonAnalyzer(Protocol):
    def analyze_lesson_request(
        self,
        request: UserLessonRequest,
    ) -> LessonRequest:
        ...


class KnowledgeAgent(Protocol):
    def create_knowledge_base(
        self,
        lesson_request: LessonRequest,
    ) -> KnowledgeBase:
        ...


class LessonPlanner(Protocol):
    def create_lesson_plan(self, lesson_request: LessonRequest) -> LessonPlan:
        ...


class ScriptWriter(Protocol):
    def create_lesson_script(
        self,
        lesson_request: LessonRequest,
        lesson_plan: LessonPlan,
        knowledge_base: KnowledgeBase | None = None,
    ) -> LessonScript:
        ...


class SectionAnimatorLike(Protocol):
    def animate(
        self,
        sections: list[RenderSection],
        output_dir: Path,
        allow_trace: bool = True,
    ) -> tuple[list[SectionClip], list[str]]:
        ...


ConcatClips = Callable[[list[Path], Path], Path]
BuildAudio = Callable[[list[Path], list[float], Path], Path]
Mux = Callable[[Path, Path, Path | None, Path | None], Path]


class DemoVideoService:
    def __init__(
        self,
        lesson_analyzer_service: LessonAnalyzer,
        lesson_planner_service: LessonPlanner,
        script_writer_service: ScriptWriter,
        section_animator: SectionAnimatorLike,
        output_root: Path = Path("output"),
        knowledge_agent_service: KnowledgeAgent | None = None,
        enable_subtitles: bool = True,
        concat_clips: ConcatClips = concat_clips,
        build_audio: BuildAudio = concat_audio_padded,
        mux: Mux = mux_video,
    ) -> None:
        self.lesson_analyzer_service = lesson_analyzer_service
        self.lesson_planner_service = lesson_planner_service
        self.script_writer_service = script_writer_service
        self.section_animator = section_animator
        self.output_root = output_root
        self.knowledge_agent_service = knowledge_agent_service
        self.enable_subtitles = enable_subtitles
        self.concat_clips = concat_clips
        self.build_audio = build_audio
        self.mux = mux

    def generate_demo_video(
        self,
        request: UserLessonRequest,
    ) -> DemoVideoResponse:
        report_stage("analyze")
        with llm_step("lesson analyzer"):
            lesson_request = self.lesson_analyzer_service.analyze_lesson_request(request)
        lesson_request = self._normalize_lesson_request_topic(request, lesson_request)

        knowledge_base = None
        qc_warnings: list[str] = []
        if self.knowledge_agent_service is not None:
            report_stage("knowledge")
            with llm_step("knowledge base"):
                knowledge_base = self.knowledge_agent_service.create_knowledge_base(
                    lesson_request
                )
            qc_warnings = self._build_qc_warnings(knowledge_base)
        else:
            report_stage("knowledge", "skipped")

        report_stage("plan")
        with llm_step("lesson planner"):
            lesson_plan = self.lesson_planner_service.create_lesson_plan(lesson_request)
        report_stage("script")
        with llm_step("script writer"):
            lesson_script = self.script_writer_service.create_lesson_script(
                lesson_request,
                lesson_plan,
                knowledge_base=knowledge_base,
            )

        return self.render_lesson(
            lesson_request, lesson_plan, lesson_script, knowledge_base=knowledge_base, qc_warnings=qc_warnings
        )

    def render_lesson(
        self,
        lesson_request: LessonRequest,
        lesson_plan: LessonPlan,
        lesson_script: LessonScript,
        knowledge_base: KnowledgeBase | None = None,
        qc_warnings: list[str] | None = None,
        extra_artifacts: Mapping[str, str] | None = None,
        allow_trace: bool = True,
    ) -> DemoVideoResponse:
        """Animate and assemble a lesson that is already written (the stages from "animate" onward).

        ``extra_artifacts`` maps a file name to text that is saved in the run folder next to the other artifacts.
        """
        qc_warnings = list(qc_warnings or [])
        sections = build_render_sections(lesson_script)
        if not sections:
            raise ValueError("Lesson script has no narration to render.")

        output_dir = self._create_output_dir(lesson_request.topic)
        bind_run_directory(output_dir)
        if allow_trace:
            clips, animation_warnings = self.section_animator.animate(sections, output_dir)
        else:
            clips, animation_warnings = self.section_animator.animate(sections, output_dir, allow_trace=False)
        qc_warnings.extend(animation_warnings)

        report_stage("assemble")
        clip_durations = [sum(clip.segment_durations) for clip in clips]
        video_only_path = self.concat_clips(
            [Path(clip.video_path) for clip in clips],
            output_dir / "lesson_video_only.mp4",
        )
        audio_path = self.build_audio(
            [Path(clip.audio_path) for clip in clips],
            clip_durations,
            output_dir / "narration.m4a",
        )

        subtitle_path: Path | None = None
        if self.enable_subtitles:
            subtitle_path = write_srt_file(
                [text for clip in clips for text in clip.narration_segments],
                [duration for clip in clips for duration in clip.segment_durations],
                output_dir / "subtitles.srt",
            )

        video_path = self.mux(
            video_only_path,
            output_dir / "lesson_demo.mp4",
            audio_path,
            subtitle_path,
        )

        summaries = [
            SectionSummary(
                title=clip.title,
                path_used=clip.path_used,
                tracer=clip.tracer,
                duration_seconds=duration,
                warnings=clip.warnings,
            )
            for clip, duration in zip(clips, clip_durations)
        ]

        self._write_json_artifacts(
            output_dir=output_dir,
            lesson_request=lesson_request,
            lesson_plan=lesson_plan,
            lesson_script=lesson_script,
            knowledge_base=knowledge_base,
            summaries=summaries,
        )
        for filename, content in (extra_artifacts or {}).items():
            (output_dir / filename).write_text(content, encoding="utf-8")

        return DemoVideoResponse(
            lesson_request=lesson_request,
            knowledge_base=knowledge_base,
            qc_warnings=qc_warnings,
            lesson_plan=lesson_plan,
            lesson_script=lesson_script,
            output_dir=str(output_dir),
            scene_durations=clip_durations,
            audio_path=str(audio_path),
            subtitle_path=str(subtitle_path) if subtitle_path else None,
            video_path=str(video_path),
            video_url=self._media_url(video_path),
            sections=summaries,
        )

    def _normalize_lesson_request_topic(
        self,
        request: UserLessonRequest,
        lesson_request: LessonRequest,
    ) -> LessonRequest:
        raw_topic = request.request.lower()

        if "photosynthesis" in raw_topic:
            lesson_request.topic = "Photosynthesis"
            return lesson_request
        if "binary search" in raw_topic or "binary-search" in raw_topic:
            lesson_request.topic = "Binary Search"
            return lesson_request
        if "sorting" in raw_topic:
            lesson_request.topic = "Sorting"
            return lesson_request

        return lesson_request

    def _build_qc_warnings(self, knowledge_base: KnowledgeBase) -> list[str]:
        warnings: list[str] = []

        for gap in knowledge_base.gaps:
            warnings.append(self._format_gap_warning(gap))

        if knowledge_base.conflicting_information:
            for conflict in knowledge_base.conflicting_information:
                warnings.append(f"Conflicting information flagged: {conflict}")

        return warnings

    def _format_gap_warning(self, gap: KnowledgeGap) -> str:
        return f"Knowledge gap: {gap.question} ({gap.reason})"

    def _media_url(self, video_path: Path) -> str | None:
        try:
            relative = Path(video_path).resolve().relative_to(self.output_root.resolve())
        except ValueError:
            return None
        return "/media/" + relative.as_posix()

    def _create_output_dir(self, topic: str) -> Path:
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower())[:60].strip("-")      # a folder name must stay short
        if not slug:
            slug = "lesson"

        output_dir = self.output_root / f"{slug}-{uuid4().hex[:8]}"
        output_dir.mkdir(parents=True, exist_ok=False)
        return output_dir

    def _write_json_artifacts(
        self,
        output_dir: Path,
        lesson_request: LessonRequest,
        lesson_plan: LessonPlan,
        lesson_script: LessonScript,
        knowledge_base: KnowledgeBase | None,
        summaries: list[SectionSummary],
    ) -> None:
        artifacts: list[tuple[str, BaseModel]] = [
            ("lesson_request.json", lesson_request),
            ("lesson_plan.json", lesson_plan),
            ("lesson_script.json", lesson_script),
        ]

        if knowledge_base is not None:
            artifacts.append(("knowledge_base.json", knowledge_base))

        for filename, artifact in artifacts:
            (output_dir / filename).write_text(
                artifact.model_dump_json(indent=2),
                encoding="utf-8",
            )

        (output_dir / "sections.json").write_text(
            json.dumps([summary.model_dump() for summary in summaries], indent=2),
            encoding="utf-8",
        )

from pathlib import Path
from typing import Callable, Protocol
from uuid import uuid4
import re

from pydantic import BaseModel

from rendering.binary_search_render import render_binary_search_demo
from rendering.subtitle_renderer import write_srt_file
from schemas.demo import DemoVideoResponse
from schemas.knowledge import KnowledgeBase, KnowledgeGap
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, UserLessonRequest
from schemas.visual import ScenePlan, VisualAction, VisualElement, VisualScene
from services.tts_service import SceneAudio, SceneTTSService, concat_scene_audio


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
    ) -> LessonScript:
        ...


class VisualPlanner(Protocol):
    def create_scene_plan(self, lesson_script: LessonScript) -> ScenePlan:
        ...


RenderFrames = Callable[[ScenePlan, Path], list[Path]]
CaptionFrames = Callable[[list[Path], ScenePlan, LessonScript, Path], list[Path]]
RenderVideo = Callable[
    [list[Path], Path, list[float], int, int, int, Path | None, Path | None],
    Path,
]


class DemoVideoService:
    def __init__(
        self,
        lesson_analyzer_service: LessonAnalyzer,
        lesson_planner_service: LessonPlanner,
        script_writer_service: ScriptWriter,
        visual_planner_service: VisualPlanner,
        render_frames: RenderFrames,
        caption_frames: CaptionFrames,
        render_video: RenderVideo,
        output_root: Path = Path("output"),
        knowledge_agent_service: KnowledgeAgent | None = None,
        scene_tts_service: SceneTTSService | None = None,
        enable_tts: bool = True,
        enable_subtitles: bool = True,
    ) -> None:
        self.lesson_analyzer_service = lesson_analyzer_service
        self.lesson_planner_service = lesson_planner_service
        self.script_writer_service = script_writer_service
        self.visual_planner_service = visual_planner_service
        self.render_frames = render_frames
        self.caption_frames = caption_frames
        self.render_video = render_video
        self.output_root = output_root
        self.knowledge_agent_service = knowledge_agent_service
        self.scene_tts_service = scene_tts_service
        self.enable_tts = enable_tts
        self.enable_subtitles = enable_subtitles

    def generate_demo_video(
        self,
        request: UserLessonRequest,
    ) -> DemoVideoResponse:
        lesson_request = self.lesson_analyzer_service.analyze_lesson_request(request)
        lesson_request = self._normalize_lesson_request_topic(request, lesson_request)

        knowledge_base = None
        qc_warnings: list[str] = []
        if self.knowledge_agent_service is not None:
            knowledge_base = self.knowledge_agent_service.create_knowledge_base(
                lesson_request
            )
            qc_warnings = self._build_qc_warnings(knowledge_base)

        lesson_plan = self.lesson_planner_service.create_lesson_plan(lesson_request)
        lesson_script = self.script_writer_service.create_lesson_script(
            lesson_request,
            lesson_plan,
        )
        visual_plan = self.visual_planner_service.create_scene_plan(lesson_script)
        animation_topic = self._get_animation_topic(lesson_request)
        if animation_topic is not None:
            visual_plan = self._build_animation_scene_plan(animation_topic, lesson_script)

        output_dir = self._create_output_dir(lesson_request.topic)
        frame_paths = self._render_visual_frames(visual_plan, output_dir)
        if not frame_paths:
            raise ValueError("Visual renderer did not produce any frames.")

        captioned_frame_paths = self.caption_frames(
            frame_paths,
            visual_plan,
            lesson_script,
            output_dir,
        )
        if not captioned_frame_paths:
            raise ValueError("Caption renderer did not produce any frames.")

        scene_durations = [scene.duration_seconds for scene in visual_plan.scenes]
        audio_path: Path | None = None
        subtitle_path: Path | None = None

        if self.enable_tts and self.scene_tts_service is not None:
            scene_audio = self.scene_tts_service.synthesize_scene_plan(
                visual_plan,
                lesson_script,
                output_dir,
            )
            scene_durations = [audio.duration_seconds for audio in scene_audio]
            audio_path = concat_scene_audio(
                scene_audio,
                output_dir / "narration.m4a",
            )

            if self.enable_subtitles:
                subtitle_path = write_srt_file(
                    [audio.narration_text for audio in scene_audio],
                    scene_durations,
                    output_dir / "subtitles.srt",
                )
        elif self.enable_subtitles:
            from rendering.caption_renderer import narration_for_scene

            subtitle_path = write_srt_file(
                [
                    narration_for_scene(scene, lesson_script)
                    for scene in visual_plan.scenes
                ],
                scene_durations,
                output_dir / "subtitles.srt",
            )

        frame_durations = self._frame_durations_for_visual_plan(
            visual_plan,
            captioned_frame_paths,
            scene_durations,
        )

        video_path = self.render_video(
            captioned_frame_paths,
            output_dir / "lesson_demo.mp4",
            frame_durations,
            30,
            854,
            480,
            audio_path,
            subtitle_path,
        )

        self._write_json_artifacts(
            output_dir=output_dir,
            lesson_request=lesson_request,
            lesson_plan=lesson_plan,
            lesson_script=lesson_script,
            visual_plan=visual_plan,
            knowledge_base=knowledge_base,
        )

        return DemoVideoResponse(
            lesson_request=lesson_request,
            knowledge_base=knowledge_base,
            qc_warnings=qc_warnings,
            lesson_plan=lesson_plan,
            lesson_script=lesson_script,
            visual_plan=visual_plan,
            output_dir=str(output_dir),
            frame_paths=[str(path) for path in frame_paths],
            captioned_frame_paths=[str(path) for path in captioned_frame_paths],
            scene_durations=scene_durations,
            audio_path=str(audio_path) if audio_path else None,
            subtitle_path=str(subtitle_path) if subtitle_path else None,
            video_path=str(video_path),
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

    def _render_visual_frames(self, visual_plan: ScenePlan, output_dir: Path) -> list[Path]:
        topic = self._detect_animation_topic_from_visual_plan(visual_plan)
        if topic == "binary_search":
            return sorted(render_binary_search_demo(output_dir).glob("frame_*.png"))
        return self.render_frames(visual_plan, output_dir)

    def _detect_animation_topic_from_visual_plan(self, visual_plan: ScenePlan) -> str | None:
        combined = " ".join(scene.section_title.lower() for scene in visual_plan.scenes)
        if "binary" in combined and "search" in combined:
            return "binary_search"
        if "sorting" in combined:
            return "sorting"
        return None

    def _frame_durations_for_visual_plan(
        self,
        visual_plan: ScenePlan,
        frame_paths: list[Path],
        scene_durations: list[float],
    ) -> list[float]:
        if len(scene_durations) == len(frame_paths):
            return scene_durations

        if len(scene_durations) != len(visual_plan.scenes):
            raise ValueError("Scene durations must match the number of scenes.")

        frame_durations: list[float] = []
        for scene, scene_duration in zip(visual_plan.scenes, scene_durations):
            frame_count = 3 if scene.visual_type.lower() == "animation" else 1
            per_frame = scene_duration / frame_count
            frame_durations.extend([per_frame] * frame_count)

        if len(frame_durations) != len(frame_paths):
            raise ValueError("Expanded frame durations must match the number of rendered frames.")

        return frame_durations

    def _get_animation_topic(self, lesson_request: LessonRequest) -> str | None:
        topic = lesson_request.topic.lower()
        if "binary search" in topic or "binary-search" in topic:
            return "binary_search"
        if "sorting" in topic:
            return "sorting"
        return None

    def _build_animation_scene_plan(
        self,
        animation_topic: str,
        lesson_script: LessonScript,
    ) -> ScenePlan:
        if animation_topic == "binary_search":
            return ScenePlan(
                scenes=[
                    VisualScene(
                        id="scene_1",
                        section_title="Binary Search",
                        narration_reference="script_section_1",
                        purpose="Show how binary search narrows the search space step by step.",
                        visual_type="animation",
                        description="Show a sorted array, highlight the middle value, and discard the half that cannot contain the target.",
                        layout="Horizontal array with a highlighted middle element and a shrinking search window.",
                        elements=[
                            VisualElement(
                                id="array",
                                type="data_structure",
                                label="Array",
                                description="The sorted list of values currently being searched.",
                                properties={"values": [2, 5, 8, 12, 16, 23, 38]},
                            ),
                            VisualElement(
                                id="target",
                                type="value",
                                label="Target",
                                description="The number we want to find.",
                                properties={"value": 23},
                            ),
                            VisualElement(
                                id="middle",
                                type="highlight",
                                label="Middle",
                                description="The current midpoint under comparison.",
                                properties={"value": 12},
                            ),
                        ],
                        actions=[
                            VisualAction(
                                order=1,
                                type="highlight",
                                target=["middle"],
                                description="Highlight the middle element being compared to the target.",
                            ),
                            VisualAction(
                                order=2,
                                type="hide",
                                target=["array"],
                                description="Discard the half of the array that cannot contain the target.",
                                parameters={"side": "left"},
                            ),
                        ],
                        duration_seconds=5.0,
                    )
                ]
            )

        return ScenePlan(
            scenes=[
                VisualScene(
                    id="scene_1",
                    section_title="Sorting",
                    narration_reference="script_section_1",
                    purpose="Show how sorting compares and swaps values to organize the list.",
                    visual_type="animation",
                    description="Show a list of values moving into sorted order by comparing neighboring items.",
                    layout="Horizontal list with a highlighted comparison pair and a moving sorted segment.",
                    elements=[
                        VisualElement(
                            id="values",
                            type="data_structure",
                            label="Values",
                            description="The unsorted list of numbers.",
                            properties={"values": [5, 2, 9, 1, 7]},
                        ),
                        VisualElement(
                            id="pair",
                            type="highlight",
                            label="Compare Pair",
                            description="The current adjacent values being compared.",
                            properties={"values": [2, 5]},
                        ),
                    ],
                    actions=[
                        VisualAction(
                            order=1,
                            type="highlight",
                            target=["pair"],
                            description="Highlight the adjacent values currently being compared.",
                        ),
                        VisualAction(
                            order=2,
                            type="show",
                            target=["values"],
                            description="Reveal the final sorted order after the comparison.",
                        ),
                    ],
                    duration_seconds=5.0,
                )
            ]
        )

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

    def _create_output_dir(self, topic: str) -> Path:
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
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
        visual_plan: ScenePlan,
        knowledge_base: KnowledgeBase | None,
    ) -> None:
        artifacts: list[tuple[str, BaseModel]] = [
            ("lesson_request.json", lesson_request),
            ("lesson_plan.json", lesson_plan),
            ("lesson_script.json", lesson_script),
            ("visual_plan.json", visual_plan),
        ]

        if knowledge_base is not None:
            artifacts.append(("knowledge_base.json", knowledge_base))

        for filename, artifact in artifacts:
            (output_dir / filename).write_text(
                artifact.model_dump_json(indent=2),
                encoding="utf-8",
            )

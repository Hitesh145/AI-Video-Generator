from pydantic import BaseModel, Field

from schemas.knowledge import KnowledgeBase
from schemas.lesson import LessonPlan, LessonRequest, LessonScript
from schemas.visual import ScenePlan


class DemoVideoResponse(BaseModel):
    lesson_request: LessonRequest = Field(
        description="Structured interpretation of the user's lesson request."
    )
    knowledge_base: KnowledgeBase | None = Field(
        default=None,
        description="Educational knowledge base used for QC and grounding.",
    )
    qc_warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking educational quality warnings for the demo run.",
    )
    lesson_plan: LessonPlan = Field(
        description="Generated teaching plan for the lesson."
    )
    lesson_script: LessonScript = Field(
        description="Generated narration script for the lesson."
    )
    visual_plan: ScenePlan = Field(
        description="Generic visual scene plan used by the renderer."
    )
    output_dir: str = Field(
        description="Directory containing generated artifacts for this demo run."
    )
    frame_paths: list[str] = Field(
        description="Raw PNG frame paths rendered from the visual scene plan."
    )
    captioned_frame_paths: list[str] = Field(
        description="PNG frame paths with narration captions overlaid."
    )
    scene_durations: list[float] = Field(
        default_factory=list,
        description="Final per-scene durations used for video timing.",
    )
    audio_path: str | None = Field(
        default=None,
        description="Combined narration audio path when TTS is enabled.",
    )
    subtitle_path: str | None = Field(
        default=None,
        description="Generated SRT subtitle file path when subtitles are enabled.",
    )
    video_path: str = Field(
        description="MP4 video path generated from the rendered frames."
    )

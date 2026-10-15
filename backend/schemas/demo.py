from pydantic import BaseModel, Field

from animation.schemas import SectionSummary
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
    visual_plan: ScenePlan | None = Field(
        default=None,
        description="Legacy slideshow scene plan; empty for animated runs.",
    )
    output_dir: str = Field(
        description="Directory containing generated artifacts for this demo run."
    )
    frame_paths: list[str] = Field(
        default_factory=list,
        description="Legacy raw PNG frame paths; empty for animated runs.",
    )
    captioned_frame_paths: list[str] = Field(
        default_factory=list,
        description="Legacy captioned PNG frame paths; empty for animated runs.",
    )
    scene_durations: list[float] = Field(
        default_factory=list,
        description="Final per-section durations used for video timing.",
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
    video_url: str | None = Field(
        default=None,
        description="URL path under /media where the finished MP4 is served.",
    )
    sections: list[SectionSummary] = Field(
        default_factory=list,
        description="How each section of the video was animated.",
    )

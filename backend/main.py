from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from pathlib import Path

from rendering.caption_renderer import apply_script_captions
from rendering.render_pipeline import render_scene_plan_frames
from rendering.video_renderer import render_video_from_frames
from schemas.demo import DemoVideoResponse
from schemas.lesson import (
    LessonPlan,
    LessonRequest,
    LessonScript,
    LessonScriptRequest,
    UserLessonRequest,
)
from schemas.knowledge import KnowledgeBase
from schemas.visual import ScenePlan
from services.llm_service import LLMService
from services.demo_video_service import DemoVideoService
from services.knowledge_agent_service import KnowledgeAgentService
from services.lesson_analyzer_service import LessonAnalyzerService
from services.lesson_planner_service import LessonPlannerService
from services.script_writer_service import ScriptWriterService
from services.tts_service import EdgeTTSService, SceneTTSService, SilentTTSService
from services.visual_planner_service import VisualPlannerService


def render_demo_video(
    frame_paths: list[Path],
    output_path: Path,
    durations: list[float],
    fps: int,
    width: int,
    height: int,
    audio_path: Path | None = None,
    subtitle_path: Path | None = None,
) -> Path:
    return render_video_from_frames(
        frame_paths=frame_paths,
        output_path=output_path,
        durations=durations,
        fps=fps,
        width=width,
        height=height,
        audio_path=audio_path,
        subtitle_path=subtitle_path,
    )


def build_scene_tts_service() -> SceneTTSService:
    try:
        import edge_tts  # noqa: F401

        return SceneTTSService(EdgeTTSService())
    except ImportError:
        return SceneTTSService(SilentTTSService())


app = FastAPI()
output_root = Path(__file__).parent / "output"
output_root.mkdir(parents=True, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.mount("/media", StaticFiles(directory=output_root), name="generated-media")

llm_service = LLMService()
lesson_analyzer_service = LessonAnalyzerService(llm_service)
knowledge_agent_service = KnowledgeAgentService(llm_service)
lesson_planner_service = LessonPlannerService(llm_service)
script_writer_service = ScriptWriterService(llm_service)
visual_planner_service = VisualPlannerService(llm_service)
demo_video_service = DemoVideoService(
    lesson_analyzer_service=lesson_analyzer_service,
    lesson_planner_service=lesson_planner_service,
    script_writer_service=script_writer_service,
    visual_planner_service=visual_planner_service,
    render_frames=render_scene_plan_frames,
    caption_frames=apply_script_captions,
    render_video=render_demo_video,
    knowledge_agent_service=knowledge_agent_service,
    scene_tts_service=build_scene_tts_service(),
)


@app.get("/")
def root():
    return {"message": "EduGen AI backend is running"}


@app.get("/videos")
def list_generated_videos() -> list[dict[str, str | int]]:
    videos: list[dict[str, str | int]] = []
    for video_path in output_root.rglob("*.mp4"):
        if not video_path.is_file() or video_path.name != "lesson_demo.mp4":
            continue

        relative_path = video_path.relative_to(output_root).as_posix()
        parent_name = video_path.parent.name.replace("-", " ").replace("_", " ")
        title = parent_name.title() if parent_name else video_path.stem.replace("_", " ").title()
        videos.append(
            {
                "id": relative_path,
                "title": title,
                "filename": video_path.name,
                "url": f"/media/{relative_path}",
                "created_at": video_path.stat().st_mtime_ns,
                "size_bytes": video_path.stat().st_size,
            }
        )

    return sorted(videos, key=lambda video: int(video["created_at"]), reverse=True)


@app.post("/lesson/analyze", response_model=LessonRequest)
def analyze_lesson(request: UserLessonRequest) -> LessonRequest:
    return lesson_analyzer_service.analyze_lesson_request(request)


@app.post("/lesson/knowledge", response_model=KnowledgeBase)
def create_knowledge_base(lesson_request: LessonRequest) -> KnowledgeBase:
    return knowledge_agent_service.create_knowledge_base(lesson_request)


@app.post("/lesson/plan", response_model=LessonPlan)
def create_lesson_plan(lesson_request: LessonRequest) -> LessonPlan:
    return lesson_planner_service.create_lesson_plan(lesson_request)


@app.post("/lesson/script", response_model=LessonScript)
def create_lesson_script(request: LessonScriptRequest) -> LessonScript:
    return script_writer_service.create_lesson_script(
        request.lesson_request,
        request.lesson_plan,
    )


@app.post("/lesson/visual-plan", response_model=ScenePlan)
def create_visual_plan(script: LessonScript) -> ScenePlan:
    return visual_planner_service.create_scene_plan(script)


@app.post("/lesson/generate-demo-video", response_model=DemoVideoResponse)
def generate_demo_video(request: UserLessonRequest) -> DemoVideoResponse:
    return demo_video_service.generate_demo_video(request)

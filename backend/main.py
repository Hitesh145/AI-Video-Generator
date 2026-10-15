from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path

from animation.codegen.generator import CodegenRenderer
from animation.narrator import StepNarrator
from animation.router import AnimationRouter
from animation.section_animator import SectionAnimator
from animation.slideshow import SlideshowRenderer
from animation.storyboard import Storyboarder
from animation.templates.render import ArrayTemplateRenderer
from animation.tracers import default_registry
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
from services.job_service import JobService
from services.jobs_router import create_jobs_router
from services.llm_recorder import RecordingLLM
from services.llm_service import LLMService
from services.media_response import create_media_router
from services.video_library import list_videos
from services.demo_video_service import DemoVideoService
from services.knowledge_agent_service import KnowledgeAgentService
from services.lesson_analyzer_service import LessonAnalyzerService
from services.lesson_planner_service import LessonPlannerService
from services.script_writer_service import ScriptWriterService
from services.tts_service import EdgeTTSService, SilentTTSService
from services.visual_planner_service import VisualPlannerService


def build_tts_synthesizer() -> EdgeTTSService | SilentTTSService:
    try:
        import edge_tts  # noqa: F401

        return EdgeTTSService()
    except ImportError:
        return SilentTTSService()


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
app.include_router(create_media_router(output_root))

llm_service = RecordingLLM(LLMService())
lesson_analyzer_service = LessonAnalyzerService(llm_service)
knowledge_agent_service = KnowledgeAgentService(llm_service)
lesson_planner_service = LessonPlannerService(llm_service)
script_writer_service = ScriptWriterService(llm_service)
visual_planner_service = VisualPlannerService(llm_service)
tracer_registry = default_registry()
section_animator = SectionAnimator(
    router=AnimationRouter(llm_service, tracer_registry),
    narrator=StepNarrator(llm_service),
    storyboarder=Storyboarder(llm_service),
    registry=tracer_registry,
    synthesizer=build_tts_synthesizer(),
    template_renderer=ArrayTemplateRenderer(),
    codegen_renderer=CodegenRenderer(llm_service),
    slideshow_renderer=SlideshowRenderer(),
)
demo_video_service = DemoVideoService(
    lesson_analyzer_service=lesson_analyzer_service,
    lesson_planner_service=lesson_planner_service,
    script_writer_service=script_writer_service,
    section_animator=section_animator,
    output_root=output_root,
    knowledge_agent_service=knowledge_agent_service,
)
job_service = JobService(demo_video_service.generate_demo_video, output_root)
app.include_router(create_jobs_router(job_service))


@app.get("/")
def root():
    return {"message": "EduGen AI backend is running"}


@app.get("/videos")
def list_generated_videos() -> list[dict[str, str | int]]:
    return list_videos(output_root)


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
    return job_service.run_blocking(request)

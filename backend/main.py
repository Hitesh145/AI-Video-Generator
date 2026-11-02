import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path

from accounts.origin import add_origin_check
from accounts.router import SESSION_COOKIE, create_auth_router, create_current_user_dependency
from accounts.service import AccountService, UserInfo
from accounts.videos import VideoRepository
from animation.codegen.generator import CodegenRenderer
from papers.ingestor import PaperIngestor
from papers.limits import MULTIPART_OVERHEAD_BYTES, UploadSizeLimitMiddleware
from papers.repository import PaperRepository
from papers.router import create_papers_router
from papers.videos_router import create_paper_videos_router
from papers.service import DEFAULT_MAX_UPLOAD_BYTES, PaperService
from animation.narrator import StepNarrator
from animation.router import AnimationRouter
from animation.section_animator import SectionAnimator
from animation.slideshow import SlideshowRenderer
from animation.storyboard import Storyboarder
from animation.templates.render import ArrayTemplateRenderer
from animation.tracers import default_registry
from rag.database import build_session_factory
from rag.pg_repository import PostgresRAGRepository
from rag.storage_service import RAGStorageService
from retrieval.search import build_paper_searcher
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
from services.claim_checker import ClaimChecker
from services.demo_video_service import DemoVideoService
from services.grounded_lesson_service import GroundedLessonService
from services.paper_video_service import PaperVideoService
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

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]
add_origin_check(app, ALLOWED_ORIGINS)

session_factory = build_session_factory()
account_service = AccountService(session_factory)
video_repository = VideoRepository(session_factory)
current_user = create_current_user_dependency(account_service)
app.include_router(
    create_auth_router(
        account_service,
        cookie_secure=os.getenv("AUTH_COOKIE_SECURE", "").lower() in ("1", "true"),
    )
)


def authorize_media(request: Request, relative_path: str) -> bool:
    """A media file is served only to the user who owns its run folder."""
    user = account_service.user_for_token(request.cookies.get(SESSION_COOKIE, ""))
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return video_repository.owner_of_run(relative_path.split("/")[0]) == user.user_id


app.include_router(create_media_router(output_root, authorize=authorize_media))

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
job_service = JobService(
    demo_video_service.generate_demo_video,
    output_root,
    on_complete=lambda user_id, response: video_repository.record(
        user_id, Path(response.output_dir).name, response.lesson_plan.title
    ),
)
app.include_router(create_jobs_router(job_service, current_user))

max_paper_upload_bytes = int(float(os.getenv("MAX_PAPER_UPLOAD_MB", DEFAULT_MAX_UPLOAD_BYTES // (1024 * 1024))) * 1024 * 1024)
rag_repository = PostgresRAGRepository(session_factory)
rag_storage = RAGStorageService(rag_repository)
paper_service = PaperService(
    PaperRepository(session_factory),
    PaperIngestor(rag_storage),
    upload_dir=Path(__file__).parent / "data" / "uploads",
    max_upload_bytes=max_paper_upload_bytes,
    max_concurrent=int(os.getenv("MAX_CONCURRENT_INGESTIONS", "1")),
)
app.include_router(create_papers_router(paper_service, current_user))
paper_video_service = PaperVideoService(
    papers=paper_service,
    searcher=build_paper_searcher(rag_storage, rag_repository),
    grounded=GroundedLessonService(llm_service),
    demo=demo_video_service,
    jobs=job_service,
    videos=video_repository,
    output_root=output_root,
    checker=ClaimChecker(llm_service),
)
app.include_router(create_paper_videos_router(paper_video_service, current_user))
app.add_middleware(
    UploadSizeLimitMiddleware,
    max_body_bytes=max_paper_upload_bytes + MULTIPART_OVERHEAD_BYTES,
    message=f"The file is larger than the {max_paper_upload_bytes // (1024 * 1024)} MB limit",
)


# Starlette puts the middleware added LAST outermost. CORS goes last so that refusals from the
# origin check and the size limit still carry CORS headers and the browser can show their message.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def fail_papers_interrupted_by_a_restart() -> None:
    # Reading runs on in-process threads, so anything unfinished when the server stopped is lost.
    paper_service.fail_interrupted()


@app.get("/")
def root():
    return {"message": "EduGen AI backend is running"}


@app.get("/videos")
def list_generated_videos(user: UserInfo = Depends(current_user)) -> list[dict[str, str | int]]:
    run_dirs = {record.run_dir for record in video_repository.list_for_user(user.user_id)}
    return list_videos(output_root, run_dirs=run_dirs)


@app.post("/lesson/analyze", response_model=LessonRequest)
def analyze_lesson(request: UserLessonRequest, user: UserInfo = Depends(current_user)) -> LessonRequest:
    return lesson_analyzer_service.analyze_lesson_request(request)


@app.post("/lesson/knowledge", response_model=KnowledgeBase)
def create_knowledge_base(lesson_request: LessonRequest, user: UserInfo = Depends(current_user)) -> KnowledgeBase:
    return knowledge_agent_service.create_knowledge_base(lesson_request)


@app.post("/lesson/plan", response_model=LessonPlan)
def create_lesson_plan(lesson_request: LessonRequest, user: UserInfo = Depends(current_user)) -> LessonPlan:
    return lesson_planner_service.create_lesson_plan(lesson_request)


@app.post("/lesson/script", response_model=LessonScript)
def create_lesson_script(request: LessonScriptRequest, user: UserInfo = Depends(current_user)) -> LessonScript:
    return script_writer_service.create_lesson_script(
        request.lesson_request,
        request.lesson_plan,
    )


@app.post("/lesson/visual-plan", response_model=ScenePlan)
def create_visual_plan(script: LessonScript, user: UserInfo = Depends(current_user)) -> ScenePlan:
    return visual_planner_service.create_scene_plan(script)


@app.post("/lesson/generate-demo-video", response_model=DemoVideoResponse)
def generate_demo_video(request: UserLessonRequest, user: UserInfo = Depends(current_user)) -> DemoVideoResponse:
    return job_service.run_blocking(request, user.user_id)

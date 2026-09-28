import pytest

from animation.codegen.generator import EXAMPLES_DIR, CodegenRenderer
from animation.narrator import StepNarrator
from animation.router import AnimationRouter
from animation.section_animator import SectionAnimator
from animation.slideshow import SlideshowRenderer
from animation.templates.render import ArrayTemplateRenderer
from animation.timing import probe_duration
from animation.tracers import default_registry
from fakes import FakeLLM
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, ScriptSection, UserLessonRequest
from services.demo_video_service import DemoVideoService
from services.tts_service import FakeTTSService


class Analyzer:
    def analyze_lesson_request(self, request):
        return LessonRequest(topic="Binary Search", audience="beginner", goal="understand it",
                             duration_minutes=1, teaching_depth="introductory")


class Planner:
    def create_lesson_plan(self, lesson_request):
        return LessonPlan(title="Binary Search", learning_objectives=["halve"], sections=["How"])


class Writer:
    def create_lesson_script(self, lesson_request, lesson_plan):
        return LessonScript(
            introduction="Let's find a number fast.",
            sections=[ScriptSection(section_title="How binary search works",
                                    narration="We look for 23 in 2, 5, 8, 12, 16, 23, 38.")],
            conclusion="Halving makes it quick.",
        )


@pytest.mark.slow
def test_full_lesson_renders_with_mixed_paths(tmp_path):
    example = (EXAMPLES_DIR / "title_card.py").read_text(encoding="utf-8")
    llm = FakeLLM([
        {"routes": [
            {"section_index": 0, "path": "codegen"},
            {"section_index": 1, "path": "trace", "tracer": "binary_search",
             "values": [2, 5, 8, 12, 16, 23, 38], "target": 23},
            {"section_index": 2, "path": "codegen"},
        ]},
        {"code": example},                                   # intro codegen
        {"sentences": ["a", "b", "c", "d", "e"],             # binary search narration (5 steps)
         "group_with_previous": [False] * 5},
        {"code": example},                                   # conclusion codegen
    ])
    registry = default_registry()
    animator = SectionAnimator(
        router=AnimationRouter(llm, registry),
        narrator=StepNarrator(llm),
        registry=registry,
        synthesizer=FakeTTSService(),
        template_renderer=ArrayTemplateRenderer(),
        codegen_renderer=CodegenRenderer(llm),
        slideshow_renderer=SlideshowRenderer(),
    )
    service = DemoVideoService(
        lesson_analyzer_service=Analyzer(),
        lesson_planner_service=Planner(),
        script_writer_service=Writer(),
        section_animator=animator,
        output_root=tmp_path,
    )

    response = service.generate_demo_video(UserLessonRequest(request="Explain binary search"))

    assert [s.path_used for s in response.sections] == ["codegen", "trace", "codegen"]
    assert response.qc_warnings == []
    assert probe_duration(response.video_path) == pytest.approx(sum(response.scene_durations), abs=0.5)

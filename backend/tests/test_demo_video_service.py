import json
from pathlib import Path

from animation.schemas import SectionClip
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, ScriptSection, UserLessonRequest
from services.demo_video_service import DemoVideoService
from services.llm_recorder import LLMCallRecorder
from services.run_context import RunContext, run_scope


class Analyzer:
    def analyze_lesson_request(self, request):
        return LessonRequest(topic="Binary Search", audience="beginner", goal="understand it",
                             duration_minutes=2, teaching_depth="introductory")


class Planner:
    def create_lesson_plan(self, lesson_request):
        return LessonPlan(title="Binary Search", learning_objectives=["halve"], sections=["How"])


class Writer:
    def create_lesson_script(self, lesson_request, lesson_plan, knowledge_base=None):
        return LessonScript(introduction="Hi.",
                            sections=[ScriptSection(section_title="How", narration="Halve it.")],
                            conclusion="Bye.")


class Animator:
    def __init__(self):
        self.sections = None

    def animate(self, sections, output_dir, allow_trace=True):
        self.allow_trace = allow_trace
        self.sections = sections
        clips = [
            SectionClip(section_index=s.index, title=s.title, video_path=f"v{s.index}.mp4",
                        audio_path=f"a{s.index}.m4a", narration_segments=[s.narration, "extra"],
                        segment_durations=[1.0, 2.0], path_used="trace" if s.index == 1 else "codegen",
                        tracer="binary_search" if s.index == 1 else None,
                        warnings=["w"] if s.index == 2 else [])
            for s in sections
        ]
        return clips, ["router warning", "w"]


def test_generates_video_from_section_clips(tmp_path):
    calls = {}
    animator = Animator()

    def concat_clips(paths, out):
        calls["clips"] = paths
        return out

    def build_audio(paths, durations, out):
        calls["audio"] = (paths, durations)
        return out

    def mux(video, out, audio, subtitles):
        calls["mux"] = (video, audio, subtitles)
        out.write_bytes(b"mp4")
        return out

    service = DemoVideoService(
        lesson_analyzer_service=Analyzer(),
        lesson_planner_service=Planner(),
        script_writer_service=Writer(),
        section_animator=animator,
        output_root=tmp_path,
        concat_clips=concat_clips,
        build_audio=build_audio,
        mux=mux,
    )

    response = service.generate_demo_video(UserLessonRequest(request="Explain binary search"))

    assert [s.title for s in animator.sections] == ["Introduction", "How", "Conclusion"]
    assert calls["clips"] == [Path("v0.mp4"), Path("v1.mp4"), Path("v2.mp4")]
    assert calls["audio"][1] == [3.0, 3.0, 3.0]
    assert response.scene_durations == [3.0, 3.0, 3.0]
    assert [s.path_used for s in response.sections] == ["codegen", "trace", "codegen"]
    assert response.sections[1].tracer == "binary_search"
    assert response.sections[2].warnings == ["w"]
    assert "router warning" in response.qc_warnings
    assert response.visual_plan is None
    srt = Path(response.subtitle_path).read_text(encoding="utf-8")
    assert "Halve it." in srt and "extra" in srt
    assert (Path(response.output_dir) / "sections.json").exists()
    assert response.video_path.endswith("lesson_demo.mp4")


class CapturingProgress:
    def __init__(self):
        self.stages = []

    def stage(self, key, detail=None):
        self.stages.append((key, detail))

    def section(self, number, total, title, path, activity):
        pass


def _mux(video, out, audio, subtitles):
    out.write_bytes(b"mp4")
    return out


def _service(tmp_path, animator=None):
    return DemoVideoService(
        lesson_analyzer_service=Analyzer(),
        lesson_planner_service=Planner(),
        script_writer_service=Writer(),
        section_animator=animator or Animator(),
        output_root=tmp_path,
        concat_clips=lambda paths, out: out,
        build_audio=lambda paths, durations, out: out,
        mux=_mux,
    )


def test_reports_the_real_stages_in_order_and_binds_the_run_folder(tmp_path):
    progress = CapturingProgress()
    recorder = LLMCallRecorder("Explain binary search")

    with run_scope(RunContext(recorder, progress)):
        response = _service(tmp_path).generate_demo_video(UserLessonRequest(request="Explain binary search"))

    assert progress.stages == [
        ("analyze", None),
        ("knowledge", "skipped"),
        ("plan", None),
        ("script", None),
        ("assemble", None),
    ]
    assert recorder.directory == Path(response.output_dir)
    assert (Path(response.output_dir) / "llm_calls.json").exists()


def test_response_carries_a_media_url_relative_to_the_output_root(tmp_path):
    response = _service(tmp_path).generate_demo_video(UserLessonRequest(request="Explain binary search"))

    folder = Path(response.output_dir).name
    assert response.video_url == f"/media/{folder}/lesson_demo.mp4"


def test_service_still_works_without_a_run_context(tmp_path):
    response = _service(tmp_path).generate_demo_video(UserLessonRequest(request="Explain binary search"))

    assert response.video_path.endswith("lesson_demo.mp4")
    assert not (Path(response.output_dir) / "llm_calls.json").exists()


class ExplodingStage:
    def __getattr__(self, name):
        raise AssertionError(f"render_lesson must not call {name}")


def test_render_lesson_writes_extra_artifacts_and_passes_warnings_through(tmp_path):
    service = DemoVideoService(
        lesson_analyzer_service=ExplodingStage(),
        lesson_planner_service=ExplodingStage(),
        script_writer_service=ExplodingStage(),
        section_animator=Animator(),
        output_root=tmp_path,
        concat_clips=lambda paths, out: out,
        build_audio=lambda paths, durations, out: out,
        mux=_mux,
    )
    request = LessonRequest(topic="The encoder", audience="a learner", goal="understand",
                            duration_minutes=2, teaching_depth="introductory")
    plan = LessonPlan(title="The encoder", learning_objectives=["x"], sections=["How"])
    script = LessonScript(introduction="Hi.", sections=[ScriptSection(section_title="How", narration="Halve it.")],
                          conclusion="Bye.")

    response = service.render_lesson(
        request, plan, script, qc_warnings=["Not yet checked."], extra_artifacts={"citations.json": '{"How": ["P1"]}'}
    )

    run_dir = Path(response.output_dir)
    assert run_dir.parent == tmp_path and run_dir.name.startswith("the-encoder-")
    assert (run_dir / "citations.json").read_text(encoding="utf-8") == '{"How": ["P1"]}'
    assert "Not yet checked." in response.qc_warnings and "router warning" in response.qc_warnings
    assert response.lesson_plan.title == "The encoder"


def test_a_very_long_topic_still_gets_a_valid_run_folder_name(tmp_path):
    service = DemoVideoService(
        lesson_analyzer_service=ExplodingStage(), lesson_planner_service=ExplodingStage(),
        script_writer_service=ExplodingStage(), section_animator=Animator(), output_root=tmp_path,
        concat_clips=lambda paths, out: out, build_audio=lambda paths, durations, out: out, mux=_mux,
    )
    request = LessonRequest(topic="Explain the method " * 30, audience="a learner", goal="understand",
                            duration_minutes=2, teaching_depth="introductory")
    plan = LessonPlan(title="T", learning_objectives=["x"], sections=["How"])
    script = LessonScript(introduction="Hi.", sections=[ScriptSection(section_title="How", narration="n")], conclusion="Bye.")

    response = service.render_lesson(request, plan, script)

    assert len(Path(response.output_dir).name) <= 80


def test_render_lesson_can_forbid_the_trace_path(tmp_path):
    animator = Animator()
    service = DemoVideoService(
        lesson_analyzer_service=ExplodingStage(), lesson_planner_service=ExplodingStage(),
        script_writer_service=ExplodingStage(), section_animator=animator, output_root=tmp_path,
        concat_clips=lambda paths, out: out, build_audio=lambda paths, durations, out: out, mux=_mux,
    )
    request = LessonRequest(topic="T", audience="a", goal="g", duration_minutes=2, teaching_depth="i")
    plan = LessonPlan(title="T", learning_objectives=["x"], sections=["How"])
    script = LessonScript(introduction="Hi.", sections=[ScriptSection(section_title="How", narration="n")], conclusion="Bye.")

    service.render_lesson(request, plan, script, allow_trace=False)

    assert animator.allow_trace is False


def test_the_demo_service_passes_the_knowledge_base_to_the_writer(tmp_path):
    from schemas.knowledge import KnowledgeBase

    knowledge = KnowledgeBase(topic="Binary Search", audience="beginner", key_concepts=["halving"], facts=[])
    seen = {}

    class KnowledgeAgent:
        def create_knowledge_base(self, lesson_request):
            return knowledge

    class RecordingWriter(Writer):
        def create_lesson_script(self, lesson_request, lesson_plan, knowledge_base=None):
            seen["knowledge_base"] = knowledge_base
            return super().create_lesson_script(lesson_request, lesson_plan)

    service = DemoVideoService(
        lesson_analyzer_service=Analyzer(), lesson_planner_service=Planner(), script_writer_service=RecordingWriter(),
        section_animator=Animator(), output_root=tmp_path, knowledge_agent_service=KnowledgeAgent(),
        concat_clips=lambda paths, out: out, build_audio=lambda paths, durations, out: out, mux=_mux,
    )

    service.generate_demo_video(UserLessonRequest(request="Explain binary search"))

    assert seen["knowledge_base"] is knowledge

from pathlib import Path

from animation.schemas import SectionClip
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, ScriptSection, UserLessonRequest
from services.demo_video_service import DemoVideoService


class Analyzer:
    def analyze_lesson_request(self, request):
        return LessonRequest(topic="Binary Search", audience="beginner", goal="understand it",
                             duration_minutes=2, teaching_depth="introductory")


class Planner:
    def create_lesson_plan(self, lesson_request):
        return LessonPlan(title="Binary Search", learning_objectives=["halve"], sections=["How"])


class Writer:
    def create_lesson_script(self, lesson_request, lesson_plan):
        return LessonScript(introduction="Hi.",
                            sections=[ScriptSection(section_title="How", narration="Halve it.")],
                            conclusion="Bye.")


class Animator:
    def __init__(self):
        self.sections = None

    def animate(self, sections, output_dir):
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

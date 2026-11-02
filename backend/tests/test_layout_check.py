import json
import types
from pathlib import Path

from animation.codegen import kit
from animation.codegen.generator import BEAT_REPORT_ENV, EXAMPLES_DIR, CodegenRenderer, LayoutCheck, check_layout
from animation.schemas import RenderSection
from animation.storyboard import PlannedBeat
from animation.templates.render import RenderError
from fakes import FakeLLM
from manim import DOWN, LEFT, RIGHT, UP, Arrow, BackgroundRectangle, Circle, Line, Rectangle, SurroundingRectangle, Text, ThreeDScene, VGroup

SECTION = RenderSection(index=2, title="Why it matters", narration="Algorithms are everywhere.")
BEATS = [PlannedBeat("Algorithms are everywhere in daily life.", "a ring of icons"),
         PlannedBeat("They follow clear steps to reach a result.", "three boxes")]
DURATIONS = [3.0, 4.0]
GOOD_CODE = (EXAMPLES_DIR / "title_card.py").read_text(encoding="utf-8")


class Scene:
    """Just enough of a Manim scene for the layout check: it reads `mobjects`."""

    def __init__(self, *mobjects):
        self.mobjects = list(mobjects)


def text(label, x=0.0, y=0.0, size=28):
    item = Text(label, font_size=size)
    item.move_to([x, y, 0])
    return item


# ---------------------------------------------------------------- kit.layout_issues
def test_two_overlapping_texts_are_reported():
    issues = kit.layout_issues(Scene(text("Alpha beam"), text("Beta ray")))

    assert len(issues) == 1 and "'Alpha beam'" in issues[0] and "'Beta ray'" in issues[0] and "overlap" in issues[0]


def test_texts_that_do_not_touch_are_fine():
    assert kit.layout_issues(Scene(text("Alpha", x=-3), text("Beta", x=3))) == []


def test_a_text_inside_a_box_is_not_an_overlap():
    box = Rectangle(width=4, height=1.5)
    label = text("Inside the box")

    assert kit.layout_issues(Scene(VGroup(box, label))) == []


def test_nested_groups_are_searched():
    nested = VGroup(VGroup(text("First label")), text("Second label"))

    issues = kit.layout_issues(Scene(nested))

    assert len(issues) == 1 and "overlap" in issues[0]


def test_invisible_text_is_ignored():
    hidden = text("Ghost words")
    hidden.set_opacity(0)

    assert kit.layout_issues(Scene(hidden, text("Visible words"))) == []


def test_text_leaving_the_frame_is_reported():
    issues = kit.layout_issues(Scene(text("Far away", x=9.0)))

    assert len(issues) == 1 and "'Far away'" in issues[0] and "leaves the screen" in issues[0]


def test_text_in_the_subtitle_area_is_reported():
    issues = kit.layout_issues(Scene(text("Too low", y=-3.6)))

    assert len(issues) == 1 and "covers the subtitle area" in issues[0]


def test_a_text_just_inside_the_safe_area_is_fine():
    assert kit.layout_issues(Scene(text("Fine", y=-2.4))) == []


def test_a_three_d_scene_checks_only_the_text_fixed_in_the_frame():
    class FakeThreeD(ThreeDScene):
        camera = types.SimpleNamespace(fixed_in_frame_mobjects=set())
        mobjects = []

    scene = object.__new__(FakeThreeD)
    scene.mobjects = [text("World one"), text("World two"), text("Label one", y=2), text("Label two", y=2)]
    FakeThreeD.camera.fixed_in_frame_mobjects = {scene.mobjects[2], scene.mobjects[3]}

    issues = kit.layout_issues(scene)

    assert len(issues) == 1 and "Label one" in issues[0] and "Label two" in issues[0]    # the world text pair is ignored


def test_the_beat_clock_report_rows_carry_the_layout_issues(tmp_path, monkeypatch):
    monkeypatch.setenv(kit.BEAT_REPORT_ENV, str(tmp_path / "r.json"))
    scene = types.SimpleNamespace(
        renderer=types.SimpleNamespace(time=0.0), mobjects=[text("Alpha beam"), text("Beta ray")],
        wait=lambda seconds: None,
    )
    clock = kit.BeatClock(scene, durations=[0.0])

    clock.end_beat()

    row = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))[0]
    assert len(row["layout"]) == 1 and "overlap" in row["layout"][0]


# ---------------------------------------------------------------- text crossed by lines, arrows and shape edges
def test_a_line_through_text_is_reported():
    issues = kit.layout_issues(Scene(text("Label"), Line([-3, 0, 0], [3, 0, 0])))

    assert len(issues) == 1 and "'Label'" in issues[0] and "crossed" in issues[0]


def test_an_arrow_running_through_a_label_is_reported():
    issues = kit.layout_issues(Scene(Arrow([-3, 0.1, 0], [3, 0.1, 0]), text("ACK")))

    assert len(issues) == 1 and "'ACK'" in issues[0] and "crossed" in issues[0]


def test_a_diagonal_arrow_that_misses_the_text_is_fine():
    # the text sits inside the arrow's bounding box but far from its path
    assert kit.layout_issues(Scene(Arrow([-3, -2, 0], [3, 2, 0]), text("Far", x=2.5, y=-1.5))) == []


def test_a_shape_edge_cutting_through_text_is_reported():
    box = Rectangle(width=1.2, height=1.0).move_to([0, 0, 0])
    label = text("Long label here", x=0.6)           # straddles the right edge of the box

    issues = kit.layout_issues(Scene(box, label))

    assert len(issues) == 1 and "crossed" in issues[0]


def test_a_line_grazing_the_edge_of_a_label_is_reported_as_touching():
    label = text("ACK")
    just_above = label.get_top()[1] + 0.02              # closer than the 0.05 margin, but not through the text

    issues = kit.layout_issues(Scene(label, Line([-3, just_above, 0], [3, just_above, 0])))

    assert len(issues) == 1 and "touching" in issues[0]


def test_a_line_a_comfortable_distance_from_a_label_is_fine():
    label = text("ACK")
    clear = label.get_top()[1] + 0.3

    assert kit.layout_issues(Scene(label, Line([-3, clear, 0], [3, clear, 0]))) == []


def test_text_fully_inside_a_circle_or_box_is_fine():
    assert kit.layout_issues(Scene(Circle(radius=1.5), text("Inside"))) == []
    assert kit.layout_issues(Scene(Rectangle(width=4, height=1.5), text("Inside"))) == []


def test_an_invisible_line_is_ignored():
    line = Line([-3, 0, 0], [3, 0, 0])
    line.set_stroke(opacity=0)
    line.set_fill(opacity=0)

    assert kit.layout_issues(Scene(text("Label"), line)) == []


def test_the_codegen_prompt_asks_for_labels_beside_arrows():
    llm = FakeLLM([{"code": GOOD_CODE}])
    run(llm, Renderer({1: rows([], [])}), Path(__import__("tempfile").mkdtemp()))

    assert "Keep text clear of arrows and lines: place a label beside an arrow with next_to(arrow, UP, buff=0.2), never on it." in " ".join(llm.prompts[0].split())


# ---------------------------------------------------------------- generator.check_layout
def rows(*layouts):
    ends = [3.0, 7.0, 8.0, 9.0]
    return [{"beat": i + 1, "start": 0.0, "expected_end": ends[i], "actual_end": ends[i], "overrun": 0.0, "layout": list(layout)}
            for i, layout in enumerate(layouts)]


def test_check_layout_names_the_beat_and_the_pair_and_says_how_to_fix_it():
    check = check_layout(rows([], ["'A' and 'B' overlap"]))

    assert check.issue_count == 1
    assert "Beat 2" in check.error and "'A' and 'B' overlap" in check.error
    assert "move one object, scale it down, shorten the text, or remove the old object first" in check.error


def test_the_same_issue_in_several_beats_counts_once():
    check = check_layout(rows(["'A' and 'B' overlap"], ["'A' and 'B' overlap"]))

    assert check.issue_count == 1 and "Beats 1-2" in check.error


def test_rows_without_layout_data_have_no_layout_error():
    plain = [{"beat": 1, "start": 0.0, "expected_end": 3.0, "actual_end": 3.0, "overrun": 0.0}]

    assert check_layout(plain) == LayoutCheck(None, 0)


# ---------------------------------------------------------------- the codegen loop
class Renderer:
    def __init__(self, reports):
        self.reports = reports
        self.calls = []

    def __call__(self, scene_file, scene_name, work_dir, output_path, extra_env):
        self.calls.append(scene_file)
        number = len(self.calls)
        output_path.write_bytes(f"video{number}".encode())
        Path(extra_env[BEAT_REPORT_ENV]).write_text(json.dumps(self.reports[number]), encoding="utf-8")
        return output_path


def run(llm, renderer, tmp_path):
    return CodegenRenderer(llm, scene_renderer=renderer).render(
        SECTION, BEATS, DURATIONS, tmp_path / "work", tmp_path / "out.mp4", tmp_path / "artifacts"
    )


def test_a_layout_issue_triggers_a_retry_with_the_message_in_the_prompt(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}] * 2)
    renderer = Renderer({1: rows([], ["'A' and 'B' overlap"]), 2: rows([], [])})

    result = run(llm, renderer, tmp_path)

    assert result.warnings == [] and len(renderer.calls) == 2
    assert "Beat 2" in llm.prompts[1] and "'A' and 'B' overlap" in llm.prompts[1]
    assert (tmp_path / "out.mp4").read_bytes() == b"video2"


def test_after_all_attempts_the_least_flawed_scene_is_used_with_a_warning(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}] * 3)
    three, one, two = ["'1' and '2' overlap", "'3' and '4' overlap", "'5' and '6' overlap"], ["'1' and '2' overlap"], \
        ["'7' and '8' overlap", "'9' and '0' overlap"]
    renderer = Renderer({1: rows(three, []), 2: rows(one, []), 3: rows(two, [])})

    result = run(llm, renderer, tmp_path)

    assert (tmp_path / "out.mp4").read_bytes() == b"video2"
    assert len(result.warnings) == 1
    assert "some text may overlap" in result.warnings[0] and "Why it matters" in result.warnings[0]


def test_a_clean_scene_returns_at_once(tmp_path):
    renderer = Renderer({1: rows([], [])})

    result = run(FakeLLM([{"code": GOOD_CODE}]), renderer, tmp_path)

    assert result.warnings == [] and len(renderer.calls) == 1


def test_a_timing_problem_and_a_layout_problem_are_reported_together(tmp_path):
    late = rows([], ["'A' and 'B' overlap"])
    late[1]["actual_end"] = 9.5
    late[1]["overrun"] = 2.5
    llm = FakeLLM([{"code": GOOD_CODE}] * 2)
    renderer = Renderer({1: late, 2: rows([], [])})

    run(llm, renderer, tmp_path)

    assert "ended 2.5 s after its audio ended" in llm.prompts[1] and "'A' and 'B' overlap" in llm.prompts[1]


def test_the_codegen_prompt_contains_the_layout_rules(tmp_path):
    llm = FakeLLM([{"code": GOOD_CODE}])
    run(llm, Renderer({1: rows([], [])}), tmp_path)

    prompt = " ".join(llm.prompts[0].split())
    for rule in (
        "Place content on a grid: at most 6 text items on screen at once; leave 0.4 units between any two objects.",
        "Never place text on top of other text; use next_to(..., buff=0.3) or arrange(..., buff=0.3).",
        "Fade out or remove an object before drawing something else in its place.",
        "Text longer than 28 characters must be split over lines or scaled with scale_to_fit_width.",
        "Call fit_in_frame on every group you build.",
    ):
        assert rule in prompt


def test_a_background_rectangle_or_tight_surrounding_box_is_not_a_crossing():
    label = text("Highlighted")

    assert kit.layout_issues(Scene(BackgroundRectangle(label, fill_opacity=0.5, buff=0), label)) == []
    assert kit.layout_issues(Scene(label, SurroundingRectangle(label, buff=0.05))) == []


def test_a_label_scaled_to_just_fit_inside_its_box_is_fine():
    box = Rectangle(width=3, height=1)
    label = text("Inside")
    label.scale_to_fit_width(box.width - 0.08)

    assert kit.layout_issues(Scene(box, label)) == []


def test_a_small_layout_flaw_on_time_beats_a_clean_layout_that_is_far_too_late(tmp_path):
    flawed = rows(["'A' and 'B' overlap"], [])
    late = rows([], [])
    late[1]["actual_end"] = 13.0
    late[1]["overrun"] = 6.0
    llm = FakeLLM([{"code": GOOD_CODE}] * 3)
    renderer = Renderer({1: flawed, 2: late, 3: late})

    result = run(llm, renderer, tmp_path)

    assert (tmp_path / "out.mp4").read_bytes() == b"video1"
    assert len(result.warnings) == 1 and "overlap" in result.warnings[0]

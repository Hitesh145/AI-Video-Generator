from animation.router import AnimationRouter
from animation.schemas import RenderSection
from animation.tracers import default_registry
from fakes import FakeLLM


SECTIONS = [
    RenderSection(index=0, title="Introduction", narration="Why search?"),
    RenderSection(index=1, title="Binary search step by step", narration="Look at the middle..."),
]


def route(llm):
    return AnimationRouter(llm, default_registry()).route(SECTIONS)


def plan(*routes):
    return {"routes": list(routes)}


def test_resolves_trace_and_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "binary_search",
         "inputs_json": '{"values": [1, 3, 5, 7], "target": 5}'},
    )]))

    assert [r.path for r in result.routes] == ["codegen", "trace"]
    assert result.routes[1].tracer == "binary_search"
    assert result.routes[1].inputs.target == 5
    assert result.warnings == []


def test_prompt_lists_tracers_and_sections():
    llm = FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "codegen"},
    )])
    route(llm)

    assert "bubble_sort" in llm.prompts[0]
    assert "Binary search step by step" in llm.prompts[0]


def test_unknown_tracer_falls_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "quick_sort", "inputs_json": "{}"},
    )]))

    assert result.routes[1].path == "codegen"
    assert "quick_sort" in result.warnings[0]


def test_invalid_inputs_fall_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "binary_search",
         "inputs_json": '{"values": [5, 1, 3], "target": 1}'},
    )]))

    assert result.routes[1].path == "codegen"
    assert "invalid inputs" in result.warnings[0]


def test_malformed_json_falls_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "binary_search", "inputs_json": "{values:"},
    )]))

    assert result.routes[1].path == "codegen"


def test_duplicate_indices_fall_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 0, "path": "codegen"},
    )]))

    assert [r.path for r in result.routes] == ["codegen", "codegen"]
    assert [r.section_index for r in result.routes] == [0, 1]
    assert len(result.warnings) == 1


def test_llm_failure_falls_back_to_codegen():
    result = route(FakeLLM([RuntimeError("timeout")]))

    assert [r.path for r in result.routes] == ["codegen", "codegen"]
    assert "timeout" in result.warnings[0]

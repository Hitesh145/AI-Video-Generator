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
         "values": [1, 3, 5, 7], "target": 5},
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
        {"section_index": 1, "path": "trace", "tracer": "quick_sort", "values": [3, 1]},
    )]))

    assert result.routes[1].path == "codegen"
    assert "quick_sort" in result.warnings[0]


def test_invalid_inputs_fall_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "binary_search",
         "values": [5, 1, 3], "target": 1},
    )]))

    assert result.routes[1].path == "codegen"
    assert "invalid inputs" in result.warnings[0]
    assert "sorted" in result.warnings[0]


def test_missing_inputs_fall_back_to_codegen():
    # Gemini's observed failure mode: tracer chosen, inputs left empty
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "binary_search"},
    )]))

    assert result.routes[1].path == "codegen"
    assert "values" in result.warnings[0]


def test_search_target_is_optional_for_sorts():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "bubble_sort", "values": [3, 1, 2]},
    )]))

    assert result.routes[1].path == "trace"
    assert result.routes[1].inputs.values == [3, 1, 2]


def test_duplicate_indices_fall_back_to_codegen():
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 0, "path": "codegen"},
    )]))

    assert [r.path for r in result.routes] == ["codegen", "codegen"]
    assert [r.section_index for r in result.routes] == [0, 1]
    assert len(result.warnings) == 1


def test_llm_failure_falls_back_to_codegen():
    result = route(FakeLLM([RuntimeError("timeout"), RuntimeError("timeout")]))

    assert [r.path for r in result.routes] == ["codegen", "codegen"]
    assert "timeout" in result.warnings[0]


def test_retries_once_after_unusable_plan():
    llm = FakeLLM([
        plan({"section_index": 0, "path": "codegen"}),  # too few routes
        plan(
            {"section_index": 0, "path": "codegen"},
            {"section_index": 1, "path": "trace", "tracer": "bubble_sort", "values": [3, 1, 2]},
        ),
    ])

    result = route(llm)

    assert [r.path for r in result.routes] == ["codegen", "trace"]
    assert result.warnings == []
    assert len(llm.prompts) == 2


def test_missing_search_target_is_picked_from_values():
    # Gemini's observed failure mode: values filled, optional target omitted
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "codegen"},
        {"section_index": 1, "path": "trace", "tracer": "binary_search", "values": [1, 3, 5, 7, 9, 11]},
    )]))

    assert result.routes[1].path == "trace"
    assert result.routes[1].inputs.target in [1, 3, 5, 7, 9, 11]
    assert result.warnings == []


def test_route_schema_bounds_values_for_the_llm():
    from animation.schemas import Route

    values_schema = Route.model_json_schema()["properties"]["values"]

    assert values_schema["maxItems"] == 8
    assert values_schema["items"]["minimum"] == -99
    assert values_schema["items"]["maximum"] == 999


def test_out_of_range_route_only_affects_its_section():
    # a 10-value example is valid for tracers' limits in the spec but over the
    # LLM-facing cap; it must not invalidate the other routes
    result = route(FakeLLM([plan(
        {"section_index": 0, "path": "trace", "tracer": "bubble_sort", "values": list(range(13))},
        {"section_index": 1, "path": "trace", "tracer": "bubble_sort", "values": [3, 1, 2]},
    )]))

    assert [r.path for r in result.routes] == ["codegen", "trace"]
    assert len(result.warnings) == 1

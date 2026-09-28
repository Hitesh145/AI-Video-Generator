import json
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

from animation.schemas import RenderSection, Route, RoutePlan
from animation.tracers.base import TracerRegistry


class StructuredGenerator(Protocol):
    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        ...


@dataclass
class ResolvedRoute:
    section_index: int
    path: Literal["trace", "codegen"]
    tracer: str | None = None
    inputs: BaseModel | None = None


@dataclass
class RoutingResult:
    routes: list[ResolvedRoute]
    warnings: list[str]


class AnimationRouter:
    def __init__(self, llm: StructuredGenerator, registry: TracerRegistry) -> None:
        self.llm = llm
        self.registry = registry

    def route(self, sections: list[RenderSection]) -> RoutingResult:
        if not sections:
            return RoutingResult([], [])

        try:
            result = self.llm.generate_structured(self._build_prompt(sections), RoutePlan)
            plan = RoutePlan.model_validate(result.model_dump())
        except Exception as exc:
            return self._all_codegen(sections, f"Animation router failed ({exc}); all sections use generated animation.")

        indices = [route.section_index for route in plan.routes]
        if sorted(indices) != [section.index for section in sections]:
            return self._all_codegen(
                sections,
                f"Animation router returned routes for sections {indices} but expected "
                f"{[section.index for section in sections]}; all sections use generated animation.",
            )

        by_index = {route.section_index: route for route in plan.routes}
        warnings: list[str] = []
        routes = [self._resolve(section, by_index[section.index], warnings) for section in sections]
        return RoutingResult(routes, warnings)

    def _resolve(self, section: RenderSection, route: Route, warnings: list[str]) -> ResolvedRoute:
        codegen = ResolvedRoute(section.index, "codegen")
        if route.path == "codegen":
            return codegen

        tracer = self.registry.get(route.tracer or "")
        if tracer is None:
            warnings.append(
                f"Section '{section.title}': unknown tracer '{route.tracer}', using generated animation."
            )
            return codegen

        try:
            inputs = tracer.input_schema.model_validate_json(route.inputs_json)
        except ValidationError as exc:
            warnings.append(
                f"Section '{section.title}': invalid inputs for {tracer.name} "
                f"({exc.error_count()} errors), using generated animation."
            )
            return codegen

        return ResolvedRoute(section.index, "trace", tracer.name, inputs)

    def _all_codegen(self, sections: list[RenderSection], warning: str) -> RoutingResult:
        return RoutingResult([ResolvedRoute(section.index, "codegen") for section in sections], [warning])

    def _build_prompt(self, sections: list[RenderSection]) -> str:
        section_text = "\n\n".join(
            f"[section_index {section.index}] {section.title}\n{section.narration}"
            for section in sections
        )
        catalogue = json.dumps(self.registry.catalogue(), indent=2)

        return f"""
Decide how to animate each section of an educational video.

Two paths are available:
- "trace": animate a registered algorithm tracer. Real code runs the algorithm on the
  inputs you choose and every step is animated. Use this only when the section walks
  through one of these algorithms on concrete data.
- "codegen": a custom animation is written for the section. Use this for everything
  else, including introductions, conclusions, definitions and comparisons.

Registered tracers (name, description, JSON schema of inputs):
{catalogue}

Sections:
{section_text}

Rules:
1. Return exactly one route per section, using its section_index.
2. For "trace", set "tracer" to a registered name and "inputs_json" to a JSON object
   string that matches that tracer's input schema.
3. If the narration uses a concrete example (specific numbers or a target), use exactly
   those values. Otherwise choose a small illustrative example: 5-8 values for searches,
   5-7 values for sorts.
4. binary_search values must be sorted ascending.
5. For "codegen", leave tracer empty and inputs_json as "{{}}".
"""

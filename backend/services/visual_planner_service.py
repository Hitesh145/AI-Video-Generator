from typing import Protocol

from pydantic import BaseModel

from schemas.lesson import LessonScript
from schemas.visual import ScenePlan


class StructuredGenerator(Protocol):
    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
    ) -> BaseModel:
        ...


class VisualPlannerService:
    def __init__(self, llm_service: StructuredGenerator) -> None:
        self.llm_service = llm_service

    def create_scene_plan(self, lesson_script: LessonScript) -> ScenePlan:
        prompt = self._build_prompt(lesson_script)
        result = self.llm_service.generate_structured(prompt, ScenePlan)

        if not isinstance(result, ScenePlan):
            raise TypeError("Visual planner did not return a ScenePlan.")

        return result

    def _build_prompt(self, lesson_script: LessonScript) -> str:
        return f"""
        Create a structured visual scene plan for the following educational
        lesson script.

        The plan will later be consumed by a deterministic visual-resolution
        and rendering system.

        Lesson script:
        {lesson_script.model_dump_json(indent=2)}

        Requirements:

        1. Create visual scenes that support the introduction, every lesson
           section, and the conclusion when useful.
        2. Preserve exact section titles from the lesson script.
        3. Do not rewrite, summarize, or modify the narration.
        4. Choose visuals that directly support the teaching point.
        5. Prefer simple educational visuals over decorative or cinematic
           visuals.
        6. Use renderer-neutral visual types such as diagram, animation, chart,
           equation, timeline, process, comparison, graph, map, text,
           illustration, or mixed.
        7. Use elements for educational objects the learner should see.
        8. Use relationships for the meaning between those objects.
        9. Use actions for changes that should happen over time.
        10. Every scene must include at least one element and at least one
            action. Static visuals should still include a show, reveal,
            highlight, or annotate action.
        11. Every action must target one or more existing element IDs from the
            same scene. Do not use an empty target list.
        12. Include narration cues when a visual action should align with a
            phrase or idea in the narration.
        13. Include estimated scene durations, but do not include exact
            timestamps.
        14. Do not include renderer names, provider names, file paths, pixel
            coordinates, code, camera movements, or tool-specific rendering
            instructions.
        15. Return only the structured result matching the provided schema.
        """

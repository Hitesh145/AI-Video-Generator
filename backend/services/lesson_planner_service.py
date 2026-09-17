from typing import Protocol

from pydantic import BaseModel

from schemas.lesson import LessonPlan, LessonRequest


class StructuredGenerator(Protocol):
    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
    ) -> BaseModel:
        ...


class LessonPlannerService:
    def __init__(self, llm_service: StructuredGenerator) -> None:
        self.llm_service = llm_service

    def create_lesson_plan(self, lesson_request: LessonRequest) -> LessonPlan:
        prompt = self._build_prompt(lesson_request)
        result = self.llm_service.generate_structured(prompt, LessonPlan)

        if not isinstance(result, LessonPlan):
            raise TypeError("Lesson planner did not return a LessonPlan.")

        return result

    def _build_prompt(self, lesson_request: LessonRequest) -> str:
        return f"""
        Create a structured educational lesson plan based on the following
        request.

        Topic: {lesson_request.topic}
        Audience: {lesson_request.audience}
        Goal: {lesson_request.goal}
        Duration: {lesson_request.duration_minutes} minutes
        Teaching depth: {lesson_request.teaching_depth}

        Design the lesson for the specified audience and depth.

        Create a logical teaching progression from foundational ideas to the
        final understanding.

        Requirements:

        1. Return a clear lesson title.
        2. Return the main learning objectives.
        3. Return an ordered sequence of teaching sections.
        4. Keep the structure generic and concept-independent.
        5. Do not write the full narration.
        6. Do not include visual instructions.
        7. Return only the structured result matching the provided schema.
        """

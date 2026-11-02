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
        plan = self._generate(prompt)

        missing = self._missing_items(lesson_request, plan)
        if missing:
            # One retry naming what was forgotten; whatever comes back is used.
            plan = self._generate(
                f"{prompt}\n\nYou forgot to cover: {', '.join(missing)}. "
                "Return the corrected plan with every item defined in some section."
            )
        return self._tidy(plan)

    def _generate(self, prompt: str) -> LessonPlan:
        result = self.llm_service.generate_structured(prompt, LessonPlan)

        if not isinstance(result, LessonPlan):
            raise TypeError("Lesson planner did not return a LessonPlan.")

        return result

    @staticmethod
    def _missing_items(lesson_request: LessonRequest, plan: LessonPlan) -> list[str]:
        covered_text = " ".join(
            [*plan.sections, *(term for note in plan.section_notes for term in note.terms_to_define)]
        ).casefold()
        return [item for item in lesson_request.must_cover if item.strip() and item.casefold() not in covered_text]

    @staticmethod
    def _tidy(plan: LessonPlan) -> LessonPlan:
        """Notes are kept only when there is exactly one per section; their titles follow the sections."""
        if len(plan.section_notes) != len(plan.sections):
            return plan.model_copy(update={"section_notes": []})
        notes = [note.model_copy(update={"title": title}) for note, title in zip(plan.section_notes, plan.sections)]
        return plan.model_copy(update={"section_notes": notes})

    def _build_prompt(self, lesson_request: LessonRequest) -> str:
        must_cover = ", ".join(lesson_request.must_cover) or "(nothing specific)"
        return f"""
        Create a structured educational lesson plan based on the following
        request.

        Topic: {lesson_request.topic}
        Audience: {lesson_request.audience}
        Goal: {lesson_request.goal}
        Duration: {lesson_request.duration_minutes} minutes
        Teaching depth: {lesson_request.teaching_depth}
        Must cover: {must_cover}

        Design the lesson for the specified audience and depth.

        Create a logical teaching progression from foundational ideas to the
        final understanding.

        Requirements:

        1. Return a clear lesson title.
        2. Return the main learning objectives.
        3. Return an ordered sequence of teaching sections (sections) and, for the same sections in the same order, section_notes.
        4. Order sections so that every term is explained before any later section uses it.
        5. Give each section a one-sentence purpose, the terms it must define, and, for any procedure, one worked example.
        6. Use about one section per minute of the lesson (at least 3, at most 12).
        7. Every item in must_cover must be defined in some section's terms_to_define.
        8. Do not write the full narration.
        9. Do not include visual instructions.
        10. Return only the structured result matching the provided schema.
        """

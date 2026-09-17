from typing import Protocol

from pydantic import BaseModel

from schemas.lesson import LessonPlan, LessonRequest, LessonScript


class StructuredGenerator(Protocol):
    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
    ) -> BaseModel:
        ...


class ScriptWriterService:
    WORDS_PER_MINUTE = 130

    def __init__(self, llm_service: StructuredGenerator) -> None:
        self.llm_service = llm_service

    def create_lesson_script(
        self,
        lesson_request: LessonRequest,
        lesson_plan: LessonPlan,
    ) -> LessonScript:
        prompt = self._build_prompt(lesson_request, lesson_plan)
        result = self.llm_service.generate_structured(prompt, LessonScript)

        if not isinstance(result, LessonScript):
            raise TypeError("Script writer did not return a LessonScript.")

        return result

    def _build_prompt(
        self,
        lesson_request: LessonRequest,
        lesson_plan: LessonPlan,
    ) -> str:
        target_words = lesson_request.duration_minutes * self.WORDS_PER_MINUTE

        return f"""
        Write a clear educational narration based on the lesson request and
        lesson plan below.

        Topic: {lesson_request.topic}
        Audience: {lesson_request.audience}
        Goal: {lesson_request.goal}
        Duration: {lesson_request.duration_minutes} minutes
        Teaching depth: {lesson_request.teaching_depth}

        Lesson title:
        {lesson_plan.title}

        Learning objectives:
        {lesson_plan.learning_objectives}

        Ordered lesson sections:
        {lesson_plan.sections}

        Requirements:

        1. Write an engaging but concise introduction.
        2. Write narration for every lesson section in the exact same order.
        3. Preserve the lesson section titles exactly.
        4. Make the explanation appropriate for the requested audience.
        5. Explain concepts clearly rather than assuming prior knowledge.
        6. Use simple examples where useful.
        7. End with a concise conclusion that reinforces the main idea.
        8. Do not write visual directions.
        9. Do not describe animations, camera movements, images, or scenes.
        10. Do not include timestamps.
        11. Target approximately {self.WORDS_PER_MINUTE} words of narration
            per minute.
        12. For a {lesson_request.duration_minutes}-minute lesson, aim for
            approximately {target_words} total words.
        13. Keep the narration concise enough to stay close to the requested
            duration.
        14. Return only the structured result matching the provided schema.
        """

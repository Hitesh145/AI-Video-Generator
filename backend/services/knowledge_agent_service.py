from typing import Protocol

from pydantic import BaseModel

from schemas.knowledge import KnowledgeBase
from schemas.lesson import LessonRequest


class StructuredGenerator(Protocol):
    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
    ) -> BaseModel:
        ...


class KnowledgeAgentService:
    def __init__(self, llm_service: StructuredGenerator) -> None:
        self.llm_service = llm_service

    def create_knowledge_base(
        self,
        lesson_request: LessonRequest,
    ) -> KnowledgeBase:
        prompt = self._build_prompt(lesson_request)
        result = self.llm_service.generate_structured(prompt, KnowledgeBase)

        if not isinstance(result, KnowledgeBase):
            raise TypeError("Knowledge agent did not return a KnowledgeBase.")

        return result

    def _build_prompt(self, lesson_request: LessonRequest) -> str:
        return f"""
        Create a structured educational knowledge base for the following lesson
        request.

        Topic: {lesson_request.topic}
        Audience: {lesson_request.audience}
        Goal: {lesson_request.goal}
        Duration: {lesson_request.duration_minutes} minutes
        Teaching depth: {lesson_request.teaching_depth}

        Responsibilities:

        1. Identify the key concepts the learner must understand.
        2. List factual claims that are important for a correct lesson.
        3. Prefer stable, widely accepted educational facts.
        4. Flag misconceptions, conflicts, or disputed claims if they matter.
        5. Identify gaps that would need external research before final video
           generation.
        6. Keep the facts appropriate for the requested audience and depth.
        7. Do not write the lesson narration.
        8. Do not include visual directions.
        9. Return only the structured result matching the provided schema.
        """

from typing import Protocol

from pydantic import BaseModel

from schemas.lesson import LessonRequest, UserLessonRequest


class StructuredGenerator(Protocol):
    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
    ) -> BaseModel:
        ...


class LessonAnalyzerService:
    def __init__(self, llm_service: StructuredGenerator) -> None:
        self.llm_service = llm_service

    def analyze_lesson_request(
        self,
        request: UserLessonRequest,
    ) -> LessonRequest:
        prompt = self._build_prompt(request)
        result = self.llm_service.generate_structured(prompt, LessonRequest)

        if not isinstance(result, LessonRequest):
            raise TypeError("Lesson analyzer did not return a LessonRequest.")

        return result

    def _build_prompt(self, request: UserLessonRequest) -> str:
        return f"""
        Analyze the following educational request.

        User request:
        {request.request}

        Determine:
        - the topic
        - the intended audience
        - the learning goal
        - an approximate lesson duration in minutes
        - the teaching depth

        Return only the structured result matching the provided schema.
        """

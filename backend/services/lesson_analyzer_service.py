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
        - topic: a short noun phrase naming the subject.
        - audience: who the lesson is for, as the learner described it; a complete beginner if not stated.
        - goal: what the learner should be able to do or explain at the end.
        - duration_minutes: how long the lesson should be.
        - teaching_depth.
        - must_cover: the terms, concepts or parts the learner must come away understanding.

        Rules:
        1. A request for "detail", "in detail", "in depth", "thorough" or "complete" means about 8 minutes and a thorough explanation.
        2. A quick or brief request means 2 minutes. If nothing is said, use 4 minutes. Never more than 12.
        3. teaching_depth must be one of: introductory, intermediate, advanced. Asking for detail does not by itself mean advanced; use the audience the learner described.
        4. must_cover: list every term, concept or part the learner named, plus terms the topic cannot be understood without (at most 8).
        5. Use the learner's own words for must_cover items.

        Return only the structured result matching the provided schema.
        """

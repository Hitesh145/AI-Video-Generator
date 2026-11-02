from typing import Protocol

from pydantic import BaseModel

from schemas.knowledge import KnowledgeBase
from schemas.lesson import LessonPlan, LessonRequest, LessonScript


class StructuredGenerator(Protocol):
    def generate_structured(
        self,
        prompt: str,
        response_schema: type[BaseModel],
    ) -> BaseModel:
        ...


def _words(script: LessonScript) -> int:
    parts = [script.introduction, *(section.narration for section in script.sections), script.conclusion]
    return sum(len(part.split()) for part in parts)


class ScriptWriterService:
    WORDS_PER_MINUTE = 130
    FRAMING_SHARE = 0.10        # of the words: introduction and conclusion together
    MIN_LENGTH_SHARE = 0.70     # below this share of the target, the script is rewritten once at full length
    MAX_FACTS = 15

    def __init__(self, llm_service: StructuredGenerator) -> None:
        self.llm_service = llm_service

    def create_lesson_script(
        self,
        lesson_request: LessonRequest,
        lesson_plan: LessonPlan,
        knowledge_base: KnowledgeBase | None = None,
    ) -> LessonScript:
        prompt = self._build_prompt(lesson_request, lesson_plan, knowledge_base)
        script = self._generate(prompt)

        target = lesson_request.duration_minutes * self.WORDS_PER_MINUTE
        written = _words(script)
        if written < self.MIN_LENGTH_SHARE * target:
            # Models tend to stop far short of the requested length; ask once for the full lesson.
            retry = self._generate(self._expansion_prompt(prompt, script, written, target))
            if _words(retry) > written:
                return retry
        return script

    def _generate(self, prompt: str) -> LessonScript:
        result = self.llm_service.generate_structured(prompt, LessonScript)

        if not isinstance(result, LessonScript):
            raise TypeError("Script writer did not return a LessonScript.")

        return result

    @staticmethod
    def _expansion_prompt(prompt: str, script: LessonScript, written: int, target: int) -> str:
        previous = chr(10).join(f"{section.section_title}: {section.narration}" for section in script.sections)
        gap = chr(10) + chr(10)
        return (
            f"{prompt}{gap}Your previous script had {written} words; this lesson needs about {target} words. "
            "Write it again at full length: in every section add the definitions, the step-by-step walk-through "
            "and the worked example with specific values that the plan asks for. Do not repeat sentences."
            f"{gap}Previous script (too short):{chr(10)}{previous}"
        )

    def _build_prompt(
        self,
        lesson_request: LessonRequest,
        lesson_plan: LessonPlan,
        knowledge_base: KnowledgeBase | None = None,
    ) -> str:
        target_words = lesson_request.duration_minutes * self.WORDS_PER_MINUTE
        sections = max(1, len(lesson_plan.sections))
        per_section = round(target_words * (1 - self.FRAMING_SHARE) / sections)
        must_cover = ", ".join(lesson_request.must_cover) or "(nothing specific)"

        return f"""
        Write a clear educational narration based on the lesson request and
        lesson plan below.

        Topic: {lesson_request.topic}
        Audience: {lesson_request.audience}
        Goal: {lesson_request.goal}
        Duration: {lesson_request.duration_minutes} minutes
        Teaching depth: {lesson_request.teaching_depth}
        Must cover: {must_cover}

        Lesson title:
        {lesson_plan.title}

        Learning objectives:
        {lesson_plan.learning_objectives}

        Ordered lesson sections:
        {self._sections_text(lesson_plan)}
        {self._facts_text(knowledge_base)}
        Requirements:

        1. Write an engaging but concise introduction.
        2. Write narration for every lesson section in the exact same order.
        3. Preserve the lesson section titles exactly.
        4. Make the explanation appropriate for the requested audience.
        5. Explain concepts clearly rather than assuming prior knowledge.
        6. Define every technical term in the sentence where it first appears: say what it is and what it is for.
        7. Use simple examples where useful.
        8. End with a concise conclusion that reinforces the main idea.
        9. Do not write visual directions.
        10. Do not describe animations, camera movements, images, or scenes.
        11. Do not include timestamps.
        12. Target approximately {self.WORDS_PER_MINUTE} words of narration
            per minute.
        13. For a {lesson_request.duration_minutes}-minute lesson, aim for
            approximately {target_words} total words, about {per_section} words per section.
        14. Never skip a definition or a step to save words; length follows the requested duration, but completeness comes first.
        15. Do not pad; every sentence must teach something.
        16. Write short sentences, under about 22 words each, with one idea
            per sentence. Never restate the previous sentence.
        17. Prefer ideas that can be drawn as shapes, arrows or diagrams
            over abstract statements, so each sentence can be shown on screen.
        18. Whenever a step-by-step procedure is explained, walk through
            ONE concrete example with specific values (for instance a short
            list of real numbers) instead of only describing it in general.
        19. Before answering, check: every term in must_cover is defined; every procedure has one worked example; no sentence relies on a term not yet explained.
        20. Return only the structured result matching the provided schema.
        """

    @staticmethod
    def _sections_text(lesson_plan: LessonPlan) -> str:
        if not lesson_plan.section_notes:
            return str(lesson_plan.sections)
        lines = []
        for number, note in enumerate(lesson_plan.section_notes, start=1):
            parts = [f"{number}. {note.title}", f"purpose: {note.purpose}"]
            if note.terms_to_define:
                parts.append(f"define: {', '.join(note.terms_to_define)}")
            if note.example:
                parts.append(f"example: {note.example}")
            lines.append(" | ".join(parts))
        return (chr(10) + "        ").join(lines)

    def _facts_text(self, knowledge_base: KnowledgeBase | None) -> str:
        if knowledge_base is None or not (knowledge_base.facts or knowledge_base.key_concepts):
            return ""
        lines = ["Reference facts you may rely on (do not contradict them):"]
        if knowledge_base.key_concepts:
            lines.append("Key concepts: " + ", ".join(knowledge_base.key_concepts))
        lines += [f"- {fact.claim}" for fact in knowledge_base.facts[: self.MAX_FACTS]]
        indent = chr(10) + "        "
        return indent + indent.join(lines) + chr(10)

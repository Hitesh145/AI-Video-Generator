"""A second pass over a finished script: find terms it uses without explaining, and fix them once.

The model lists the terms a complete beginner would not know that are used without a definition. The terms the
learner asked to be covered (``must_cover``) are also checked without the model: if one never appears in the script,
it is reported as never mentioned. A model error propagates, so a script that was meant to be reviewed is never
silently rendered unreviewed.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from schemas.lesson import LessonRequest, LessonScript
from schemas.terms import TermReview, UndefinedTerm


class StructuredGenerator(Protocol):
    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        ...


def _script_text(script: LessonScript) -> str:
    return " ".join([script.introduction, *(section.narration for section in script.sections), script.conclusion])


def _variants(term: str) -> set[str]:
    base = term.strip().casefold()
    return {base, base + "s", base[:-1] if base.endswith("s") else base}


def missing_must_cover(lesson_request: LessonRequest, script: LessonScript) -> list[str]:
    """The must_cover items that never occur in the script (case and a plural s do not matter)."""
    text = _script_text(script).casefold()
    return [
        item for item in lesson_request.must_cover
        if item.strip() and not any(variant in text for variant in _variants(item))
    ]


class TermReviewService:
    def __init__(self, llm_service: StructuredGenerator) -> None:
        self.llm_service = llm_service

    def review(self, lesson_request: LessonRequest, script: LessonScript) -> list[UndefinedTerm]:
        answer = self.llm_service.generate_structured(self._review_prompt(lesson_request, script), TermReview)
        if not isinstance(answer, TermReview):
            raise TypeError("The term review did not return a TermReview.")
        found = list(answer.undefined_terms)
        known = {item.term.strip().casefold() for item in found}
        for item in missing_must_cover(lesson_request, script):
            if item.strip().casefold() not in known:
                found.append(UndefinedTerm(term=item, section_title="", reason="never mentioned"))
        return found

    def improve(
        self, lesson_request: LessonRequest, script: LessonScript
    ) -> tuple[LessonScript, list[str]]:
        """The script with its undefined terms explained (one rewrite), and the must_cover items still missing."""
        undefined = self.review(lesson_request, script)
        if undefined:
            fixed = self._fix(lesson_request, script, undefined)
            if self._same_outline(script, fixed):
                script = fixed
        return script, missing_must_cover(lesson_request, script)

    def _fix(self, lesson_request: LessonRequest, script: LessonScript, undefined: list[UndefinedTerm]) -> LessonScript:
        result = self.llm_service.generate_structured(self._fix_prompt(lesson_request, script, undefined), LessonScript)
        if not isinstance(result, LessonScript):
            raise TypeError("The term fix did not return a LessonScript.")
        return result

    @staticmethod
    def _same_outline(original: LessonScript, rewritten: LessonScript) -> bool:
        """A rewrite may add words, never drop, rename or reorder sections."""
        return [s.section_title for s in original.sections] == [s.section_title for s in rewritten.sections]

    @staticmethod
    def _script_block(script: LessonScript) -> str:
        lines = [f"Introduction: {script.introduction}"]
        lines += [f"{section.section_title}: {section.narration}" for section in script.sections]
        lines.append(f"Conclusion: {script.conclusion}")
        return chr(10).join(lines)

    def _review_prompt(self, lesson_request: LessonRequest, script: LessonScript) -> str:
        return f"""
        You are grading an educational narration for a complete beginner. The learner asked about: {lesson_request.topic}

        List every technical term, symbol or named concept that a complete beginner would not already know
        AND that the narration uses without ever explaining what it is (no definition, no plain-language
        gloss, no worked example that makes its meaning clear). Be strict: a term that is only named, or only
        used inside another sentence, counts as undefined. Do not list everyday words. For each term give the
        title of the section where it is first used, and a few words on why it counts as unexplained.

        Narration:
        <<<NARRATION
        {self._script_block(script)}
        NARRATION>>>
        """

    def _fix_prompt(self, lesson_request: LessonRequest, script: LessonScript, undefined: list[UndefinedTerm]) -> str:
        listed = (chr(10) + "        ").join(
            f"- {item.term}" + (f" (first used in: {item.section_title})" if item.section_title else " (never mentioned: add it where it belongs)")
            for item in undefined
        )
        return f"""
        Here is a lesson narration for a complete beginner (topic: {lesson_request.topic}). These terms are used
        without being explained, or are missing:
        {listed}

        Rewrite the narration so that each listed term is explained in the sentence where it first appears: say
        what it is and what it is for, with a short example when that makes it clearer. Rewrite only the sections
        that need it. Keep every section title and the order of the sections exactly as they are, and remove
        nothing else. Return the complete narration in the same structure.

        Narration:
        <<<NARRATION
        {self._script_block(script)}
        NARRATION>>>
        """

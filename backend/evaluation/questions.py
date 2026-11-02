"""Question files: what a learner might ask about a paper, and how to recognise a good answer passage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


class Question(BaseModel):
    id: str
    question: str
    kind: Literal["answerable", "absent"]
    category: str
    # Short wording copied from the paper. A retrieved passage is relevant if it contains ANY of them.
    answer_phrases: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _phrases_match_the_kind(self) -> "Question":
        if self.kind == "answerable":
            if not self.answer_phrases or any(not phrase.strip() for phrase in self.answer_phrases):
                raise ValueError(f"Question {self.id}: an answerable question needs non-blank answer phrases")
        elif self.answer_phrases:
            raise ValueError(f"Question {self.id}: an absent question must not list answer phrases")
        return self


class QuestionSet(BaseModel):
    paper: str
    questions: list[Question]

    @model_validator(mode="after")
    def _ids_are_unique(self) -> "QuestionSet":
        seen: set[str] = set()
        for question in self.questions:
            if question.id in seen:
                raise ValueError(f"Duplicate question id {question.id}")
            seen.add(question.id)
        return self


def load_question_set(path: Path) -> QuestionSet:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{path.name}: cannot read the file ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name}: not valid JSON ({exc})") from exc
    try:
        return QuestionSet.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"{path.name}: {exc}") from exc

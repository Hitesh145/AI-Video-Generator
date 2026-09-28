from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from animation.schemas import RenderSection, StepNarration, TraceStep


class StructuredGenerator(Protocol):
    def generate_structured(self, prompt: str, response_schema: type[BaseModel]) -> BaseModel:
        ...


@dataclass(frozen=True)
class NarratedSegment:
    text: str
    step_indices: tuple[int, ...]


def segments_from_narration(step_count: int, narration: StepNarration) -> list[NarratedSegment]:
    groups = narration.group_with_previous
    if len(groups) != step_count:
        raise ValueError(f"Expected {step_count} group flags, got {len(groups)}.")
    if groups and groups[0]:
        raise ValueError("The first step cannot be grouped with a previous step.")
    narrated = groups.count(False)
    if len(narration.sentences) != narrated:
        raise ValueError(f"Expected {narrated} sentences, got {len(narration.sentences)}.")
    if any(not sentence.strip() for sentence in narration.sentences):
        raise ValueError("Sentences must not be blank.")

    segments: list[tuple[str, list[int]]] = []
    sentences = iter(narration.sentences)
    for index, grouped in enumerate(groups):
        if grouped:
            segments[-1][1].append(index)
        else:
            segments.append((next(sentences).strip(), [index]))

    return [NarratedSegment(text, tuple(indices)) for text, indices in segments]


class StepNarrator:
    def __init__(self, llm: StructuredGenerator, max_attempts: int = 2) -> None:
        self.llm = llm
        self.max_attempts = max_attempts

    def narrate(
        self,
        section: RenderSection,
        steps: list[TraceStep],
    ) -> tuple[list[NarratedSegment], list[str]]:
        prompt = self._build_prompt(section, steps)
        last_error: Exception | None = None

        for _ in range(self.max_attempts):
            try:
                result = self.llm.generate_structured(prompt, StepNarration)
                narration = StepNarration.model_validate(result.model_dump())
                return segments_from_narration(len(steps), narration), []
            except Exception as exc:
                last_error = exc

        fallback = [NarratedSegment(step.event, (index,)) for index, step in enumerate(steps)]
        warning = (
            f"Section '{section.title}': step narration failed ({last_error}); "
            "using plain step descriptions."
        )
        return fallback, [warning]

    def _build_prompt(self, section: RenderSection, steps: list[TraceStep]) -> str:
        events = "\n".join(f"{index}. {step.event}" for index, step in enumerate(steps))
        return f"""
Write the spoken narration for an animated algorithm walkthrough.

Section title: {section.title}
The lesson script for this section says:
{section.narration}

The animation shows these steps, in order ({len(steps)} steps):
{events}

Return:
- group_with_previous: exactly {len(steps)} booleans, one per step. Use true for small
  repetitive steps that can play quickly under the previous sentence (for example the
  many compare/swap steps of a long sort). Step 0 must be false.
- sentences: one short spoken sentence for every step whose flag is false, in order.

Rules:
1. Each sentence must describe only what its step (and any grouped steps after it)
   actually shows. Never mention values or outcomes that are not in the steps.
2. Keep the tone and level of the lesson script. One sentence each, under 25 words.
3. Plain spoken English: no markdown, no code, no lists.
"""

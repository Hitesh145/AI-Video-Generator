from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from schemas.lesson import LessonScript


PathUsed = Literal["trace", "codegen", "slideshow"]


class RenderSection(BaseModel):
    index: int = Field(ge=0, description="0-based position of the section in the video.")
    title: str
    narration: str


def build_render_sections(script: LessonScript) -> list[RenderSection]:
    parts: list[tuple[str, str]] = []
    if script.introduction.strip():
        parts.append(("Introduction", script.introduction))
    for section in script.sections:
        parts.append((section.section_title, section.narration))
    if script.conclusion.strip():
        parts.append(("Conclusion", script.conclusion))

    return [
        RenderSection(index=index, title=title, narration=narration)
        for index, (title, narration) in enumerate(parts)
    ]


class Route(BaseModel):
    section_index: int = Field(description="Index of the section this route is for.")
    path: Literal["trace", "codegen"] = Field(
        description="'trace' to animate a registered algorithm tracer, 'codegen' otherwise."
    )
    tracer: str | None = Field(
        default=None,
        description="Tracer name when path is 'trace'.",
    )
    # Plain structured fields rather than a JSON string: Gemini reliably fills
    # these, but mostly left a JSON-in-a-string field empty or truncated. The
    # bounds go into the schema Gemini decodes against; without them it
    # sometimes generated runaway number lists. The cap is 8 (tracers accept 12)
    # because Gemini pads to the maximum with filler values.
    values: list[Annotated[int, Field(ge=-99, le=999)]] = Field(
        default_factory=list,
        max_length=8,
        description="Array values for the tracer when path is 'trace' (5-8 values).",
    )
    target: Annotated[int, Field(ge=-99, le=999)] | None = Field(
        default=None,
        description="Value to search for, for search tracers only.",
    )


class RoutePlan(BaseModel):
    routes: list[Route] = Field(description="Exactly one route per section.")


class ArrayState(BaseModel):
    values: list[int | str]
    pointers: dict[str, int] = Field(default_factory=dict)
    highlighted: list[int] = Field(default_factory=list)
    dimmed: list[int] = Field(default_factory=list)
    swapped: tuple[int, int] | None = None
    sorted_indices: list[int] = Field(default_factory=list)
    found: int | None = None

    @model_validator(mode="after")
    def _indices_in_range(self) -> "ArrayState":
        count = len(self.values)
        indices = [
            *self.pointers.values(),
            *self.highlighted,
            *self.dimmed,
            *self.sorted_indices,
        ]
        if self.swapped is not None:
            indices.extend(self.swapped)
        if self.found is not None:
            indices.append(self.found)

        bad = [index for index in indices if not 0 <= index < count]
        if bad:
            raise ValueError(f"State indices out of range for {count} values: {bad}")
        return self


class TraceStep(BaseModel):
    state: ArrayState
    event: str = Field(min_length=1, description="Factual description of what happened.")


class StepNarration(BaseModel):
    sentences: list[str] = Field(
        description="One spoken sentence per step that is not grouped with the previous step."
    )
    group_with_previous: list[bool] = Field(
        description="One flag per step; true means the step plays quickly under the previous sentence."
    )


class SectionClip(BaseModel):
    section_index: int
    title: str
    video_path: str
    audio_path: str
    narration_segments: list[str]
    segment_durations: list[float]
    path_used: PathUsed
    tracer: str | None = None
    warnings: list[str] = Field(default_factory=list)


class SectionSummary(BaseModel):
    title: str
    path_used: PathUsed
    tracer: str | None = None
    duration_seconds: float
    warnings: list[str] = Field(default_factory=list)

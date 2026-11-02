from pydantic import BaseModel, Field


class GroundedSection(BaseModel):
    section_title: str
    narration: str
    evidence_ids: list[str] = Field(
        description="Ids of the numbered passages (for example P1) this section is based on."
    )


class GroundedLesson(BaseModel):
    covers_topic: bool = Field(
        description="False when the passages do not actually address what the learner asked for."
    )
    gap_note: str = Field(
        default="",
        description="When covers_topic is false: one sentence saying what the paper does not contain.",
    )
    title: str
    learning_objectives: list[str]
    introduction: str = Field(
        description="Says which part of the paper the video covers."
    )
    sections: list[GroundedSection]
    conclusion: str

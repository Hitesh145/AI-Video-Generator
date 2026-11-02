from pydantic import BaseModel, Field


class GroundedSection(BaseModel):
    section_title: str
    narration: str
    evidence_ids: list[str] = Field(
        description="Ids of the numbered passages (for example P1) this section is based on."
    )


class GroundedLesson(BaseModel):
    title: str
    learning_objectives: list[str]
    introduction: str = Field(
        description="Says which part of the paper the video covers."
    )
    sections: list[GroundedSection]
    conclusion: str

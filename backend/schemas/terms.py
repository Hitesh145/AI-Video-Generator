from pydantic import BaseModel, Field


class UndefinedTerm(BaseModel):
    term: str = Field(description="The technical term, symbol or named concept.")
    section_title: str = Field(description="The section where it is first used without explanation.")
    reason: str = Field(description="Why it counts as unexplained, in a few words.")


class TermReview(BaseModel):
    undefined_terms: list[UndefinedTerm]

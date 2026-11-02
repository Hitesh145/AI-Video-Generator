from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["supported", "unsupported", "contradicted", "framing"]


class SentenceVerdict(BaseModel):
    index: int = Field(description="Number of the sentence, as given.")
    verdict: Verdict
    quote: str = Field(
        default="",
        description="For supported: an exact quote copied from the passages that states the sentence's content.",
    )


class PartVerdicts(BaseModel):
    verdicts: list[SentenceVerdict]

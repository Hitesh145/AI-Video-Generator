from pydantic import BaseModel, Field


class KnowledgeFact(BaseModel):
    claim: str = Field(
        description="A concise factual claim that may be used in the lesson."
    )
    importance: str = Field(
        description="How important this fact is, such as high, medium, or low."
    )
    explanation: str = Field(
        description="Learner-friendly explanation of why the fact matters."
    )
    source_type: str = Field(
        description=(
            "Where this fact came from conceptually, such as established "
            "domain knowledge, textbook-level knowledge, or external research."
        )
    )


class KnowledgeGap(BaseModel):
    question: str = Field(
        description="A question or uncertainty that should be resolved later."
    )
    reason: str = Field(
        description="Why this gap matters for educational correctness."
    )


class KnowledgeBase(BaseModel):
    topic: str = Field(description="The topic covered by this knowledge base.")
    audience: str = Field(description="The intended learner level or audience.")
    key_concepts: list[str] = Field(
        description="Important concepts that should be covered in the lesson."
    )
    facts: list[KnowledgeFact] = Field(
        description="Factual claims that serve as lesson ground truth."
    )
    conflicting_information: list[str] = Field(
        default_factory=list,
        description="Potential conflicts, misconceptions, or disputed claims.",
    )
    gaps: list[KnowledgeGap] = Field(
        default_factory=list,
        description="Important missing information that should be researched later.",
    )

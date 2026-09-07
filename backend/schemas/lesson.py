from pydantic import BaseModel, Field


class LessonRequest(BaseModel):
    topic: str = Field(description="The subject the learner wants to understand.")
    audience: str = Field(description="The intended learner level or audience.") # can be lateral in future
    goal: str = Field(description="What the learner should understand by the end.")
    duration_minutes: int = Field(
        description="Approximate desired lesson duration in minutes."
    )
    teaching_depth: str = Field( 
        description="The depth of explanation, such as introductory or intermediate."
    )#same for this one, can be lateral in future
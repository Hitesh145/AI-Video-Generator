from pydantic import BaseModel, Field


class UserLessonRequest(BaseModel):
    request: str = Field(
        description="The user's request for an educational lesson."
    )


class LessonRequest(BaseModel):
    topic: str = Field(description="The subject the learner wants to understand.")
    audience: str = Field(description="The intended learner level or audience.")
    goal: str = Field(description="What the learner should understand by the end.")
    duration_minutes: int = Field(
        description="Approximate desired lesson duration in minutes."
    )
    teaching_depth: str = Field(
        description="The depth of explanation, such as introductory or intermediate."
    )

class LessonPlan(BaseModel):
    title: str = Field(
        description="The title of the educational lesson."
    )
    learning_objectives: list[str] = Field(
        description="The main things the learner should understand by the end."
    )
    sections: list[str] = Field(
        description="The ordered sequence of concepts to teach."
    )
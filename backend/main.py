from fastapi import FastAPI

from schemas.lesson import LessonRequest, UserLessonRequest
from services.llm_service import LLMService


app = FastAPI()

llm_service = LLMService()


@app.get("/")
def root():
    return {"message": "EduGen AI backend is running"}


@app.post("/lesson/analyze", response_model=LessonRequest)
def analyze_lesson(request: UserLessonRequest) -> LessonRequest:
    prompt = f"""
    Analyze the following educational request.

    User request:
    {request.request}

    Determine:
    - the topic
    - the intended audience
    - the learning goal
    - an approximate lesson duration in minutes
    - the teaching depth

    Return only the structured result matching the provided schema.
    """

    return llm_service.generate_structured(
        prompt,
        LessonRequest,
    )
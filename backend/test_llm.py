from schemas.lesson import LessonRequest
from services.llm_service import LLMService


def main() -> None:
    user_request = "Explain binary search to a beginner."

    prompt = f"""
    Analyze the following educational request.

    User request:
    {user_request}

    Extract:
    - the topic
    - the intended audience
    - the learning goal
    - an approximate lesson duration in minutes
    - the teaching depth

    Return only the structured result matching the provided schema.
    """

    llm = LLMService()

    lesson = llm.generate_structured(
        prompt,
        LessonRequest,
    )

    print(lesson)
    print()
    print(lesson.model_dump())


if __name__ == "__main__":
    main()
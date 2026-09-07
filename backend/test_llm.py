from schemas.lesson import LessonRequest
from services.llm_service import LLMService


def main() -> None:
    llm = LLMService()

    lesson = llm.generate_structured(
        """
        Analyze this user request for an educational video:

        "Explain neural networks to a beginner."

        Determine the topic, intended audience, learning goal,
        approximate duration in minutes, and teaching depth.
        """,
        LessonRequest,
    )

    print(lesson)
    print()
    print(lesson.model_dump())


if __name__ == "__main__":
    main()
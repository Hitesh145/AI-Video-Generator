from schemas.lesson import LessonPlan, LessonRequest
from services.llm_service import LLMService


def main() -> None:
    lesson_request = LessonRequest(
        topic="Binary search",
        audience="Beginner",
        goal="Understand the core concept and step-by-step process of binary search",
        duration_minutes=5,
        teaching_depth="Introductory",
    )

    prompt = f"""
    Create a structured educational lesson plan based on the following request.

    Topic: {lesson_request.topic}
    Audience: {lesson_request.audience}
    Goal: {lesson_request.goal}
    Duration: {lesson_request.duration_minutes} minutes
    Teaching depth: {lesson_request.teaching_depth}

    Design the lesson for the specified audience and depth.

    Create a logical teaching progression from foundational ideas
    to the final understanding.

    Return:
    - a clear lesson title
    - the main learning objectives
    - an ordered sequence of teaching sections

    Do not write the full narration.
    Focus only on the lesson structure.
    """

    llm = LLMService()

    lesson_plan = llm.generate_structured(
        prompt,
        LessonPlan,
    )

    print(lesson_plan)
    print()
    print(lesson_plan.model_dump())


if __name__ == "__main__":
    main()
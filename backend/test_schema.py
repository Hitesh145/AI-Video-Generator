from schemas.lesson import LessonRequest


lesson = LessonRequest(
    topic="Neural Networks",
    audience="beginner",
    goal="Understand the basic operation of neural networks",
    duration_minutes=4,
    teaching_depth="introductory",
)

print(lesson)
print(lesson.model_dump())
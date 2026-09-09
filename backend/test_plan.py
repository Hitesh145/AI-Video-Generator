from schemas.lesson import LessonPlan


lesson_plan = LessonPlan(
    title="Binary Search",
    learning_objectives=[
        "Understand what binary search is.",
        "Understand why the data must be sorted.",
        "Understand how each step eliminates half the search space.",
    ],
    sections=[
        "Introduction to binary search",
        "Why sorting matters",
        "Finding the middle element",
        "Eliminating half the search space",
        "Repeating the process",
        "Time complexity",
    ],
)

print(lesson_plan)
print()
print(lesson_plan.model_dump())
from fakes import FakeLLM
from schemas.lesson import LessonRequest
from services.lesson_planner_service import LessonPlannerService


def request(must_cover=("items", "closure")):
    return LessonRequest(topic="LR parsing", audience="student", goal="understand LR parsing", duration_minutes=8,
                         teaching_depth="intermediate", must_cover=list(must_cover))


def note(title, terms=(), purpose="Explain it.", example=""):
    return {"title": title, "purpose": purpose, "terms_to_define": list(terms), "example": example}


GOOD = {
    "title": "LR parsing", "learning_objectives": ["Know items"],
    "sections": ["What parsing is", "Items", "Closure"],
    "section_notes": [note("What parsing is", ["parser"]), note("Items", ["item"], example="A -> a . B"),
                      note("Closure", ["closure"])],
}


def plan(answers, lesson_request=None):
    llm = FakeLLM(answers)
    result = LessonPlannerService(llm).create_lesson_plan(lesson_request or request())
    return result, llm


def normalized(prompt):
    return " ".join(prompt.split())


def test_the_prompt_no_longer_asks_for_a_generic_structure_and_asks_for_terms_and_examples():
    _, llm = plan([GOOD])

    prompt = normalized(llm.prompts[0])
    assert "generic" not in prompt and "concept-independent" not in prompt
    assert "Order sections so that every term is explained before any later section uses it." in prompt
    assert "Give each section a one-sentence purpose, the terms it must define, and, for any procedure, one worked example." in prompt
    assert "Use about one section per minute of the lesson (at least 3, at most 12)." in prompt
    assert "Every item in must_cover must be defined in some section's terms_to_define." in prompt


def test_must_cover_is_listed_in_the_prompt():
    _, llm = plan([GOOD])

    assert "Must cover: items, closure" in normalized(llm.prompts[0])


def test_a_plan_with_notes_keeps_them_and_aligns_their_titles_with_the_sections():
    result, _ = plan([GOOD])

    assert [n.title for n in result.section_notes] == result.sections
    assert result.section_notes[1].terms_to_define == ["item"]


def test_notes_with_the_wrong_count_are_dropped():
    answer = dict(GOOD, section_notes=[note("What parsing is", ["parser"]), note("Items", ["items", "closure"])])

    result, _ = plan([answer])

    assert result.section_notes == [] and result.sections == GOOD["sections"]


def test_a_missing_must_cover_item_triggers_one_retry_naming_it():
    lacking = dict(GOOD, sections=["What parsing is", "Items", "Tables"],
                   section_notes=[note("What parsing is"), note("Items", ["items"]), note("Tables")])
    llm = FakeLLM([lacking, GOOD])

    result = LessonPlannerService(llm).create_lesson_plan(request())

    assert len(llm.prompts) == 2 and "You forgot to cover: closure" in llm.prompts[1]
    assert result.sections == GOOD["sections"]


def test_after_the_retry_the_plan_is_returned_even_if_an_item_is_still_missing():
    lacking = dict(GOOD, sections=["What parsing is", "Items", "Tables"],
                   section_notes=[note("What parsing is"), note("Items", ["items"]), note("Tables")])
    llm = FakeLLM([lacking, lacking])

    result = LessonPlannerService(llm).create_lesson_plan(request())

    assert len(llm.prompts) == 2 and result.sections == lacking["sections"]


def test_an_item_named_in_a_section_title_counts_as_covered_without_a_retry():
    answer = dict(GOOD, section_notes=[note("What parsing is"), note("Items"), note("Closure")])
    llm = FakeLLM([answer])

    LessonPlannerService(llm).create_lesson_plan(request())

    assert len(llm.prompts) == 1


def test_a_plan_without_notes_or_must_cover_still_works():
    llm = FakeLLM([{"title": "T", "learning_objectives": ["x"], "sections": ["A", "B", "C"]}])

    result = LessonPlannerService(llm).create_lesson_plan(request(must_cover=()))

    assert result.sections == ["A", "B", "C"] and result.section_notes == [] and len(llm.prompts) == 1

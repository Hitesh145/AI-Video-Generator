from fakes import FakeLLM
from schemas.knowledge import KnowledgeBase, KnowledgeFact
from schemas.lesson import LessonPlan, LessonRequest, SectionNote
from services.script_writer_service import ScriptWriterService


def script(*narrations, intro="Hello there.", conclusion="Bye."):
    return {
        "introduction": intro,
        "sections": [{"section_title": f"S{i}", "narration": n} for i, n in enumerate(narrations, start=1)],
        "conclusion": conclusion,
    }


def make_request(minutes=2, must_cover=()):
    return LessonRequest(topic="Binary Search", audience="beginner", goal="understand it",
                         duration_minutes=minutes, teaching_depth="introductory", must_cover=list(must_cover))


def make_plan(sections=("How",), notes=()):
    return LessonPlan(title="Binary Search", learning_objectives=["halve"], sections=list(sections),
                      section_notes=list(notes))


def prompt_for_a_lesson(**kwargs):
    llm = FakeLLM([script("It works."), script("It works.")])
    ScriptWriterService(llm).create_lesson_script(make_request(), make_plan(), **kwargs)
    return " ".join(llm.prompts[0].split())


def test_prompt_asks_for_short_drawable_sentences_with_a_concrete_example():
    prompt = prompt_for_a_lesson()

    assert "under about 22 words" in prompt
    assert "one idea per sentence" in prompt
    assert "can be drawn" in prompt
    assert "ONE concrete example with specific values" in prompt


def test_prompt_keeps_the_total_length_rule_and_the_closing_rule():
    prompt = prompt_for_a_lesson()

    assert "approximately 260 total words" in prompt
    assert "20. Return only the structured result" in prompt
    assert "14. Return only" not in prompt


def test_the_writer_prompt_contains_the_definition_rules_and_the_checklist():
    prompt = prompt_for_a_lesson()

    assert "Define every technical term in the sentence where it first appears: say what it is and what it is for." in prompt
    assert "Never skip a definition or a step to save words; length follows the requested duration, but completeness comes first." in prompt
    assert "Do not pad; every sentence must teach something." in prompt
    assert "Before answering, check: every term in must_cover is defined; every procedure has one worked example; no sentence relies on a term not yet explained." in prompt
    assert "enough to stay close to the requested duration" not in prompt


def test_the_writer_prompt_includes_section_notes_must_cover_and_reference_facts():
    llm = FakeLLM([script("It works."), script("It works.")])
    notes = [SectionNote(title="Items", purpose="Know what an item is.", terms_to_define=["item"], example="A -> a . B")]
    knowledge = KnowledgeBase(
        topic="t", audience="a", key_concepts=["closure"],
        facts=[KnowledgeFact(claim="An item marks how much of a rule has been seen.", importance="high",
                             explanation="e", source_type="textbook")],
    )

    ScriptWriterService(llm).create_lesson_script(
        make_request(must_cover=("items", "closure")), make_plan(("Items",), notes), knowledge_base=knowledge
    )

    prompt = " ".join(llm.prompts[0].split())
    assert "Must cover: items, closure" in prompt
    assert "purpose: Know what an item is." in prompt and "define: item" in prompt and "example: A -> a . B" in prompt
    assert "Reference facts you may rely on" in prompt and "An item marks how much of a rule has been seen." in prompt
    assert "closure" in prompt


def test_the_writer_works_without_a_knowledge_base_or_notes():
    prompt = prompt_for_a_lesson()

    assert "Reference facts" not in prompt and "Must cover: (nothing specific)" in prompt


def test_the_prompt_gives_a_word_budget_per_section():
    llm = FakeLLM([script("One."), script("One.")])
    ScriptWriterService(llm).create_lesson_script(make_request(minutes=8), make_plan(("A", "B", "C", "D")))

    prompt = " ".join(llm.prompts[0].split())
    assert "approximately 1040 total words" in prompt
    assert "about 234 words per section" in prompt          # (1040 - 10% for introduction and conclusion) / 4


LONG = "word " * 100


def test_a_script_far_below_the_target_length_is_rewritten_once_at_full_length():
    short, full = script("Too short."), script(LONG * 8)
    llm = FakeLLM([short, full])

    result = ScriptWriterService(llm).create_lesson_script(make_request(minutes=8), make_plan(("A",)))

    assert len(llm.prompts) == 2
    second = " ".join(llm.prompts[1].split())
    assert "Your previous script had" in second and "words; this lesson needs about 1040" in second
    assert "Too short." in second
    assert result.sections[0].narration == LONG * 8


def test_the_retry_is_used_only_if_it_is_longer():
    llm = FakeLLM([script("Short one."), script("Shorter.")])

    result = ScriptWriterService(llm).create_lesson_script(make_request(minutes=8), make_plan(("A",)))

    assert result.sections[0].narration == "Short one."


def test_a_script_close_to_the_target_is_not_rewritten():
    llm = FakeLLM([script(LONG * 8)])

    ScriptWriterService(llm).create_lesson_script(make_request(minutes=8), make_plan(("A",)))

    assert len(llm.prompts) == 1


def test_the_old_two_argument_call_still_works():
    llm = FakeLLM([script("It works. " * 100)])

    result = ScriptWriterService(llm).create_lesson_script(make_request(), make_plan())

    assert result.conclusion == "Bye."

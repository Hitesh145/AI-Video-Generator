from fakes import FakeLLM
from schemas.lesson import LessonPlan, LessonRequest
from services.script_writer_service import ScriptWriterService


def prompt_for_a_lesson():
    llm = FakeLLM([{
        "introduction": "Hello there.",
        "sections": [{"section_title": "How", "narration": "It works."}],
        "conclusion": "Bye.",
    }])
    request = LessonRequest(topic="Binary Search", audience="beginner", goal="understand it",
                            duration_minutes=2, teaching_depth="introductory")
    plan = LessonPlan(title="Binary Search", learning_objectives=["halve"], sections=["How"])

    ScriptWriterService(llm).create_lesson_script(request, plan)

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
    assert "17. Return only the structured result" in prompt
    assert "14. Return only" not in prompt

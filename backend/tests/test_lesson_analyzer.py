from fakes import FakeLLM
from schemas.lesson import LessonRequest, UserLessonRequest
from services.lesson_analyzer_service import LessonAnalyzerService

ANSWER = {
    "topic": "LR parsing", "audience": "student", "goal": "understand LR parsing", "duration_minutes": 8,
    "teaching_depth": "intermediate", "must_cover": ["items", "closure", "parsing table"],
}


def analyze(answer=ANSWER, text="Explain LR parsing in detail."):
    llm = FakeLLM([answer])
    request = LessonAnalyzerService(llm).analyze_lesson_request(UserLessonRequest(request=text))
    return request, " ".join(llm.prompts[0].split())


def test_lesson_request_must_cover_defaults_to_empty():
    request = LessonRequest(topic="t", audience="a", goal="g", duration_minutes=4, teaching_depth="introductory")

    assert request.must_cover == []


def test_the_analyzer_prompt_maps_detail_words_to_duration_and_asks_for_must_cover():
    _, prompt = analyze()

    assert 'A request for "detail", "in detail", "in depth", "thorough" or "complete" means about 8 minutes and a thorough explanation.' in prompt
    assert "A quick or brief request means 2 minutes. If nothing is said, use 4 minutes. Never more than 12." in prompt
    assert "teaching_depth must be one of: introductory, intermediate, advanced." in prompt
    assert "must_cover: list every term, concept or part the learner named, plus terms the topic cannot be understood without (at most 8)." in prompt


def test_the_analyzer_prompt_contains_the_learners_request_once():
    _, prompt = analyze(text="Explain LR parsing in detail.")

    assert prompt.count("Explain LR parsing in detail.") == 1


def test_the_analyzer_returns_the_models_must_cover_unchanged():
    request, _ = analyze()

    assert request.must_cover == ["items", "closure", "parsing table"]
    assert request.duration_minutes == 8


def test_an_answer_without_must_cover_is_still_accepted():
    answer = {k: v for k, v in ANSWER.items() if k != "must_cover"}

    request, _ = analyze(answer)

    assert request.must_cover == []

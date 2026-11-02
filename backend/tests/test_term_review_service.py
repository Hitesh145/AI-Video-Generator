import pytest
from fakes import FakeLLM
from schemas.lesson import LessonRequest, LessonScript, ScriptSection
from schemas.terms import TermReview, UndefinedTerm
from services.term_review_service import TermReviewService, missing_must_cover


def request(must_cover=("items", "closure")):
    return LessonRequest(topic="LR parsing", audience="student", goal="understand", duration_minutes=8,
                         teaching_depth="intermediate", must_cover=list(must_cover))


def script(*sections, intro="Welcome.", conclusion="Done."):
    return LessonScript(
        introduction=intro,
        sections=[ScriptSection(section_title=title, narration=text) for title, text in sections],
        conclusion=conclusion,
    )


BASE = script(("Items", "An item is a rule with a dot showing how much has been read."),
              ("Closure", "Closure adds every rule the parser could start next."))


def review(items):
    return {"undefined_terms": [{"term": t, "section_title": s, "reason": r} for t, s, r in items]}


def test_must_cover_terms_missing_from_the_script_are_found_without_the_model():
    lacking = script(("Items", "An item is a rule with a dot."))

    assert missing_must_cover(request(), lacking) == ["closure"]


def test_case_and_plural_variants_count_as_present():
    text = script(("A", "ITEM sets and Closures are explained here."))

    assert missing_must_cover(request(), text) == []


def test_the_model_list_and_the_missing_terms_are_combined_without_duplicates():
    llm = FakeLLM([review([("lookahead", "Closure", "used but never explained"), ("closure", "Closure", "x")])])
    lacking = script(("Items", "An item is a rule with a dot."), ("Parsing", "Then we use lookahead."))

    found = TermReviewService(llm).review(request(), lacking)

    assert [u.term for u in found] == ["lookahead", "closure"]
    assert found[1].reason == "x"


def test_a_model_only_term_and_a_never_mentioned_term_both_appear():
    llm = FakeLLM([review([("lookahead", "Parsing", "never explained")])])
    lacking = script(("Items", "An item is a rule with a dot."), ("Parsing", "Then we use lookahead."))

    found = TermReviewService(llm).review(request(), lacking)

    assert {u.term: u.reason for u in found} == {"lookahead": "never explained", "closure": "never mentioned"}


def test_the_review_prompt_is_strict_and_contains_the_script_once():
    llm = FakeLLM([review([])])

    TermReviewService(llm).review(request(), BASE)

    prompt = " ".join(llm.prompts[0].split())
    assert "complete beginner" in prompt and "without ever explaining" in prompt
    assert prompt.count("An item is a rule with a dot showing how much has been read.") == 1


def test_nothing_undefined_means_no_fix_call():
    llm = FakeLLM([review([])])

    fixed, remaining = TermReviewService(llm).improve(request(), BASE)

    assert fixed == BASE and remaining == [] and len(llm.prompts) == 1


def test_fix_is_accepted_when_titles_and_order_are_unchanged():
    better = script(("Items", "An item is a rule with a dot. The dot marks how much input was read."),
                    ("Closure", "Closure adds every rule the parser could start next. Lookahead is the next symbol."))
    llm = FakeLLM([review([("lookahead", "Closure", "never explained")]), better.model_dump()])

    fixed, remaining = TermReviewService(llm).improve(request(), BASE)

    assert fixed.sections[1].narration.endswith("Lookahead is the next symbol.") and remaining == []
    fix_prompt = " ".join(llm.prompts[1].split())
    assert "lookahead" in fix_prompt and "Keep every section title and the order of the sections" in fix_prompt


def test_fix_is_rejected_when_a_section_is_dropped_or_renamed_and_the_original_is_kept():
    dropped = script(("Items", "Only one section now."))
    renamed = script(("Items", "text"), ("Something else", "text"))
    for bad in (dropped, renamed):
        llm = FakeLLM([review([("lookahead", "Closure", "never explained")]), bad.model_dump()])

        fixed, _ = TermReviewService(llm).improve(request(), BASE)

        assert fixed == BASE


def test_a_must_cover_item_still_missing_after_the_fix_is_reported():
    still_missing = script(("Items", "An item is a rule with a dot."), ("Parsing", "Parsing uses a table."))
    llm = FakeLLM([review([]), still_missing.model_dump()])
    lacking = script(("Items", "An item is a rule with a dot."), ("Parsing", "Parsing uses a table."))

    fixed, remaining = TermReviewService(llm).improve(request(), lacking)

    assert remaining == ["closure"] and fixed == still_missing


def test_a_model_error_in_the_review_propagates():
    llm = FakeLLM([RuntimeError("model down")])

    with pytest.raises(RuntimeError, match="model down"):
        TermReviewService(llm).improve(request(), BASE)


def test_a_model_error_in_the_fix_propagates():
    llm = FakeLLM([review([("lookahead", "Closure", "never explained")]), RuntimeError("model down")])

    with pytest.raises(RuntimeError, match="model down"):
        TermReviewService(llm).improve(request(), BASE)


def test_the_schema_accepts_an_empty_review():
    assert TermReview(undefined_terms=[]).undefined_terms == []
    assert UndefinedTerm(term="t", section_title="s", reason="r").term == "t"

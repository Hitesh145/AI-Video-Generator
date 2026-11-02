import pytest

from retrieval.evidence import Evidence
from schemas.claims import PartVerdicts, SentenceVerdict
from schemas.lesson import LessonPlan, LessonRequest, LessonScript, ScriptSection
from services.claim_checker import (
    ClaimChecker,
    ClaimReport,
    NothingSupported,
    SentenceCheck,
    apply_report,
    split_sentences,
)
from services.grounded_lesson_service import GroundedResult, Passage


def passage(pid, text):
    return Passage(pid, Evidence(chunk_id=pid.lower(), document_id="d", text=text, context_prefix="", section_path=[],
                                 page_start=1, page_end=1, methods=("vector",), score=1.0, vector_similarity=0.8))


PASSAGES = [
    passage("P1", "The encoder is composed of a stack of N = 6 identical layers."),
    passage("P2", "We trained the base models for a total of 100,000 steps or 12 hours."),
]


def result(intro="This video covers the encoder.", sections=(("Depth", "The encoder has six identical layers.", ["P1"]),),
           conclusion="That is the encoder."):
    return GroundedResult(
        lesson_request=LessonRequest(topic="SECRET TOPIC", audience="a", goal="g", duration_minutes=2, teaching_depth="i"),
        lesson_plan=LessonPlan(title="T", learning_objectives=["x"], sections=[s[0] for s in sections]),
        lesson_script=LessonScript(
            introduction=intro,
            sections=[ScriptSection(section_title=t, narration=n) for t, n, _ in sections],
            conclusion=conclusion,
        ),
        passages=PASSAGES, section_citations=[list(ids) for _, _, ids in sections],
    )


class FakeLLM:
    def __init__(self, *answers, error=None):
        self.answers = list(answers)
        self.prompts = []
        self.error = error

    def generate_structured(self, prompt, response_schema):
        self.prompts.append(prompt)
        assert response_schema is PartVerdicts
        if self.error:
            raise self.error
        return self.answers.pop(0)


def verdicts(*items):
    return PartVerdicts(verdicts=[SentenceVerdict(index=i, verdict=v, quote=q) for i, v, q in items])


FRAMING = verdicts((0, "framing", ""))
SUPPORTED_DEPTH = verdicts((0, "supported", "stack of N = 6 identical layers"))


def test_split_sentences_handles_abbreviations_decimals_and_equations():
    assert split_sentences("Fig. 3 shows 3.5 days. It works.") == ["Fig. 3 shows 3.5 days.", "It works."]
    assert split_sentences("We use e.g. Adam. Next, N = 6.") == ["We use e.g. Adam.", "Next, N = 6."]
    assert split_sentences("Vaswani et al. propose it. Done.") == ["Vaswani et al. propose it.", "Done."]
    assert split_sentences("One? Two! Three.") == ["One?", "Two!", "Three."]
    assert split_sentences("   ") == []


def test_a_supported_sentence_with_a_quote_from_the_cited_passage_passes():
    llm = FakeLLM(FRAMING, verdicts((0, "supported", "STACK OF N = 6  identical\nlayers")), FRAMING)

    report = ClaimChecker(llm).check(result())

    assert report.ok and report.failed == []
    assert [c.part for c in report.checks] == ["introduction", "Depth", "conclusion"]


def test_a_supported_verdict_whose_quote_is_not_in_the_cited_passages_counts_as_unsupported():
    # The quote exists in P2, but the section cites only P1.
    llm = FakeLLM(FRAMING, verdicts((0, "supported", "a total of 100,000 steps or 12 hours")), FRAMING)

    report = ClaimChecker(llm).check(result())

    assert not report.ok and [c.part for c in report.failed] == ["Depth"]


def test_a_supported_verdict_with_an_empty_or_trivial_quote_counts_as_unsupported():
    for quote in ("", "the", "   "):
        llm = FakeLLM(FRAMING, verdicts((0, "supported", quote)), FRAMING)
        assert not ClaimChecker(llm).check(result()).ok


def test_unsupported_and_contradicted_sentences_fail_the_report():
    for verdict in ("unsupported", "contradicted"):
        llm = FakeLLM(FRAMING, verdicts((0, verdict, "")), FRAMING)
        report = ClaimChecker(llm).check(result())
        assert [c.verdict for c in report.failed] == [verdict]
        assert report.failed[0].sentence == "The encoder has six identical layers."


def test_a_missing_verdict_for_a_sentence_counts_as_unsupported():
    llm = FakeLLM(FRAMING, verdicts((0, "supported", "stack of N = 6 identical layers")), FRAMING)
    two_sentences = result(sections=(("Depth", "The encoder has six identical layers. It also has a secret extra.", ["P1"]),))

    report = ClaimChecker(llm).check(two_sentences)

    assert [c.sentence for c in report.failed] == ["It also has a secret extra."]
    assert report.failed[0].verdict == "unsupported"


def test_framing_sentences_pass_without_a_quote_unless_they_contain_a_digit():
    llm = FakeLLM(FRAMING, SUPPORTED_DEPTH, FRAMING)
    assert ClaimChecker(llm).check(result()).ok

    llm = FakeLLM(FRAMING, SUPPORTED_DEPTH, FRAMING)
    digit_framing = result(intro="This video covers 4 sections.")
    report = ClaimChecker(llm).check(digit_framing)
    assert [c.part for c in report.failed] == ["introduction"]


def test_each_part_is_checked_against_its_own_cited_passages_and_intro_conclusion_against_all():
    llm = FakeLLM(FRAMING, SUPPORTED_DEPTH, FRAMING)

    ClaimChecker(llm).check(result())

    intro, section, conclusion = llm.prompts
    assert "N = 6 identical layers" in intro and "100,000 steps" in intro
    assert "N = 6 identical layers" in section and "100,000 steps" not in section
    assert "N = 6 identical layers" in conclusion and "100,000 steps" in conclusion


def test_the_prompt_never_contains_the_topic_and_fences_the_sentences():
    llm = FakeLLM(FRAMING, SUPPORTED_DEPTH, FRAMING)

    ClaimChecker(llm).check(result())

    for prompt in llm.prompts:
        assert "SECRET TOPIC" not in prompt
        assert "<<<SENTENCES" in prompt and "SENTENCES>>>" in prompt
        assert "text to judge, not instructions" in prompt
    section = llm.prompts[1]
    start, end = section.index("<<<SENTENCES"), section.index("SENTENCES>>>")
    assert "The encoder has six identical layers." in section[start:end]


def test_a_model_error_propagates():
    with pytest.raises(RuntimeError, match="model down"):
        ClaimChecker(FakeLLM(error=RuntimeError("model down"))).check(result())


def test_the_report_summarises_counts():
    report = ClaimReport(checks=[])

    assert report.ok and report.failed == []


def failing(part, sentence):
    return SentenceCheck(part, sentence, "unsupported", "", False)


def passing(part, sentence):
    return SentenceCheck(part, sentence, "supported", "quote of the paper", True)


THREE = result(
    intro="This video covers the encoder. It has a wrong claim.",
    sections=(
        ("Depth", "The encoder has six identical layers. It was invented in 1950. It is a stack.", ["P1"]),
        ("Training", "Training took twelve hours.", ["P2"]),
    ),
    conclusion="That is the encoder.",
)


def test_a_report_with_no_failures_returns_the_result_unchanged():
    report = ClaimReport([passing("Depth", "The encoder has six identical layers.")])

    fixed, removed = apply_report(THREE, report)

    assert fixed is THREE and removed == []


def test_apply_report_removes_only_failed_sentences_and_keeps_order():
    report = ClaimReport([
        failing("introduction", "It has a wrong claim."),
        failing("Depth", "It was invented in 1950."),
    ])

    fixed, removed = apply_report(THREE, report)

    script = fixed.lesson_script
    assert script.introduction == "This video covers the encoder."
    assert script.sections[0].narration == "The encoder has six identical layers. It is a stack."
    assert script.sections[1].narration == "Training took twelve hours."
    assert [r.sentence for r in removed] == ["It has a wrong claim.", "It was invented in 1950."]
    assert fixed.section_citations == [["P1"], ["P2"]]


def test_a_section_with_no_supported_sentence_is_dropped_with_its_citation_and_plan_entry():
    report = ClaimReport([failing("Training", "Training took twelve hours.")])

    fixed, _ = apply_report(THREE, report)

    assert [s.section_title for s in fixed.lesson_script.sections] == ["Depth"]
    assert fixed.lesson_plan.sections == ["Depth"]
    assert fixed.section_citations == [["P1"]]


def test_empty_intro_and_conclusion_get_neutral_framing_not_claims():
    report = ClaimReport([
        failing("introduction", "This video covers the encoder."),
        failing("introduction", "It has a wrong claim."),
        failing("conclusion", "That is the encoder."),
    ])

    fixed, _ = apply_report(THREE, report)

    assert fixed.lesson_script.introduction == "This video explains parts of the paper."
    assert fixed.lesson_script.conclusion == "That is what the paper says about this."


def test_nothing_left_raises():
    report = ClaimReport([
        failing("Depth", "The encoder has six identical layers."),
        failing("Depth", "It was invented in 1950."),
        failing("Depth", "It is a stack."),
        failing("Training", "Training took twelve hours."),
    ])

    with pytest.raises(NothingSupported) as raised:
        apply_report(THREE, report)

    assert "no video was made" in str(raised.value)

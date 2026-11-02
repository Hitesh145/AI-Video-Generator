import json

import pytest

from evaluation.metrics import ThresholdSuggestion
from evaluation.questions import Question, QuestionSet
from evaluation.run import Context, main
from evaluation.runner import evaluate, render_markdown
from retrieval.evidence import Evidence


def ev(chunk_id, text, similarity=None, score=None):
    return Evidence(
        chunk_id=chunk_id, document_id="d", text=text, context_prefix="", section_path=["S"],
        page_start=1, page_end=1, methods=("vector",) if similarity is not None else ("keyword",),
        score=score if score is not None else (similarity or 0.0), vector_similarity=similarity,
    )


def answerable(question_id, phrase, category="method"):
    return Question(id=question_id, kind="answerable", category=category, question=f"Question {question_id}?", answer_phrases=[phrase])


def absent(question_id):
    return Question(id=question_id, kind="absent", category="absent", question=f"Question {question_id}?")


class FakeSearcher:
    """Returns canned evidence per (question text, mode) and records every call."""

    def __init__(self, canned):
        self.canned = canned
        self.calls = []

    def search(self, user_id, document_id, query, k=8, mode="hybrid"):
        self.calls.append((query, mode, k))
        return list(self.canned.get((query, mode), []))


# q1 is found at rank 1, q2 at rank 3, q3 nowhere; q4 is a question the paper cannot answer
QUESTION_SET = QuestionSet(paper="demo", questions=[
    answerable("q1", "alpha phrase", "method"),
    answerable("q2", "beta phrase", "results"),
    answerable("q3", "gamma phrase", "method"),
    absent("q4"),
])
CANNED = {
    ("Question q1?", "vector"): [ev("a", "the alpha phrase here", 0.90), ev("b", "other", 0.5)],
    ("Question q2?", "vector"): [ev("c", "x", 0.8), ev("d", "y", 0.7), ev("e", "has the beta phrase", 0.6)],
    ("Question q3?", "vector"): [ev("f", "nothing relevant", 0.55)],
    ("Question q4?", "vector"): [ev("g", "unrelated text", 0.30)],
}


def run(modes=("vector",), k_values=(1, 3, 5), canned=None):
    searcher = FakeSearcher(CANNED if canned is None else canned)
    return searcher, evaluate(searcher, "u", "d", QUESTION_SET, modes=modes, k_values=k_values)


def test_recall_and_mrr_are_computed_per_mode():
    _, result = run(k_values=(1, 3))

    summary = result.summaries[0]
    assert summary.mode == "vector"
    assert summary.recall_at == {1: pytest.approx(1 / 3), 3: pytest.approx(2 / 3)}
    assert summary.mrr == pytest.approx((1 + 1 / 3 + 0) / 3)


def test_absent_questions_never_count_against_recall_but_feed_the_threshold():
    _, result = run()

    assert (result.answerable_count, result.absent_count) == (3, 1)
    assert result.summaries[0].recall_at[5] == pytest.approx(2 / 3)       # q4 changes nothing
    suggestion = result.threshold_by_mode["vector"]
    assert isinstance(suggestion, ThresholdSuggestion)
    assert 0.30 < suggestion.threshold < 0.55 and suggestion.accuracy == 1.0


def test_recall_by_category_groups_answerable_questions():
    _, result = run(k_values=(5,))

    assert result.category_k == 5
    assert result.summaries[0].recall_by_category == {"method": pytest.approx(0.5), "results": pytest.approx(1.0)}


def test_searching_uses_the_largest_k_and_each_requested_mode_only():
    searcher, _ = run(modes=("hybrid",), k_values=(1, 3, 8), canned={})

    assert {(mode, k) for _, mode, k in searcher.calls} == {("hybrid", 8)}
    assert len(searcher.calls) == 4


def test_a_question_with_no_evidence_has_rank_none_and_score_none():
    _, result = run(modes=("hybrid",), canned={})

    first = result.questions[0]
    assert first.rank_by_mode["hybrid"] is None and first.best_score_by_mode["hybrid"] is None


def test_the_coverage_score_of_a_hybrid_search_is_the_best_vector_similarity_not_the_rank_score():
    canned = {("Question q1?", "hybrid"): [ev("a", "x", similarity=0.42, score=0.0328), ev("b", "y", score=0.0160)]}
    _, result = run(modes=("hybrid",), canned=canned)

    assert result.questions[0].best_score_by_mode["hybrid"] == pytest.approx(0.42)


def test_the_markdown_report_lists_modes_tables_thresholds_and_missed_questions():
    _, result = run(modes=("vector", "hybrid"), k_values=(1, 3, 5))

    text = render_markdown([result])

    assert "| vector |" in text and "| hybrid |" in text
    assert "recall@5" in text and "MRR" in text
    assert "threshold" in text.lower()
    assert "baseline" in text.lower() and "kept" in text.lower()   # accuracy is never shown without its floor
    assert "q3" in text                       # nobody found it
    assert "demo" in text


# ---------------------------------------------------------------- command line
def write_question_file(directory, name="demo.json", phrase="alpha phrase"):
    path = directory / name
    path.write_text(json.dumps({"paper": "demo", "questions": [
        {"id": "q1", "kind": "answerable", "category": "method", "question": "Question q1?", "answer_phrases": [phrase]},
        {"id": "q4", "kind": "absent", "category": "absent", "question": "Question q4?", "answer_phrases": []},
    ]}), encoding="utf-8")
    return path


def make_context(paper_text="the alpha phrase is here"):
    return Context(
        user_id="u", storage=None, ingestor=None,
        searcher=FakeSearcher({("Question q1?", "vector"): [ev("a", "the alpha phrase here", 0.9)],
                               ("Question q4?", "vector"): [ev("g", "unrelated", 0.2)]}),
        ensure_document=lambda key, path: f"doc-{key}",
        paper_passages=lambda document_id: [paper_text],
    )


def cli(tmp_path, argv, context=None, papers=("demo",)):
    questions = tmp_path / "questions"
    questions.mkdir(exist_ok=True)
    if not (questions / "demo.json").exists():
        write_question_file(questions)
    fetched = {key: tmp_path / f"{key}.pdf" for key in papers}
    return main(
        argv + ["--questions-dir", str(questions), "--out", str(tmp_path / "report.md")],
        context_factory=lambda email: context or make_context(),
        fetcher=lambda: fetched,
    )


def test_the_command_line_writes_a_report_and_succeeds(tmp_path, capsys):
    assert cli(tmp_path, ["--modes", "vector"]) == 0

    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "| vector |" in report
    assert "recall@5" in capsys.readouterr().out


def test_validation_problems_stop_the_run_before_any_scoring(tmp_path, capsys):
    status = cli(tmp_path, ["--modes", "vector"], context=make_context(paper_text="a text without the phrase"))

    assert status == 1
    assert "q1" in capsys.readouterr().out
    assert not (tmp_path / "report.md").exists()


def test_validate_only_checks_files_and_does_not_run_the_evaluation(tmp_path, capsys):
    assert cli(tmp_path, ["--validate-only"]) == 0
    assert not (tmp_path / "report.md").exists()
    assert "no problems" in capsys.readouterr().out.lower()


def test_an_unknown_paper_key_is_an_error(tmp_path, capsys):
    assert cli(tmp_path, ["--papers", "nonexistent"]) == 2
    assert "nonexistent" in capsys.readouterr().out

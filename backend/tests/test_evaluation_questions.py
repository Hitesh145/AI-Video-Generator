import json

import pytest

from evaluation.questions import Question, QuestionSet, load_question_set
from evaluation.validation import find_problems


def answerable(question_id, phrases=("multi-head attention",)):
    return {"id": question_id, "kind": "answerable", "category": "method",
            "question": "How does it work?", "answer_phrases": list(phrases)}


def absent(question_id):
    return {"id": question_id, "kind": "absent", "category": "absent",
            "question": "Something the paper never discusses?", "answer_phrases": []}


def write_json(tmp_path, data, name="questions.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_valid_file_loads(tmp_path):
    path = write_json(tmp_path, {"paper": "p", "questions": [answerable("q1"), answerable("q2"), absent("q3")]})

    loaded = load_question_set(path)

    assert loaded.paper == "p"
    assert [q.kind for q in loaded.questions] == ["answerable", "answerable", "absent"]


def test_answerable_questions_need_a_phrase_and_absent_ones_must_have_none(tmp_path):
    no_phrase = write_json(tmp_path, {"paper": "p", "questions": [{**answerable("q1"), "answer_phrases": []}]}, "a.json")
    with pytest.raises(ValueError, match="q1"):
        load_question_set(no_phrase)
    blank = write_json(tmp_path, {"paper": "p", "questions": [{**answerable("q2"), "answer_phrases": ["  "]}]}, "b.json")
    with pytest.raises(ValueError, match="q2"):
        load_question_set(blank)
    with_phrase = write_json(tmp_path, {"paper": "p", "questions": [{**absent("q3"), "answer_phrases": ["x"]}]}, "c.json")
    with pytest.raises(ValueError, match="q3"):
        load_question_set(with_phrase)


def test_duplicate_ids_are_rejected(tmp_path):
    path = write_json(tmp_path, {"paper": "p", "questions": [answerable("q1"), answerable("q1")]})

    with pytest.raises(ValueError, match="q1"):
        load_question_set(path)


def test_a_missing_or_malformed_file_names_itself_in_the_error(tmp_path):
    with pytest.raises(ValueError, match="nope.json"):
        load_question_set(tmp_path / "nope.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="broken.json"):
        load_question_set(broken)


QUESTION_SET = QuestionSet(paper="p", questions=[
    Question(id="q1", kind="answerable", category="method", question="Scaling?", answer_phrases=["scaled dot-product attention"]),
    Question(id="q2", kind="answerable", category="method", question="Heads?", answer_phrases=["multi-head attention", "attention heads"]),
])


def test_find_problems_names_every_phrase_that_is_not_in_the_paper():
    problems = find_problems(QUESTION_SET, ["Scaled dot-product attention divides by sqrt(d_k)."])

    assert len(problems) == 2
    assert any("q2" in p and "multi-head attention" in p for p in problems)
    assert any("q2" in p and "attention heads" in p for p in problems)


def test_find_problems_is_clean_when_every_phrase_occurs():
    text = "Scaled dot-product attention ... Multi-Head\nAttention uses 8 attention heads."

    assert find_problems(QUESTION_SET, [text]) == []


def test_find_problems_ignores_absent_questions():
    only_absent = QuestionSet(paper="p", questions=[Question(id="a1", kind="absent", category="absent", question="Anything?")])

    assert find_problems(only_absent, ["any text at all"]) == []


def test_find_problems_rejects_a_phrase_that_straddles_two_passages():
    # Scoring looks inside one passage at a time, so a phrase split by a passage boundary could never be found.
    passages = ["Scaled dot-product", "attention divides by sqrt(d_k). Multi-head attention and attention heads."]

    problems = find_problems(QUESTION_SET, passages)

    assert len(problems) == 1 and "q1" in problems[0]

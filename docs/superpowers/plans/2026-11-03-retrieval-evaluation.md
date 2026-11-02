# Paper Search and Its Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the search that finds the right passages of one stored paper for a question, and measure how well it works on real papers, so the decisions for video generation (which retrieval method, what counts as "not in the paper") rest on numbers.

**Architecture:** A `retrieval` package offers three ways to search one paper: by meaning (the existing vector search), by words (new PostgreSQL full-text search over the passages) and a hybrid that merges both with reciprocal rank fusion. An `evaluation` package holds hand-checked question files for three real papers, pure scoring functions, a runner that compares the methods and a command-line tool that prints a report. Nothing here generates a video; this is project 3's first step, as the design prescribes ("measure retrieval before building generation").

**Tech Stack:** PostgreSQL full-text search (`to_tsvector`, GIN index), existing pgvector search and Gemini embeddings, Python, pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-paper-videos-design.md` (section 6 "How a video is made", section 10 "Order of work" and its decision rule). The whole-paper-versus-retrieval comparison needs generated answers, so it belongs to the next plan; this plan measures retrieval only, and measures what the "topic not in the paper" popup needs (a score that separates covered from uncovered topics).

## Global Constraints

- Search is always inside **one paper owned by the caller** (spec sections 3 and 7). Another user's or another paper's passages must never be returned, even when they are more similar.
- Retrieval settings stay configurable and each method is testable alone (spec section 6): reciprocal rank fusion constant 60, 20 candidates per method, 8 results by default.
- Backend tests run from `backend/`; default `python -m pytest -q` excludes `slow`; the full run is `python -m pytest -q -m "slow or not slow"`. Integration tests need `RAG_TEST_DATABASE_URL`: the same URL as `RAG_DATABASE_URL` with the database name `edugen_rag_test` (it exists on the owner's server); set it in the shell, never in `.env`.
- Downloaded papers are untrusted data: save each in its own folder under `backend/data/eval_papers/` (git-ignored), never run or import anything from them, and only hand them to the existing Docling parser.
- Never stage `backend/IJRTI2304061.pdf`, `backend/IJRTI2304061_assets/`, `backend/rendering/__init__.py`, `backend/output/**` or anything under `backend/data/`. Question files and the written results summary are committed; PDFs are not.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Stage files by name only.

## Review Focus

1. **A typo in a question file:** every phrase listed as an expected answer must occur in the paper's text; validation fails loudly and names the question and phrase, instead of silently scoring a miss. Tested in Task 4 and enforced in Task 6.
2. **Questions the paper cannot answer:** they never count against recall; they are reported separately with the score distribution that lets us choose the "not in this paper" threshold. Tested in Task 4 and 5.
3. **Isolation:** a search for user A in paper X never returns passages of user B or of paper Y, even when they match better. Tested in Task 2 and 3 against real PostgreSQL.
4. **Odd queries:** an empty or whitespace query, only stop words, punctuation and quotes, something that looks like SQL (`'; DROP TABLE rag_documents; --`) and a 5,000-character query do not crash and cannot inject; keyword search returns nothing for a query with no usable words. Tested in Task 2 and 3.
5. **Re-running the evaluation:** a paper that is already stored is not parsed again and its passages are not embedded again (no repeated Gemini cost). Tested in Task 5.

---

## File Structure

**Create**
- `backend/retrieval/__init__.py`, `evidence.py` (Evidence), `fusion.py` (reciprocal_rank_fusion), `search.py` (PaperSearcher).
- `backend/alembic/versions/0004_passage_text_index.py`.
- `backend/evaluation/__init__.py`, `questions.py` (schema + loader), `metrics.py` (pure scoring), `validation.py`, `ingest.py` (store-and-embed a paper once), `runner.py` (compare methods, markdown report), `fetch_papers.py`, `run.py` (command-line entry), `papers.json` (manifest), `data/attention.json`, `data/resnet.json`, `data/sample.json` (question files).
- Tests: `tests/test_fusion.py`, `tests/test_keyword_search.py`, `tests/test_paper_searcher.py`, `tests/test_evaluation_metrics.py`, `tests/test_evaluation_questions.py`, `tests/test_evaluation_runner.py`, `tests/test_evaluation_ingest.py`.
- `docs/superpowers/results/2026-11-03-retrieval-evaluation.md` (the committed findings, Task 7).

**Modify**
- `backend/rag/storage_schema.py` (KeywordHit), `backend/rag/pg_repository.py` (keyword_search), `backend/data/.gitignore` (ignore `eval_papers/`).

## Calls made while planning (not in the spec)

- **Relevance is decided by text, not by hand-picked chunk ids.** A question lists short phrases that the answer passage must contain; a retrieved passage counts as relevant if its normalised text contains any of them. This survives re-chunking and needs no labelling tool. The cost: the question writer must pick distinctive phrases, which validation checks against the paper's text.
- **Three papers:** the owner's light sample paper (`IJRTI2304061.pdf`, local only), "Attention Is All You Need" (arXiv 1706.03762, equations and tables) and "Deep Residual Learning for Image Recognition" (arXiv 1512.03385, figures). About 15 questions each: 12 answerable across motivation, method, definitions/equations, tables/figures, results, comparison and limitations, plus 3 the paper cannot answer.
- **Keyword search ORs the query's words** (after removing stop words) and ranks with `ts_rank_cd`, because AND-ing every word of a natural question finds nothing.
- **An evaluation account** (`evaluation@edugen.local`, random unused password) is created in the development database to own the evaluation copies; they never appear in anyone's library.
- **Not in this plan:** context expansion with neighbouring passages, section-hierarchy search, cross-reference following and reranking. The design says to add those only if these measurements show they are needed.

---

### Task 1: Evidence and reciprocal rank fusion

**Files:**
- Create: `backend/retrieval/__init__.py`, `backend/retrieval/evidence.py`, `backend/retrieval/fusion.py`, `backend/tests/test_fusion.py`

**Interfaces:**
- Produces (`retrieval.evidence`): frozen dataclass `Evidence(chunk_id: str, document_id: str, text: str, context_prefix: str, section_path: list[str], page_start: int | None, page_end: int | None, methods: tuple[str, ...], score: float, vector_similarity: float | None)`. `methods` lists which searches found it (`"vector"`, `"keyword"`); `score` is the value results are ordered by; `vector_similarity` is cosine similarity (1 - distance) when the vector search returned it, else `None`.
- Produces (`retrieval.fusion`): `reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]`: each item's score is the sum over rankings of `1 / (k + rank)` with 1-based ranks; returns `(item, score)` best first; ties keep the order in which the item first appeared across the rankings.

- [ ] **Step 1: Write the failing tests** in `tests/test_fusion.py`:

```python
def test_an_item_found_by_both_rankings_beats_items_found_by_one():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["d", "b", "e"]])
    assert [item for item, _ in fused][0] == "b"

def test_scores_are_the_sum_of_one_over_k_plus_rank():
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60))
    assert fused["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)

def test_every_item_appears_exactly_once():
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "a"], ["a"]])
    assert sorted(item for item, _ in fused) == ["a", "b", "c"]

def test_ties_keep_first_seen_order():
    assert [item for item, _ in reciprocal_rank_fusion([["x", "y"]], k=60)] == ["x", "y"]
    assert [item for item, _ in reciprocal_rank_fusion([["p"], ["q"]])] == ["p", "q"]

def test_empty_inputs_give_nothing():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []

def test_a_duplicate_inside_one_ranking_counts_once_at_its_best_rank():
    fused = dict(reciprocal_rank_fusion([["a", "a", "b"]]))
    assert fused["a"] == pytest.approx(1 / 61)

def test_k_must_be_positive():
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)
```

- [ ] **Step 2: Run to verify it fails.** `python -m pytest tests/test_fusion.py -q` -> collection error `ModuleNotFoundError: No module named 'retrieval'`.
- [ ] **Step 3: Implement** `Evidence` and `reciprocal_rank_fusion` exactly as specified (pure functions, no I/O).
- [ ] **Step 4: Run to verify it passes.** `python -m pytest tests/test_fusion.py -q` -> 7 passed.
- [ ] **Step 5: Commit**

```bash
git add retrieval/__init__.py retrieval/evidence.py retrieval/fusion.py tests/test_fusion.py
git commit -m "Add the evidence type and reciprocal rank fusion" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Keyword search over a paper's passages

**Files:**
- Create: `backend/alembic/versions/0004_passage_text_index.py`, `backend/tests/test_keyword_search.py`
- Modify: `backend/rag/storage_schema.py`, `backend/rag/pg_repository.py`

**Interfaces:**
- Produces (`rag.storage_schema`): frozen dataclass `KeywordHit(chunk_id: str, document_id: str, text: str, context_prefix: str, section_path: list[str], page_start: int | None, page_end: int | None, rank_score: float)`.
- Produces (`PostgresRAGRepository`): `keyword_search(user_id: str, document_id: str, query: str, limit: int = 20) -> list[KeywordHit]`. Only passages of `document_id` that belong to `user_id`; best match first; `[]` when the query has no usable words or `document_id` is not the user's. The query's words (letters and digits only, lower-cased, stop words dropped by PostgreSQL's English configuration) are joined with `|` and matched against `to_tsvector('english', context_prefix || ' ' || text)`; ranked by `ts_rank_cd`. `limit` must be between 1 and 100 (else `ValueError`).
- Migration `0004_passage_text_index` (revision `0004_passage_text_index`, down_revision `0003_papers`) creates `ix_rag_chunks_fts`, a GIN index on exactly that expression; `downgrade` drops it.

- [ ] **Step 1: Write the failing integration tests** in `tests/test_keyword_search.py` (module-level skip without `RAG_TEST_DATABASE_URL`, marked `integration`; reuse the `migrated_engine` fixture by importing it from `test_postgres_integration`; build documents with `make_fixture`-style chunks that have distinct texts, e.g. "Binary search halves the sorted array each step", "Photosynthesis converts light into chemical energy", "The learning rate controls the step size of gradient descent"):

```python
def test_the_passage_that_mentions_the_words_ranks_first(...):
    hits = repo.keyword_search(owner, document_id, "how does binary search halve the array")
    assert hits[0].text.startswith("Binary search halves")

def test_questions_are_matched_word_by_word_not_as_one_phrase(...):
    assert repo.keyword_search(owner, document_id, "What is the learning rate used for?")

def test_a_query_with_no_usable_words_returns_nothing(...):
    for query in ["", "   ", "the of and", "?!...", "'' \"\""]:
        assert repo.keyword_search(owner, document_id, query) == []

def test_sql_looking_and_very_long_queries_are_just_words(...):
    assert isinstance(repo.keyword_search(owner, document_id, "'; DROP TABLE rag_documents; --"), list)
    assert isinstance(repo.keyword_search(owner, document_id, "binary " * 800), list)
    # and the table still exists afterwards: another search works

def test_only_the_callers_passages_in_the_named_paper_are_searched(...):
    # user B stores a paper with a passage that matches the query better;
    # user A's search in A's paper never returns it; A searching with B's document_id returns []
    # a second paper of user A that also matches is not returned when searching the first

def test_limit_is_validated_and_respected(...):
    with pytest.raises(ValueError): repo.keyword_search(owner, document_id, "binary", limit=0)
    assert len(repo.keyword_search(owner, document_id, "step", limit=1)) <= 1

def test_the_search_uses_the_index_expression(...):
    # EXPLAIN of the exact query mentions ix_rag_chunks_fts when enable_seqscan is off
```

- [ ] **Step 2: Run to verify it fails.** With `RAG_TEST_DATABASE_URL` set: `python -m pytest tests/test_keyword_search.py -q` -> failures (`AttributeError: ... keyword_search` / missing index).
- [ ] **Step 3: Implement** the migration, `KeywordHit` and `keyword_search` (SQLAlchemy `text()` with bound parameters only; build the OR-query by splitting the input on non-alphanumerics, never by interpolating user text into SQL).
- [ ] **Step 4: Run to verify it passes.** `python -m pytest tests/test_keyword_search.py tests/test_postgres_integration.py -q` -> all pass.
- [ ] **Step 5: Commit**

```bash
git add alembic/versions/0004_passage_text_index.py rag/storage_schema.py rag/pg_repository.py tests/test_keyword_search.py
git commit -m "Add full-text keyword search over one paper's passages" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The paper searcher (vector, keyword, hybrid)

**Files:**
- Create: `backend/retrieval/search.py`, `backend/tests/test_paper_searcher.py`

**Interfaces:**
- Consumes: `Evidence`, `reciprocal_rank_fusion` (Task 1); `KeywordHit` and `keyword_search` (Task 2); the existing `RAGStorageService.search_similar(user_id, query, limit, document_id) -> list[SimilarityHit]`.
- Produces (`retrieval.search`): `SearchMode = Literal["vector", "keyword", "hybrid"]`; `PaperSearcher(vector_search: Callable[[str, str, str, int], list[SimilarityHit]], keyword_search: Callable[[str, str, str, int], list[KeywordHit]], candidates: int = 20, rrf_k: int = 60)` with
  `search(user_id: str, document_id: str, query: str, k: int = 8, mode: SearchMode = "hybrid") -> list[Evidence]` (arguments of the callables are `(user_id, document_id, query, limit)`; a blank query returns `[]` without calling either search; `k` is clamped to 1..50; `vector` mode scores by cosine similarity and keyword mode by `rank_score`; hybrid scores are the fused values; duplicates by `chunk_id` are merged and `methods` records every search that found the passage);
  `build_paper_searcher(storage: RAGStorageService, repository: PostgresRAGRepository) -> PaperSearcher`.

- [ ] **Step 1: Write the failing tests** in `tests/test_paper_searcher.py` with plain-Python fakes for the two searches (lists of `SimilarityHit` / `KeywordHit`):

```python
def test_vector_mode_orders_by_similarity_and_reports_it():
    results = searcher.search("u", "d", "q", k=2, mode="vector")
    assert [e.chunk_id for e in results] == ["c1", "c2"]
    assert results[0].methods == ("vector",) and results[0].vector_similarity == pytest.approx(0.9)
    assert keyword_calls == []

def test_keyword_mode_never_calls_the_vector_search():
    results = searcher.search("u", "d", "q", mode="keyword")
    assert vector_calls == [] and all(e.methods == ("keyword",) for e in results)

def test_hybrid_merges_duplicates_and_records_both_methods():
    results = searcher.search("u", "d", "q", mode="hybrid")
    shared = next(e for e in results if e.chunk_id == "c2")
    assert shared.methods == ("vector", "keyword") and shared.vector_similarity is not None
    assert len({e.chunk_id for e in results}) == len(results)

def test_hybrid_puts_a_passage_found_by_both_above_ones_found_by_one():
    results = searcher.search("u", "d", "q", mode="hybrid")
    assert results[0].methods == ("vector", "keyword")          # c2 is ranked low by each list but found by both
    assert results[0].score > results[-1].score

def test_k_limits_the_results_and_is_clamped():
    assert len(searcher.search("u", "d", "q", k=1)) == 1
    assert len(searcher.search("u", "d", "q", k=0)) == 1
    assert len(searcher.search("u", "d", "q", k=999)) <= 50

@pytest.mark.parametrize("query", ["", "   ", "\\n\\t"])
def test_a_blank_query_returns_nothing_and_calls_no_search(query):
    assert searcher.search("u", "d", query) == []
    assert vector_calls == [] and keyword_calls == []

def test_the_callers_ids_are_passed_through_unchanged():
    # both fakes record (user_id, document_id, query, limit); limit == candidates

def test_a_failing_keyword_search_does_not_hide_vector_results_in_hybrid_mode():
    # keyword fake raises RuntimeError; hybrid returns the vector results with methods == ("vector",)
```

Add one integration test in `tests/test_keyword_search.py` (real PostgreSQL, real repository, a constant-vector embedder like `ConstantEmbedder`): `build_paper_searcher(...)` hybrid search in user A's paper never returns user B's passages (Review Focus 3).

- [ ] **Step 2: Run to verify it fails.** `python -m pytest tests/test_paper_searcher.py -q` -> `ModuleNotFoundError: No module named 'retrieval.search'`.
- [ ] **Step 3: Implement `PaperSearcher`** as specified. If the keyword search raises in hybrid mode, log a warning and continue with the vector results; if the vector search raises, let it propagate (it is the primary search).
- [ ] **Step 4: Run to verify it passes.** `python -m pytest tests/test_paper_searcher.py -q` and, with `RAG_TEST_DATABASE_URL` set, `python -m pytest tests/test_keyword_search.py -q`.
- [ ] **Step 5: Commit**

```bash
git add retrieval/search.py tests/test_paper_searcher.py tests/test_keyword_search.py
git commit -m "Add the paper searcher with vector, keyword and hybrid modes" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Question files and scoring

**Files:**
- Create: `backend/evaluation/__init__.py`, `backend/evaluation/questions.py`, `backend/evaluation/metrics.py`, `backend/evaluation/validation.py`, `backend/tests/test_evaluation_questions.py`, `backend/tests/test_evaluation_metrics.py`

**Interfaces:**
- Produces (`evaluation.questions`): pydantic models `Question(id: str, question: str, kind: Literal["answerable", "absent"], category: str, answer_phrases: list[str] = [])` (an answerable question needs at least one non-blank phrase; an absent one must have none) and `QuestionSet(paper: str, questions: list[Question])` (question ids unique); `load_question_set(path: Path) -> QuestionSet` (raises `ValueError` with the file name and the problem).
- Produces (`evaluation.metrics`), all pure: `normalize(text: str) -> str` (lower-case, Unicode NFKC so ligatures such as "ﬁ" become "fi", hyphen/dash variants and soft hyphens become a plain space or nothing, whitespace collapsed); `is_relevant(passage_text: str, phrases: Sequence[str]) -> bool` (normalised containment of any phrase); `first_relevant_rank(passage_texts: Sequence[str], phrases: Sequence[str]) -> int | None` (1-based); `recall_at_k(ranks: Sequence[int | None], k: int) -> float`; `mean_reciprocal_rank(ranks: Sequence[int | None]) -> float`; frozen dataclass `ThresholdSuggestion(threshold: float, accuracy: float)` and `suggest_threshold(answerable_scores: Sequence[float], absent_scores: Sequence[float]) -> ThresholdSuggestion | None` (the score cut-off that best separates the two groups, "covered" meaning score >= threshold; `None` if either group is empty; ties choose the lower threshold).
- Produces (`evaluation.validation`): `find_problems(question_set: QuestionSet, paper_text: str) -> list[str]`: one message per answerable question phrase that does not occur in the normalised paper text, naming the question id and the phrase; `[]` when everything is found.

- [ ] **Step 1: Write the failing tests.**

`tests/test_evaluation_metrics.py`:
```python
def test_normalize_handles_ligatures_hyphens_case_and_whitespace():
    assert normalize("The  \\u00ef\\u00ac\\u0081rst   Self\\u2010Attention\\nLayer") == normalize("the first self-attention layer")
    assert normalize("multi-\\u00adhead") == normalize("multi-head")

def test_is_relevant_matches_any_phrase_case_insensitively():
    assert is_relevant("We use Multi-Head Attention with h = 8", ["multi-head attention"])
    assert not is_relevant("We use recurrence", ["multi-head attention", "attention heads"])

def test_first_relevant_rank_is_one_based_or_none():
    assert first_relevant_rank(["a", "needle here", "b"], ["needle"]) == 2
    assert first_relevant_rank(["a", "b"], ["needle"]) is None

def test_recall_at_k_counts_ranks_within_k():
    assert recall_at_k([1, 3, None, 5], 3) == pytest.approx(0.5)
    assert recall_at_k([], 3) == 0.0

def test_mrr_averages_reciprocal_ranks_and_scores_misses_zero():
    assert mean_reciprocal_rank([1, 2, None]) == pytest.approx((1 + 0.5 + 0) / 3)

def test_suggest_threshold_separates_the_groups():
    suggestion = suggest_threshold([0.8, 0.7, 0.9], [0.3, 0.4, 0.2])
    assert 0.4 < suggestion.threshold <= 0.7 and suggestion.accuracy == 1.0

def test_suggest_threshold_reports_the_best_achievable_accuracy_when_groups_overlap():
    suggestion = suggest_threshold([0.8, 0.5, 0.45], [0.6, 0.4, 0.1])
    assert 0.5 < suggestion.accuracy < 1.0

def test_suggest_threshold_needs_both_groups():
    assert suggest_threshold([], [0.1]) is None and suggest_threshold([0.9], []) is None
```

`tests/test_evaluation_questions.py`:
```python
def test_a_valid_file_loads(tmp_path):
    path = write_json(tmp_path, {"paper": "p", "questions": [answerable("q1"), answerable("q2"), absent("q3")]})
    loaded = load_question_set(path)
    assert loaded.paper == "p" and [q.kind for q in loaded.questions] == ["answerable", "answerable", "absent"]
def test_answerable_questions_need_a_phrase_and_absent_ones_must_have_none(tmp_path):
    no_phrase = write_json(tmp_path, {"paper": "p", "questions": [{**answerable("q1"), "answer_phrases": []}]})
    with pytest.raises(ValueError, match="q1"):
        load_question_set(no_phrase)
    blank = write_json(tmp_path, {"paper": "p", "questions": [{**answerable("q2"), "answer_phrases": ["  "]}]})
    with pytest.raises(ValueError, match="q2"):
        load_question_set(blank)
    with_phrase = write_json(tmp_path, {"paper": "p", "questions": [{**absent("q3"), "answer_phrases": ["x"]}]})
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
def test_find_problems_names_every_phrase_that_is_not_in_the_paper():
    problems = find_problems(question_set, "Scaled dot-product attention divides by sqrt(d_k).")
    assert any("q2" in p and "multi-head attention" in p for p in problems)
    assert find_problems(question_set, "scaled dot-product attention ... multi-head attention") == []
def test_find_problems_ignores_absent_questions():
    only_absent = QuestionSet(paper="p", questions=[Question(id="a1", kind="absent", category="absent", question="Anything?")])
    assert find_problems(only_absent, "any text at all") == []
```

- [ ] **Step 2: Run to verify it fails.** `python -m pytest tests/test_evaluation_metrics.py tests/test_evaluation_questions.py -q` -> `ModuleNotFoundError: No module named 'evaluation'`.
- [ ] **Step 3: Implement** the three modules. `suggest_threshold` tries each observed score as a candidate cut-off (plus nothing else) and keeps the one with the most correct decisions.
- [ ] **Step 4: Run to verify it passes.** Same command -> all pass.
- [ ] **Step 5: Commit**

```bash
git add evaluation/__init__.py evaluation/questions.py evaluation/metrics.py evaluation/validation.py tests/test_evaluation_metrics.py tests/test_evaluation_questions.py
git commit -m "Add question files, scoring functions and phrase validation" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Runner, report, one-time ingest, paper download, command line

**Files:**
- Create: `backend/evaluation/ingest.py`, `backend/evaluation/runner.py`, `backend/evaluation/fetch_papers.py`, `backend/evaluation/run.py`, `backend/evaluation/papers.json`, `backend/tests/test_evaluation_runner.py`, `backend/tests/test_evaluation_ingest.py`
- Modify: `backend/data/.gitignore` (add `eval_papers/`)

**Interfaces:**
- Consumes: `PaperSearcher`, `Evidence` (Tasks 1, 3); scoring and `QuestionSet` (Task 4); `PaperIngestor`, `RAGStorageService`, `PostgresRAGRepository.find_document_by_sha256`, `AccountService`.
- Produces (`evaluation.ingest`): `ensure_paper(pdf_path: Path, user_id: str, storage, ingestor, work_dir: Path) -> str` returns the stored `document_id`; it computes the file's SHA-256 and returns the existing document (parsing nothing, embedding nothing new) when `storage.repository.find_document_by_sha256(user_id, sha)` finds one, otherwise runs `ingestor.ingest` then `ingestor.embed`.
- Produces (`evaluation.runner`): frozen dataclasses `QuestionResult(question_id, kind, category, rank_by_mode: dict[str, int | None], best_score_by_mode: dict[str, float | None])` and `ModeSummary(mode, recall_at: dict[int, float], mrr: float, recall_by_category: dict[str, float])`; `EvaluationResult(paper, answerable_count, absent_count, summaries: list[ModeSummary], questions: list[QuestionResult], threshold_by_mode: dict[str, ThresholdSuggestion | None])`; `evaluate(searcher: PaperSearcher, user_id: str, document_id: str, question_set: QuestionSet, modes: Sequence[str] = ("vector", "keyword", "hybrid"), k_values: Sequence[int] = (1, 3, 5, 8)) -> EvaluationResult` (searches with `k = max(k_values)`; absent questions only feed `best_score_by_mode` and the threshold suggestion, never recall; the "best score" of a question is the top evidence `score`, `None` when nothing was found); `render_markdown(results: Sequence[EvaluationResult]) -> str` (a table per paper: rows = modes, columns = recall@k, MRR; a per-category recall@5 table; the score ranges of answerable versus absent questions and the suggested threshold per mode; a list of answerable questions that no mode found in the top 8, with their ids).
- Produces (`evaluation.fetch_papers`): `fetch(manifest_path: Path, dest_dir: Path, download: Callable[[str], bytes] | None = None) -> dict[str, Path]` (`download` defaults to a function that fetches the URL over HTTPS; tests pass a fake): for each manifest entry with a `url`, downloads to `dest_dir/<key>/paper.pdf` unless a file with the pinned `sha256` already exists; checks the response starts with `%PDF-`, is at most 30 MB, and that its SHA-256 equals the entry's `sha256` when one is pinned (a mismatch raises `ValueError` and keeps the file out of the results); entries with only a `local_path` resolve to that file if it exists. Manifest entries: `{"key", "title", "url" | "local_path", "sha256" | null}`; ship `attention` (`https://arxiv.org/pdf/1706.03762`), `resnet` (`https://arxiv.org/pdf/1512.03385`) and `sample` (`local_path: "IJRTI2304061.pdf"`).
- Produces (`evaluation.run`): `python -m evaluation.run [--papers KEY ...] [--modes MODE ...] [--user-email EMAIL] [--validate-only] [--out PATH]`. It fetches the papers, finds or creates the evaluation account (`evaluation@edugen.local` with a random unused password), ensures each paper is stored once, validates the question file against the stored text (printing every problem and exiting with status 1 if any), runs `evaluate` and writes the markdown report to `--out` (default `evaluation/results/latest.md`, git-ignored) and prints it.

- [ ] **Step 1: Write the failing tests.**

`tests/test_evaluation_runner.py` (a fake searcher whose `search` returns canned `Evidence` lists per `(query, mode)`):
```python
def test_recall_and_mrr_are_computed_per_mode():
    # three answerable questions whose answer phrase appears at rank 1, rank 3 and nowhere in the vector results
    result = evaluate(searcher, "u", "d", question_set, modes=("vector",), k_values=(1, 3))
    summary = result.summaries[0]
    assert summary.recall_at == {1: pytest.approx(1 / 3), 3: pytest.approx(2 / 3)}
    assert summary.mrr == pytest.approx((1 + 1 / 3 + 0) / 3)
    # three answerable questions: found at rank 1, 3 and not at all in vector mode -> recall@1 = 1/3, recall@3 = 2/3, MRR = (1 + 1/3 + 0)/3
def test_absent_questions_never_count_against_recall_but_feed_the_threshold():
    # adding an absent question leaves recall unchanged; threshold_by_mode["vector"] is a ThresholdSuggestion
def test_recall_by_category_groups_answerable_questions():
    # q1 (method) and q2 (results) are found in the top 5, q3 (method) is not
    summary = evaluate(searcher, "u", "d", question_set, modes=("vector",), k_values=(5,)).summaries[0]
    assert summary.recall_by_category == {"method": pytest.approx(0.5), "results": pytest.approx(1.0)}
def test_searching_uses_the_largest_k_and_each_requested_mode_only():
    # modes=("hybrid",) -> the fake sees only hybrid calls, each with k == max(k_values)
def test_a_question_with_no_evidence_has_rank_none_and_score_none():
    result = evaluate(empty_searcher, "u", "d", question_set, modes=("hybrid",))
    first = result.questions[0]
    assert first.rank_by_mode["hybrid"] is None and first.best_score_by_mode["hybrid"] is None
def test_the_markdown_report_lists_modes_tables_thresholds_and_missed_questions():
    text = render_markdown([result])
    assert "| hybrid |" in text and "recall@5" in text and "q3" in text and "threshold" in text.lower()
```

`tests/test_evaluation_ingest.py`:
```python
def test_a_new_paper_is_parsed_stored_and_embedded_once():
    document_id = ensure_paper(pdf_path, "u", storage, ingestor, work_dir)
    assert document_id == "doc-1" and ingestor.ingest_calls == 1 and ingestor.embed_calls == 1
def test_an_already_stored_paper_is_neither_parsed_nor_embedded_again():
    storage.repository.existing[("u", sha256_of(pdf_path))] = "doc-9"
    assert ensure_paper(pdf_path, "u", storage, ingestor, work_dir) == "doc-9"
    assert ingestor.ingest_calls == 0 and ingestor.embed_calls == 0
def test_fetch_checks_the_pdf_header_size_and_pinned_hash(tmp_path):
    # a fake downloader returns canned bodies for three manifest entries
    with pytest.raises(ValueError, match="hash"):
        fetch(manifest_with_wrong_hash, tmp_path, download=lambda url: PDF_BYTES)
    with pytest.raises(ValueError, match="PDF"):
        fetch(manifest_without_hash, tmp_path, download=lambda url: b"<html>not a pdf</html>")
    with pytest.raises(ValueError, match="large"):
        fetch(manifest_without_hash, tmp_path, download=lambda url: b"%PDF-" + b"0" * (31 * 1024 * 1024))
    assert list(tmp_path.rglob("paper.pdf")) == []              # nothing bad was kept
def test_fetch_skips_the_download_when_the_pinned_file_is_already_there(tmp_path):
    calls = []
    paths = fetch(manifest_with_right_hash, tmp_path, download=lambda url: calls.append(url) or PDF_BYTES)
    again = fetch(manifest_with_right_hash, tmp_path, download=lambda url: calls.append(url) or PDF_BYTES)
    assert paths == again and len(calls) == 1
def test_local_path_entries_resolve_when_present_and_are_skipped_when_missing(tmp_path):
    present = fetch(manifest_with_local(tmp_path / "here.pdf"), tmp_path / "dest", download=None)   # file exists
    absent = fetch(manifest_with_local(tmp_path / "gone.pdf"), tmp_path / "dest", download=None)
    assert list(present) == ["sample"] and absent == {}
```

- [ ] **Step 2: Run to verify it fails.** `python -m pytest tests/test_evaluation_runner.py tests/test_evaluation_ingest.py -q` -> `ModuleNotFoundError: No module named 'evaluation.runner'`.
- [ ] **Step 3: Implement** the four modules and the manifest; add `eval_papers/` and the results folder to the git-ignores (`backend/data/.gitignore` and `backend/evaluation/.gitignore` containing `results/`).
- [ ] **Step 4: Run to verify it passes.** `python -m pytest tests/test_evaluation_runner.py tests/test_evaluation_ingest.py -q` -> all pass; then `python -m pytest -q` -> the whole default suite passes.
- [ ] **Step 5: Commit**

```bash
git add evaluation/ingest.py evaluation/runner.py evaluation/fetch_papers.py evaluation/run.py evaluation/papers.json evaluation/.gitignore data/.gitignore tests/test_evaluation_runner.py tests/test_evaluation_ingest.py
git commit -m "Add the evaluation runner, report, paper download and command line" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Fetch the papers, store them, write and validate the question files

**Files:**
- Create: `backend/evaluation/data/attention.json`, `backend/evaluation/data/resnet.json`, `backend/evaluation/data/sample.json`
- Modify: `backend/evaluation/papers.json` (fill in the pinned `sha256` of each downloaded paper)

This task runs real Docling and real Gemini embeddings against the development database (a few minutes per paper; a few hundred embedding calls in total).

- [ ] **Step 1: Fetch and store the papers.** Run `python -m evaluation.run --validate-only` from `backend/` with the question files absent (it should fetch both arXiv papers into `data/eval_papers/<key>/paper.pdf`, store and embed all three papers under the evaluation account and report "no question file" for each). Copy the printed SHA-256 of each downloaded PDF into `papers.json`.
Expected: three papers stored; re-running prints that nothing was parsed or embedded again (Review Focus 5).

- [ ] **Step 2: Read each paper's stored text.** Print the passages with their pages (a small throwaway script under `backend/scratch_*.py`, not committed) and read them. For every paper write `evaluation/data/<key>.json` with about 15 questions in this shape:

```json
{"paper": "attention", "questions": [
  {"id": "attention-01", "kind": "answerable", "category": "method",
   "question": "How does the Transformer let each position look at every other position?",
   "answer_phrases": ["self-attention", "attends to all positions"]},
  {"id": "attention-14", "kind": "absent", "category": "absent",
   "question": "How many GPUs were used to train GPT-4?", "answer_phrases": []}
]}
```
Rules: 12 answerable questions per paper spread over motivation, method, definitions or equations, tables or figures, results with numbers, comparison with other work and limitations or future work (at least two questions whose answer is spread over more than one section); 3 absent questions on plausible nearby topics the paper truly does not cover. Phrases must be short, distinctive wording copied from the paper's own text (they are alternatives; any one occurring in a passage makes it relevant). Questions are written like a learner would ask them, not by copying the answer sentence.

- [ ] **Step 3: Validate.** `python -m evaluation.run --validate-only`.
Expected: exit status 0 and "no problems" for all three files; fix any phrase it reports (a phrase that is not found in the stored text) until clean.

- [ ] **Step 4: Commit**

```bash
git add evaluation/data/attention.json evaluation/data/resnet.json evaluation/data/sample.json evaluation/papers.json
git commit -m "Add the evaluation question files for three papers" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Run the evaluation and report the findings

**Files:**
- Create: `docs/superpowers/results/2026-11-03-retrieval-evaluation.md`

- [ ] **Step 1: Full suite and integration tests.** In `backend/`, with `RAG_TEST_DATABASE_URL` set: `python -m pytest -q -m "slow or not slow"`.
Expected: everything passes; report the count.

- [ ] **Step 2: Migrate the development database.** `python -m alembic -c alembic.ini upgrade head`.
Expected: `0004_passage_text_index (head)`.

- [ ] **Step 3: Run the evaluation.** `python -m evaluation.run` (all papers, all three modes).
Expected: the markdown report prints and is saved.

- [ ] **Step 4: Write the findings** into `docs/superpowers/results/2026-11-03-retrieval-evaluation.md`: the report tables as produced (not retyped by hand), then a short plain-language reading with these answers: (a) which mode has the best recall@5 and MRR overall and per paper; (b) whether adding keyword search to vector search helps or hurts, by how much; (c) which question categories fail (equations? tables? multi-section answers?) and why, with examples taken from the missed-question list; (d) the suggested "not in this paper" threshold per mode, how well it separates the groups on these papers, and how confident that makes us; (e) a recommendation for the next plan (which retrieval mode to use, whether neighbouring-passage expansion or reranking looks worth testing, and what the whole-paper-in-prompt comparison should measure). State plainly what these numbers do not show (three papers, questions written by the assistant, retrieval only, no generated answers).

- [ ] **Step 5: Clean up.** Leave the three evaluation copies in the database (they are reused by later plans) but note the evaluation account in the findings; delete scratch scripts; confirm `git status` shows no PDFs or `data/` files.

- [ ] **Step 6: Commit and report**

```bash
git add ../docs/superpowers/results/2026-11-03-retrieval-evaluation.md
git commit -m "Record the retrieval evaluation findings" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
Report in chat: the headline numbers, the recommendation, and anything not verified.

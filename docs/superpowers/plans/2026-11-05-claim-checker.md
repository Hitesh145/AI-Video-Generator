# Claim Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before a paper video is rendered, every sentence of its script is checked against the passages it cites by an independent model pass; sentences the paper does not support are fixed or removed, and what happened is saved with the video and shown to the viewer.

**Architecture:** A `ClaimChecker` splits each script part into sentences and asks a separate model call (which sees only the sentences and the cited passages, not the topic) for a verdict per sentence plus the exact quote that supports it. A verdict of "supported" only counts if the quote really occurs in the cited passages (deterministic check). Unsupported sentences trigger one regeneration of the lesson with the offending sentences named; sentences still unsupported afterwards are removed (a section left empty is dropped; no section left fails the job). The report is saved as `claim_check.json` and summarised in the video's notes.

**Tech Stack:** Python, Pydantic, existing `LLMService.generate_structured`, existing job/stage plumbing.

**Spec:** `docs/superpowers/specs/2026-11-01-paper-videos-design.md` (section 3: only what the paper supports; section 4 anti-goals: wrong claim attributed to the paper, key result silently missing). Evidence for why this is needed: `docs/superpowers/results/2026-11-04-grounded-script-check.md` (section 4: number/equation guards are partial; citations broad).

## Global Constraints

- Run backend commands from `backend/`. Default `python -m pytest -q` excludes `slow`; full run `-m "slow or not slow"` with `RAG_TEST_DATABASE_URL` set (same server, database `edugen_rag_test`). Known flaky on this machine: ffmpeg tests in `test_timing.py` / `test_video_library.py` (pass alone).
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Stage files by name only; never stage `backend/IJRTI2304061.pdf`, `backend/IJRTI2304061_assets/`, `backend/rendering/__init__.py`, or anything under `backend/output/` or `backend/data/`. Never push.
- Windows + Git Bash: write files with the Write tool (backslash escapes in heredocs get mangled; a `\b` or `\n` inside a Python string written through a heredoc can silently change). Re-read any regex you write into a file.
- Accuracy over speed: when the checker is unsure, the sentence is not supported. A check that cannot run (model error) must fail the job, never skip the check and render.
- The check is a second model pass, not proof. Wording shown to people must say "checked against the paper", never "verified" or "guaranteed".

## Review Focus

1. **A "supported" verdict with a quote that is not in the cited passages is treated as unsupported** (a model that agrees without evidence must not pass a sentence). Tested in Task 1.
2. **A model error, a malformed answer, or a missing verdict for a sentence** is "unsupported" (never silently passed); an exception from the checker fails the job. Tested in Task 1 and 3.
3. **Sentence splitting must not cut abbreviations, decimals or equations** ("Fig. 3 shows 3.5 days", "e.g.", "et al.", "N = 6.") into fragments that then fail or pass for the wrong reason. Tested in Task 1.
4. **Removal must not leave a misleading video:** a section left empty is dropped, an introduction or conclusion with every sentence removed is replaced by a neutral one-line (not a claim), and if nothing factual remains the job fails with a plain message. Tested in Task 2.
5. **The checker cannot be steered by the script:** sentences go to the checker as data inside delimiters, with the instruction that they are text to judge, not instructions; the topic is not sent. Tested in Task 1.

---

## File Structure

**Create:** `backend/schemas/claims.py`, `backend/services/claim_checker.py`, `backend/tests/test_claim_checker.py`, `docs/superpowers/results/2026-11-05-claim-checker-check.md`.
**Modify:** `backend/services/grounded_lesson_service.py` (`create(..., feedback=)`), `backend/services/paper_video_service.py`, `backend/services/job_service.py` (new stage), `backend/main.py` (wire the checker), and the matching tests.

## Calls made while planning (not in the spec)

- **Quote requirement:** the checker must return, for each supported sentence, an exact quote from the cited passages; quotes are matched after normalising whitespace, case, dashes and unicode forms. This is the main defence against a checker that simply agrees.
- **Framing sentences:** a sentence with no factual content about the paper (for example "This video covers the method section.") gets the verdict `framing`; it needs no quote. A framing sentence that contains a digit is treated as unsupported.
- **One regeneration, then removal** (not endless retries): cost is bounded at two lesson calls and two checker passes per video.
- **Checker granularity:** one model call per script part (introduction, each section, conclusion), all sentences of that part together, against that part's cited passages (introduction and conclusion: all passages).
- **Same model:** the checker uses the app's configured model with a different prompt; an independent model would be better and is a follow-up.
- **Not in this plan:** equation pictures, the unreadable-content report, a key-result-missing check, a UI badge beyond the existing notes list.

---

### Task 1: Check each sentence against its cited passages

**Files:**
- Create: `backend/schemas/claims.py`, `backend/services/claim_checker.py`, `backend/tests/test_claim_checker.py`

**Interfaces:**
- Consumes: `services.grounded_lesson_service.{GroundedResult, Passage}` (`GroundedResult.lesson_script: LessonScript` with `introduction`, `sections[].narration`, `conclusion`; `.section_citations: list[list[str]]`; `.passages: list[Passage]` where `Passage.evidence.text`); an LLM with `generate_structured(prompt, response_schema)`.
- Produces (`schemas.claims`): `SentenceVerdict(index: int, verdict: Literal["supported", "unsupported", "contradicted", "framing"], quote: str = "")`; `PartVerdicts(verdicts: list[SentenceVerdict])`.
- Produces (`services.claim_checker`): `split_sentences(text: str) -> list[str]`; `SentenceCheck(part: str, sentence: str, verdict: str, quote: str, supported: bool)`; `ClaimReport(checks: list[SentenceCheck])` with properties `failed -> list[SentenceCheck]`, `ok -> bool`; `ClaimChecker(llm_service)` with `check(result: GroundedResult) -> ClaimReport`. `part` is `"introduction"`, `"conclusion"` or the section title.
- `split_sentences` splits after `.`, `!` or `?` followed by whitespace and an uppercase letter, but never after the abbreviations `Fig.`, `Figs.`, `Eq.`, `Eqn.`, `Sec.`, `No.`, `e.g.`, `i.e.`, `et al.`, `vs.`, never inside a decimal, and keeps text such as `N = 6.` intact.

- [ ] **Step 1: Write the failing tests** with a fake LLM that returns scripted `PartVerdicts` and records prompts: `test_split_sentences_handles_abbreviations_decimals_and_equations` (cases `"Fig. 3 shows 3.5 days. It works."` gives 2; `"We use e.g. Adam. Next, N = 6."` gives 2; `"Vaswani et al. propose it. Done."` gives 2), `test_a_supported_sentence_with_a_quote_from_the_cited_passage_passes` (quote matches after case/whitespace/dash normalisation), `test_a_supported_verdict_whose_quote_is_not_in_the_cited_passages_counts_as_unsupported`, `test_a_supported_verdict_with_an_empty_quote_counts_as_unsupported`, `test_unsupported_and_contradicted_sentences_fail_the_report`, `test_a_missing_verdict_for_a_sentence_counts_as_unsupported`, `test_framing_sentences_pass_without_a_quote_unless_they_contain_a_digit`, `test_each_part_is_checked_against_its_own_cited_passages_and_intro_conclusion_against_all` (inspect the prompts), `test_the_prompt_never_contains_the_topic_and_fences_the_sentences` (sentences between `<<<SENTENCES` and `SENTENCES>>>`, the instruction that they are text to judge, not instructions), `test_a_model_error_propagates` (the fake raises; `check` raises, nothing is swallowed).
- [ ] **Step 2: Run.** Expected: FAIL (modules missing).
- [ ] **Step 3: Implement** schemas, `split_sentences`, quote normalisation (`casefold`, NFKC, dash variants to `-`, collapse whitespace), the prompt, and `check`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** the four files "Check each script sentence against its cited passages".

### Task 2: Fix or remove what the paper does not support

**Files:**
- Modify: `backend/services/grounded_lesson_service.py`, `backend/services/claim_checker.py`, `backend/tests/test_grounded_lesson_service.py`, `backend/tests/test_claim_checker.py`

**Interfaces:**
- `GroundedLessonService.create(topic, evidence, brief=False, feedback: Sequence[str] = ())`: when `feedback` is given, the prompt ends with `A previous version contained sentences the paper does not support. Do not repeat them:` and one `- ` line per sentence.
- `claim_checker.apply_report(result: GroundedResult, report: ClaimReport) -> tuple[GroundedResult, list[SentenceCheck]]` returning the result with every failed sentence removed and the list of removed checks. Rules: sentences are removed from the narration text; a section with no sentences left is dropped together with its citations and its plan entry; an introduction with no sentences left becomes `This video explains parts of the paper.`; a conclusion with none left becomes `That is what the paper says about this.`; if no section is left raise `NothingSupported("None of the script could be checked against the paper, so no video was made.")`.

- [ ] **Step 1: Write the failing tests:** `test_apply_report_removes_only_failed_sentences_and_keeps_order`, `test_a_section_with_no_supported_sentence_is_dropped_with_its_citation_and_plan_entry`, `test_empty_intro_and_conclusion_get_neutral_framing_not_claims`, `test_nothing_left_raises`, `test_a_report_with_no_failures_returns_the_result_unchanged`, `test_feedback_sentences_appear_in_the_regeneration_prompt` (in the grounded service tests).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run both files.** Expected: PASS.
- [ ] **Step 5: Commit** "Remove unsupported sentences and allow regeneration with feedback".

### Task 3: Check every paper video before it is rendered

**Files:**
- Modify: `backend/services/paper_video_service.py`, `backend/services/job_service.py`, `backend/main.py`, `backend/tests/test_paper_video_service.py`, `backend/tests/test_job_service.py`, `backend/tests/test_paper_videos_router.py`

**Interfaces:**
- `JobService.STAGES` gains `("check", "Checking the script against the paper")` between `script` and `route`.
- `PaperVideoService.__init__` gains `checker: ClaimCheckerLike` (any object with `check(result) -> ClaimReport`), placed after `grounded`; `main.py` passes `ClaimChecker(llm_service)`.
- In `_make_paper_video`: after the lesson is written, `report_stage("check")`; run `checker.check`; if it has failures, write the lesson again once with `feedback=` the failed sentences and check again; apply `apply_report` to the final result; render only the final result. Save `claim_check.json` (all checks of the final attempt, the removed sentences, and whether a regeneration happened). `qc_warnings` / notes: replace the not-checked sentence by `Each sentence was checked against the passages it cites by a second model pass; this is not a guarantee.` when all passed, or `... {n} sentence(s) the paper did not support were removed.` when some were removed. A checker exception fails the job with its message; nothing is rendered.
- `NOT_CHECKED_WARNING` remains for the case a video predates the checker (no `claim_check.json`).

- [ ] **Step 1: Write the failing tests** (fake checker): `test_a_clean_check_renders_with_the_checked_note_and_saves_claim_check_json`, `test_failed_sentences_trigger_one_regeneration_with_feedback_and_the_second_result_is_rendered`, `test_sentences_still_failing_after_regeneration_are_removed_and_the_note_says_how_many`, `test_a_checker_exception_fails_the_job_and_renders_nothing`, `test_nothing_supported_fails_the_job_with_a_plain_message`, `test_the_check_stage_is_reported`, plus the stage list assertion in the job tests.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** and wire in `main.py`.
- [ ] **Step 4: Run the whole suite** (and with `RAG_TEST_DATABASE_URL`). Expected: PASS.
- [ ] **Step 5: Commit** "Check every paper video's script against the paper before rendering".

### Task 4: Does the checker really catch a wrong sentence? (live)

**Files:** Create `docs/superpowers/results/2026-11-05-claim-checker-check.md`; scratch scripts under `.superpowers/` (not committed). Calls the real model on the evaluation papers (a few dozen calls, no rendering).

- [ ] **Step 1:** For the six lessons used in the previous live check (covered and weak topics on the three evaluation papers) run write + check; record per paper how many sentences were supported, framing, failed, and whether a regeneration happened.
- [ ] **Step 2: Plant errors.** Take each of those six scripts and insert by hand 3 false sentences each: a changed number ("3.5 days" to "5 days"), a reversed claim ("recurrence is required"), and a plausible claim from outside the paper (a true statement about the topic that the cited passages do not contain). Run the checker on the altered scripts. Record how many of the 18 planted sentences it flagged, and any false alarms on the untouched sentences.
- [ ] **Step 3: Write the results note:** detection rate, false alarms, cost (calls, seconds), and what remains unchecked (same model as the writer, key-result omissions, equation pictures). Commit "Record the live check of the claim checker". Report in chat the detection rate honestly, including misses.

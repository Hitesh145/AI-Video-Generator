# Teaching and Animation Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Videos explain every term they use (for example what an LR "item" is) at the depth the person asked for, show no overlapping or off-screen text, and can use 3D scenes where the idea is spatial, without changing the model.

**Architecture:** Fix the instructions the model is given at each stage (analyzer, planner, script writer, storyboard, animation code), pass information that is currently dropped (the knowledge-base facts and the terms the person named), add a second pass that finds undefined terms, add an automatic overlap check to the generated animation's beat report (which already drives retries), and add one 3D example the model can follow. Measured before and after on fixed topics.

**Tech Stack:** Python (FastAPI services, Pydantic schemas), Manim Community Edition scenes, existing `generate_structured` LLM calls.

**Spec:** `docs/superpowers/specs/2026-11-01-paper-videos-design.md` section 3 for paper videos (amended here: a paper video may carry short, clearly marked general-knowledge definitions). Findings that motivate this plan: the owner's report of an LR-parser video that used "items" without defining them; `docs/superpowers/results/` notes on the current prompts.

## Global Constraints

- Run backend commands from `backend/`. Quick suite `python -m pytest -q`; everything `python -m pytest -q -m "slow or not slow"` with `RAG_TEST_DATABASE_URL` set. Known flaky on this machine: ffmpeg tests in `test_timing.py` / `test_video_library.py`.
- Commit trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Stage files by name; never stage `backend/IJRTI2304061.pdf`, `backend/IJRTI2304061_assets/`, `backend/rendering/__init__.py`, anything under `backend/output/`, `backend/data/` or `docs/report/`. Never push.
- Windows + Git Bash: write files with the Write tool; re-read any regex or `\n` you put into a file through a heredoc.
- New schema fields must have defaults so existing tests, saved run folders and the studio keep working.
- Prompt wording is tested by asserting the exact rule sentences that matter (as in `test_grounded_lesson_service.py`); behaviour is tested with fake LLMs; improvement is measured with the live evaluation in Task 8.
- Paper videos: background definitions are general knowledge, never numbers or equations, always spoken with the marker `Some background that is not from the paper:` and never counted as claims of the paper.
- No change may weaken the claim checker for the paper's own sentences.

## Review Focus

1. **Existing callers keep working:** a `LessonRequest` / `LessonPlan` / script writer called the old way (no new fields, no knowledge base) behaves as before. Tested in Tasks 1 to 3.
2. **The term pass cannot damage a good script:** the rewrite must keep the same section titles in the same order and must not drop sections; otherwise the original script is kept and a warning recorded. Tested in Task 4.
3. **A model error in a new step never silently skips the step:** an exception in the term review fails the job with its message for the studio; it must not render a script that was meant to be reviewed. (Chosen over "skip on error": the owner's priority is that explanations are complete.) Tested in Task 4.
4. **Background definitions cannot smuggle claims:** digits, equations or more than two sentences in a background field are rejected; background text is never counted as supported by the paper and is clearly labelled aloud and in the notes. Tested in Task 5.
5. **The layout check cannot reject a good scene forever:** it triggers retries like timing does, and after the attempts the least-flawed scene is used with a warning, never a failed video. Tested in Task 6.
6. **3D scenes still obey the validator and the beat clock** (one class named `SectionScene`, allowed imports only, `BeatClock` timing). Tested in Task 7.

---

## File Structure

**Create:** `backend/schemas/terms.py`, `backend/services/term_review_service.py`, `backend/animation/codegen/examples/three_d_layers.py`, `backend/tests/test_term_review_service.py`, `backend/tests/test_layout_check.py`, `docs/superpowers/results/2026-11-06-teaching-and-animation-quality.md`.
**Modify:** `backend/schemas/lesson.py`, `backend/services/{lesson_analyzer_service,lesson_planner_service,script_writer_service,demo_video_service,grounded_lesson_service,paper_video_service,claim_checker}.py`, `backend/schemas/grounded.py`, `backend/animation/{storyboard,router}.py`, `backend/animation/codegen/{kit,generator}.py`, `backend/main.py`, and the matching tests.

## Calls made while planning (not in the spec)

- **Studio and paper videos share the new rules** where they apply (define terms, depth, layout, 3D); only the studio gets the term-review pass and the knowledge base, because paper videos are limited to the paper's passages plus the marked background.
- **Duration rules** (analyzer): quick/brief/short = 2 minutes; nothing said = 4; "detailed", "in detail", "in depth", "thorough", "complete", "deep dive" = 8; never more than 12. Words per minute stays 130.
- **Overlap rule** (layout check): two text objects overlap when their boxes intersect by more than 10% of the smaller box; text is off-screen when any part leaves the frame or enters the subtitle strip (bottom 15%); fully transparent objects are ignored. Scenes that use `ThreeDScene` skip the text-overlap test (projected boxes are not comparable) but keep the off-screen test for fixed-in-frame text.
- **Baseline first:** the evaluation set and judge prompt are fixed before any prompt is changed, so the improvement can be measured. The judge is the same model family as the writer; its numbers compare before and after, not absolute quality.
- **Not in this plan:** a stronger model (compared separately, results pending), neighbouring-passage retrieval, equation pictures, a vision model that inspects rendered frames.

---

### Task 1: The analyzer reads depth and the terms the person asked for

**Files:** Modify `backend/schemas/lesson.py`, `backend/services/lesson_analyzer_service.py`, `backend/tests/test_lesson_analyzer.py` (create if absent; or the existing analyzer test file).

**Interfaces:**
- `LessonRequest` gains `must_cover: list[str] = []` (terms or parts the learner named or clearly needs; at most 8).
- The analyzer prompt contains the sentences `A request for "detail", "in detail", "in depth", "thorough" or "complete" means about 8 minutes and a thorough explanation.`, `A quick or brief request means 2 minutes. If nothing is said, use 4 minutes. Never more than 12.`, `teaching_depth must be one of: introductory, intermediate, advanced.`, and `must_cover: list every term, concept or part the learner named, plus terms the topic cannot be understood without (at most 8).`

- [ ] **Step 1: Write the failing tests:** `test_lesson_request_must_cover_defaults_to_empty`, `test_the_analyzer_prompt_maps_detail_words_to_duration_and_asks_for_must_cover` (the four sentences), `test_the_analyzer_returns_the_models_must_cover_unchanged`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** the field and the prompt.
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** "Make the analyzer read depth and the terms the learner named".

### Task 2: The planner makes a prerequisite-first plan with a purpose and terms per section

**Files:** Modify `backend/schemas/lesson.py`, `backend/services/lesson_planner_service.py`, planner tests.

**Interfaces:**
- `SectionNote(title: str, purpose: str, terms_to_define: list[str] = [], example: str = "")`; `LessonPlan` gains `section_notes: list[SectionNote] = []`.
- Planner prompt: remove `Keep the structure generic and concept-independent.`; add `Order sections so that every term is explained before any later section uses it.`, `Give each section a one-sentence purpose, the terms it must define, and, for any procedure, one worked example.`, `Use about one section per minute of the lesson (at least 3, at most 12).`, `Every item in must_cover must be defined in some section's terms_to_define.`; the request's `must_cover` is printed in the prompt.
- After the call: notes are used only if their count equals the section count (titles are taken from `sections`); otherwise `section_notes` is cleared. If some `must_cover` item is in no section's `terms_to_define` and not in any section title, the planner retries once with `You forgot to cover: <items>`; after the retry it returns what it has.

- [ ] **Step 1: Write the failing tests:** `test_the_planner_prompt_no_longer_asks_for_a_generic_structure_and_asks_for_terms_and_examples`, `test_must_cover_is_listed_in_the_prompt`, `test_notes_with_the_wrong_count_are_dropped`, `test_a_missing_must_cover_item_triggers_one_retry_naming_it`, `test_a_plan_without_notes_still_works`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** "Plan lessons prerequisite-first with the terms each section must define".

### Task 3: The script writer receives the facts and the terms, and must define terms where they first appear

**Files:** Modify `backend/services/script_writer_service.py`, `backend/services/demo_video_service.py` (protocol and call), writer and demo tests, and every fake writer in tests.

**Interfaces:**
- `ScriptWriterService.create_lesson_script(lesson_request, lesson_plan, knowledge_base: KnowledgeBase | None = None) -> LessonScript`.
- The prompt prints `must_cover`, each section's purpose, terms to define and example (when present), and the knowledge base's key concepts and facts as `Reference facts you may rely on`.
- New rules (exact sentences): `Define every technical term in the sentence where it first appears: say what it is and what it is for.`, `Never skip a definition or a step to save words; length follows the requested duration, but completeness comes first.`, `Before answering, check: every term in must_cover is defined; every procedure has one worked example; no sentence relies on a term not yet explained.` The old rule 13 ("Keep the narration concise enough...") is replaced by `Do not pad; every sentence must teach something.`
- `DemoVideoService.generate_demo_video` passes `knowledge_base=knowledge_base` to the writer.

- [ ] **Step 1: Write the failing tests:** `test_the_writer_prompt_contains_the_definition_rules_and_the_checklist`, `test_the_writer_prompt_includes_section_notes_must_cover_and_reference_facts`, `test_the_writer_works_without_a_knowledge_base_or_notes`, `test_the_demo_service_passes_the_knowledge_base_to_the_writer`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** and update the fakes' signatures.
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** "Give the script writer the facts and make it define every term".

### Task 4: A second pass finds undefined terms and fixes them

**Files:** Create `backend/schemas/terms.py`, `backend/services/term_review_service.py`, `backend/tests/test_term_review_service.py`; modify `backend/services/demo_video_service.py`, `backend/main.py`.

**Interfaces:**
- `schemas.terms`: `UndefinedTerm(term: str, section_title: str, reason: str)`, `TermReview(undefined_terms: list[UndefinedTerm])`.
- `TermReviewService(llm_service)` with `review(lesson_request, lesson_script) -> list[UndefinedTerm]` (the model's list plus, deterministically, every `must_cover` item that does not occur anywhere in the script text, case-insensitive, an optional plural `s`, reported as `reason="never mentioned"`) and `fix(lesson_request, lesson_script, undefined) -> LessonScript` (one model call returning a `LessonScript`).
- The review prompt asks for terms a complete beginner would not know that are used without a definition, gloss or worked example (strict). The fix prompt asks to rewrite only the sections that use the listed terms, add the definition in the sentence of first use, keep every section title and the order, and remove nothing else.
- `fix` result is accepted only if it has the same number of sections with the same titles in the same order; otherwise the original script is kept.
- `DemoVideoService(..., term_review_service=None)`: after the script, if a reviewer is configured, `report_stage("script", "Checking that every term is explained")`, review; if anything is undefined, fix once, then review again deterministically for `must_cover` only; remaining items become `qc_warnings` (`Term not explained: <term>`). A model exception propagates (fails the job).

- [ ] **Step 1: Write the failing tests:** `test_must_cover_terms_missing_from_the_script_are_reported_without_the_model` (plural and case variants count as present), `test_the_model_list_and_the_missing_terms_are_combined_without_duplicates`, `test_fix_is_accepted_when_titles_and_order_are_unchanged`, `test_fix_is_rejected_when_a_section_is_dropped_or_renamed_and_the_original_is_kept`, `test_nothing_undefined_means_no_fix_call`, `test_a_model_error_in_the_review_propagates`, `test_the_demo_service_runs_the_review_and_fix_and_records_warnings_for_what_stays_undefined`, `test_the_demo_service_without_a_reviewer_is_unchanged`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** and wire `TermReviewService(llm_service)` into `main.py` for the studio pipeline.
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** "Find terms a script uses without explaining and fix them".

### Task 5: Paper videos may carry marked general-knowledge definitions

**Files:** Modify `backend/schemas/grounded.py`, `backend/services/grounded_lesson_service.py`, `backend/services/claim_checker.py` (carry the field through `apply_report`), `backend/services/paper_video_service.py`, and their tests.

**Interfaces:**
- `GroundedSection` gains `background: str = ""`: at most two sentences defining, from general knowledge, terms the section uses that its passages do not define. No digits, no `=`.
- `GroundedResult` gains `section_background: list[str]` (parallel to sections); `apply_report` filters it with the sections.
- `find_problems` reports a section whose `background` contains a digit, an equation, or more than two sentences.
- Prompt rule: `If a term in your narration is not defined by the passages, you may define it in the section's background field in at most two plain sentences from general knowledge; never put numbers, formulas or claims about this paper there.`
- `PaperVideoService` builds the final script after checking: a section with background is narrated as `Some background that is not from the paper: <background> <narration>`; the note `Sentences introduced as background are general knowledge, not from the paper, and are not checked against it.` is added when any background is used; `claim_check.json` lists the background texts. The claim checker never sees the background.

- [ ] **Step 1: Write the failing tests:** `test_background_with_digits_or_equations_or_three_sentences_is_a_problem`, `test_background_is_carried_through_apply_report_and_dropped_with_its_section`, `test_the_final_narration_starts_with_the_background_marker`, `test_the_note_is_added_only_when_background_is_used`, `test_the_claim_checker_never_receives_the_background_text`, `test_the_grounded_prompt_allows_marked_background`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** "Let paper videos define terms from general knowledge, clearly marked".

### Task 6: Layout rules and an automatic overlap check

**Files:** Modify `backend/animation/codegen/kit.py`, `backend/animation/codegen/generator.py`, `backend/animation/storyboard.py`; create `backend/tests/test_layout_check.py`; extend the codegen generator tests.

**Interfaces:**
- `kit.layout_issues(scene) -> list[str]`: walks `scene.mobjects`, treats each `Text`/`MarkupText` as one leaf (its glyphs are not walked), ignores leaves with fill opacity below 0.05, and returns plain sentences: `'<a>' and '<b>' overlap` (intersection above 10% of the smaller box) and `'<a>' leaves the screen or covers the subtitle area`. For a `ThreeDScene` only the off-screen test runs.
- `BeatClock.end_beat` stores, in each report row, `"layout": layout_issues(scene)`.
- `generator.check_layout(rows) -> LayoutCheck(error: str | None, issue_count: int)`: the error text names the beat and the offending pair and says how to fix (`move one, scale it down, or reduce the text`).
- `CodegenRenderer.render`: after the timing check passes, the layout check also runs; both errors are returned together on a retry; the least-flawed attempt (fewest layout issues, then least overrun) is kept as the fallback with the warning `Section '<title>': some text may overlap (<message>)`; a scene with no issues returns at once as today.
- Prompt rules added to the codegen prompt: `Place content on a grid: at most 6 text items on screen at once; leave 0.4 units between any two objects.`, `Never place text on top of other text; use next_to(..., buff=0.3) or arrange(..., buff=0.3).`, `Fade out or remove an object before drawing something else in its place.`, `Text longer than 28 characters must be split over lines or scaled with scale_to_fit_width.`, `Call fit_in_frame on every group you build.` The storyboard prompt gains `Plan at most 6 labelled items per beat and say where each one sits (left, right, top, bottom, centre).`

- [ ] **Step 1: Write the failing tests** (fake Manim-like objects are not needed: build real `Text` and `Rectangle` mobjects in a scene-like stub that exposes `mobjects`): `test_two_overlapping_texts_are_reported`, `test_a_text_inside_a_box_is_not_an_overlap`, `test_text_leaving_the_frame_or_in_the_subtitle_area_is_reported`, `test_invisible_text_is_ignored`, `test_check_layout_names_the_beat_and_the_pair`, `test_a_layout_issue_triggers_a_retry_with_the_message_in_the_prompt`, `test_after_all_attempts_the_least_flawed_scene_is_used_with_a_warning`, `test_the_codegen_prompt_contains_the_layout_rules`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** "Check generated scenes for overlapping and off-screen text".

### Task 7: A 3D scene the model can follow

**Files:** Create `backend/animation/codegen/examples/three_d_layers.py`; modify `backend/animation/codegen/generator.py` (prompt), `backend/animation/storyboard.py` (prompt), tests.

**Interfaces:**
- The example is a complete scene `class SectionScene(ThreeDScene):` with `clock = BeatClock(self)` as the first line, three beats, a stack of three labelled layers drawn as 3D blocks, camera orientation set with `self.set_camera_orientation(phi=65 * DEGREES, theta=-45 * DEGREES)`, a slow `self.begin_ambient_camera_rotation` for one beat, labels added with `self.add_fixed_in_frame_mobjects`, and `clock.end_beat()` at the end of each beat. It uses only allowed imports.
- Codegen prompt rule: `When a beat is about something spatial (layers of a network, matrices as grids, vectors, planes, stacks), you may use class SectionScene(ThreeDScene): follow the 3D example; keep labels fixed in frame.` Storyboard rule: `A visual may be described as 3D when the idea is spatial (layers, matrices, vectors, stacks).`

- [ ] **Step 1: Write the failing tests:** `test_the_3d_example_passes_the_validator`, `test_the_codegen_prompt_mentions_the_3d_rule_and_includes_the_3d_example`, `test_a_threed_scene_with_one_class_named_section_scene_is_valid`, `test_the_storyboard_prompt_allows_3d_visuals`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Write the example and the prompt changes.**
- [ ] **Step 4: Render the example for real** with Manim at low quality (`-ql`) using `BEAT_DURATIONS='[2.5,2.5,2.5]'`; expected: a video is produced, the beat report has 3 rows and no layout issues. Then run the whole suite.
- [ ] **Step 5: Commit** "Add a 3D example scene and allow 3D visuals".

### Task 8: Measure before and after

**Files:** Create `docs/superpowers/results/2026-11-06-teaching-and-animation-quality.md`; scratch scripts under `.superpowers/scratch/` (not committed). Calls the real model.

- [ ] **Step 1: Baseline (done before Task 1):** `.superpowers/scratch/teaching_eval.py baseline` on 8 fixed topics, saving words, requested minutes, sections and the judge's list of undefined terms.
- [ ] **Step 2: After:** run the same script with label `after` (the studio pipeline now includes the knowledge base, must_cover, notes and the term review) and compare: mean undefined terms per topic, words against the requested duration, sections, and whether the LR request now defines item, closure and parsing table. Read the LR script in full.
- [ ] **Step 3: Layout and 3D on real renders:** for three sections (one text-heavy, one with a diagram, one spatial) run the codegen path with the real model and Manim, count layout issues in the beat reports per attempt, and record whether the 3D example was followed for the spatial one. Report render time.
- [ ] **Step 4: Write the results note** with the before/after table, what improved, what did not, and the cost (extra model calls and seconds per video). Commit "Record the teaching and animation quality measurements" and report in chat, including any topic that got worse.

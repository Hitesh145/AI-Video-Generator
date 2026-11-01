# Paper Videos — Design

**Date:** 2026-11-01
**Status:** Draft for review
**Branch:** `feature/rag-ingestion` (built on `main`)

Words marked **(my call)** are decisions the author made without being told, so the owner can check them. Everything else comes from the owner's answers.

## 1. Intent

Research papers are long and hard to read. EduGen AI already turns a typed request ("Explain binary search to a beginner") into a narrated, animated video. This feature lets a person add research papers and get videos that explain **that paper**, so they can understand it without reading all of it.

**Who uses it:** anyone: students, teachers, curious people. They are not assumed to be experts.

**Why accuracy is the whole point:** if a video teaches something the paper does not say, the feature has failed, however good it looks. Every design choice below puts correctness ahead of speed, polish or coverage.

## 2. What the user can do

1. **Create an account** with email and password, and log in. Everything below is private to that account.
2. **Add papers** (PDF upload). Each paper appears in a personal library with a status (processing, ready, failed) and basic details (title, page count, number of videos).
3. **Open a paper** and ask for videos about it. One paper can have many videos, for example "summary of the paper", "the method", "the results", "limitations", or any topic typed in a box.
4. **Watch the videos** made from that paper, listed on the paper's page. A video still being made shows real progress.
5. **See how well the paper was read.** After upload, the paper's page says what was read reliably and what was not (see section 5).

### Screens (mockups were reviewed in the browser)
- **Library:** list of the user's papers, an "Add paper (PDF)" button, per-paper status.
- **Paper page:** quick buttons (summary, method, results, limitations) plus a box for any topic, a "Generate video" button, and the list of videos from this paper. The owner liked a mix of two options; a tickable outline of the paper's own sections (choose sections to explain) is an **optional extra (my call)**, not the main control.
- **Login / sign up.**
- The existing studio page (ordinary topic videos) stays and now requires login.

## 3. Rules for what a video may say

- **One paper per video.** A video uses only the selected paper. Papers are never mixed.
- **Only what the paper supports.** Each statement in a video must be backed by a specific passage of the paper. Anything that cannot be backed is left out or flagged, never presented as the paper's claim.
- **Numbers and equations are copied, not re-typed by the AI.** They come from the paper's own text. The AI explains around them. Equations are shown as plain text with the paper's symbols preserved exactly (sigma, omega, subscripts and so on); the equation must match the paper. **Decided with the owner:** an equation is shown as text only when its plain-text form loses nothing (a simple one-line equation). For complex equations (fractions, sums with limits, integrals, matrices) the video shows the paper's own cropped picture of the equation, exact by construction, and the narration explains it. An equation counts as "read reliably" only when the text version loses nothing; otherwise it gets the picture. If even the picture cannot be produced, the equation is reported as unreadable and not used.
- **Figures from the paper may be reused** in the video.
- **Topic not in the paper.** If the request is not covered, the app shows a popup: the paper does not cover this topic, but it can be explained from general knowledge, with an option to generate a normal video without the paper. **(my call)** If the paper only touches the topic briefly, the popup says so and offers two choices: a short video of just what the paper says, or a normal general video. Videos made without the paper are labelled "not from the paper" in the list. The app decides coverage by how well the paper's text matches the request, and when unsure it leans toward "not covered" rather than inventing support.
- **Unreadable content.** If part of the paper cannot be read reliably, the app says so plainly, for example "3 equations on pages 5 and 7 could not be read reliably", on the paper's page, and the video states nothing drawn from those parts.

## 4. Anti-goals

The feature fails even if it technically works when:
- a video contains a wrong number, symbol, equation or claim attributed to the paper;
- a key result of the paper is silently missing while the video sounds complete;
- unreadable parts are guessed at instead of reported.

## 5. Reading the paper

- Text, headings, figures, captions, tables and equations are extracted from the PDF into a stored, structured form with page numbers. The ingestion code for this already exists on this branch (Docling parsing, structure-aware chunking, PostgreSQL + pgvector storage with Gemini embeddings, Alembic migration). It is untested against a real Postgres database or the live Gemini embedding API.
- **Vector storage (decided with the owner).** PostgreSQL with the pgvector extension, as in the existing migration `0001_rag_storage.py`. pgvector must be installed on the owner's PostgreSQL 18 (native Windows) before the database layer can run. Similarity search runs in SQL and is always filtered by owner, and by paper when one is selected. Accounts, papers, videos and jobs live in the same database and the same Alembic migration chain, so the whole app, including the existing studio page, requires PostgreSQL to be running.
- **Text inside images** (scanned pages, equations pasted as pictures, charts) gets an image-reading step in addition to the PDF text parser. Content read this way is marked lower-confidence, and the video shows the original cropped image next to the text version so the viewer can check it. **(my call)** First try the image/OCR and formula support built into the parser already in use, and add a Gemini vision step only for what it misses.
- **Equations (decided with the owner):** the parser's equation reading is currently switched off. It is switched on so each equation has a text form and a saved cropped image. Simple equations may be shown as text; complex ones are shown as the cropped picture plus narration (section 3). The accuracy check compares numbers and symbols against the stored text form, or, for picture-only equations, checks the narration does not state a different formula.
- After upload, a "reading report" per paper lists what was read well and what was not.

## 6. How a video is made (builds on the existing pipeline)

The existing pipeline stages are: understand request → knowledge → plan → script → choose animations → animate sections → assemble. Videos from a paper reuse it with these changes **(my call)**:
- The `knowledge` stage takes its facts from retrieved passages of the selected paper instead of from the LLM's memory, using the same knowledge-base format, with each fact carrying its source passage and page. "Nothing relevant found" becomes a recorded gap.
- Retrieval happens in two steps: a paper-level pass for the plan, then per-section retrieval (using each planned section's title and goals) for the script.
- Retrieval combines meaning-based vector search and keyword search over the same passages, merged by rank (reciprocal rank fusion). More elaborate methods (section-hierarchy search, cross-reference following) are only added if an evaluation shows a benefit.
- Each script sentence keeps the ids of its supporting passages so the video and logs can cite page and section.
- **Accuracy check before finishing:** every number and equation in the script must appear in a cited passage (a simple deterministic check), and an AI verification pass flags sentences the cited passages do not support, one call per section. Failed sentences are revised or removed, and what remains unresolved is shown to the user as a warning.
- Retrieved passages and queries are written to the existing per-run `llm_calls.md/json` debug log so a wrong video can be traced to retrieval or to generation.
- Existing limits apply: the animation kit draws text only (no LaTeX), so equations are text, and figures need a new small helper for showing a stored image.

## 7. Accounts **(my call)**

Built in the existing Python (FastAPI) backend. Passwords are stored only as salted hashes. Login sessions use a secure token. Login attempts are rate-limited. Every paper, video and job row carries a user id from the start, so ownership never has to be retrofitted; users can only read their own. Ordinary topic videos belong to the user too.

## 8. Non-goals (explicitly left out for now)

Sharing or public papers, videos across several papers, "forgot password" and email verification, chatting with a paper in text, editing a finished video, file types other than PDF (Word, web pages, arXiv links), mobile app, other languages or voices, and deployment at scale. It should run on the owner's machine first, designed so deployment is possible later.

## 9. Decided versus left to the builder

**Decided by the owner:** the user-facing behaviour in sections 2-4, including complex equations shown as the paper's own picture; pgvector for vector search; accuracy over everything else; email-and-password accounts; everything private to an account; the non-goals.

**My calls (above):** reuse of the existing pipeline and Docling/Gemini choices already on this branch; the whole-paper-versus-retrieval decision rule; two-step retrieval with vector + keyword search merged by rank; the deterministic plus AI accuracy check; image-reading approach; account implementation details; the optional section picker; the weak-coverage popup variant.

**Left to the builder:** chunk sizes and retrieval settings (tuned by measurement), page layout details, error message wording, file and module layout, and the order of work inside each project.

## 10. Order of work

Several independent projects, each getting its own plan **(my call on order)**:
1. Accounts (small), with a user id on all data from the start.
2. Paper library: upload, reading, the reading report, image/equation reading.
3. Grounded videos: retrieval, the pipeline changes, the "not in the paper" popup.
4. Accuracy checking.
5. Screens, built alongside each step.

Before step 3, build a small question set for a real paper (including questions whose answer is absent) and measure retrieval quality, then decide whether any heavier retrieval method is needed. Also compare against simply giving the model the whole paper as numbered passages, to be sure retrieval is helping. **Decision rule (my call):** the winner is whichever produces fewer unsupported or wrong claims, measured on number and equation correctness and on an AI-checked unsupported-claim rate over the question set. If the whole-paper approach is better or equal, the embedding step is dropped, since accuracy is the owner's priority and fewer moving parts is better. Citations and the accuracy check work either way.

## 11. How we will know it works

- On sample papers, every number and equation in a generated video matches the paper (checked against the source text).
- Requests about topics absent from the paper trigger the popup rather than an invented explanation.
- Unreadable parts are reported, and nothing from them appears in a video.
- One user cannot see another user's papers or videos.

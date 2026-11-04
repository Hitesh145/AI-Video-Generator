# EduGen AI

EduGen AI turns a topic or a research paper into a narrated, animated explainer video.

- **Studio:** type a topic ("explain LR parsing in detail") and get a video.
- **Paper videos:** upload a research paper (PDF), ask a question about it, and get a video that says only what the paper says. Every sentence is checked against the paper's own passages, numbers and equations are copied exactly, and anything the paper does not support is left out.

Accuracy comes first: paper videos are grounded, checked, and traceable, and every user's papers and videos are private to that user.

## How it works

```
Browser (React + Vite)  <--HTTP + session cookie-->  FastAPI backend  -->  PostgreSQL + pgvector
                                                          |                 files on disk
                                                          +--> Gemini API   Docling, Manim, edge-tts, ffmpeg
```

A video is made as a **background job** with eight stages: analyze, knowledge, plan, script, check, route, animate, assemble. The browser polls the job for live progress.

### Studio videos (a topic, no paper)

1. **Analyze:** the request becomes a structured lesson request (topic, audience, goal, duration, depth, and the terms the learner named).
2. **Knowledge:** reference facts, gaps and conflicts for the topic.
3. **Plan:** ordered sections, prerequisites first, with terms to define and a worked example per section.
4. **Script:** narration with a word budget per section, terms defined where first used, then a review pass that fixes terms left unexplained.

### Paper videos (a question about an uploaded paper)

1. **Ingest:** the PDF is parsed (Docling), split into passages, embedded and stored in PostgreSQL with pgvector. A paper that is only partly read is refused rather than stored.
2. **Retrieve:** the question is embedded and matched against that paper's passages (vector search).
3. **Coverage check:** *covered* (similarity 0.75 or more), *weak* (0.60 to 0.75, a shorter video with a note) or *absent* (below 0.60, no paper video).
4. **Grounded writer:** one model call from the numbered passages. It cites passage ids, copies numbers and equations exactly, and may add a short general-knowledge definition or everyday example in a separate field. That field is spoken after the marker "Some background that is not from the paper:" and is never presented as the paper's content.
5. **Guards:** cited ids must exist, numbers and equations must appear in the cited text, and background text must be plain (no digits or claims about the paper).
6. **Claim checker:** a second model pass judges every sentence and must quote the passage that supports it. Unsupported sentences trigger one rewrite, and what still fails is removed.
7. **Evidence trail:** each video's run folder holds `evidence.json`, `citations.json`, `claim_check.json` and `qc_warnings.json`.

### Animation and assembly (shared)

Each section gets a storyboard and Manim code written by the model (2D and 3D scenes). A layout check looks for overlapping or off-screen text and for lines crossing labels, and sends problems back for a retry. Narration is voiced with edge-tts, timed to the animation, and ffmpeg assembles the final MP4 with subtitles.

## Tech stack

| Part | Technology |
|---|---|
| Frontend | React 19, Vite, TypeScript, Tailwind |
| Backend | FastAPI (Python) |
| Database | PostgreSQL with pgvector, Alembic migrations |
| Model | Google Gemini (default `gemini-3.5-flash-lite`, set with `GEMINI_MODEL`) |
| PDF parsing | Docling |
| Animation | Manim |
| Voice and video | edge-tts, ffmpeg |

## Repository layout

```
backend/
  main.py            app wiring and the studio endpoints
  accounts/          sign-up, login, sessions, the per-user video library
  papers/            paper upload, status, retry, and the paper-video endpoints
  rag/               PDF parsing, chunking, embeddings, PostgreSQL storage
  retrieval/         vector / keyword / hybrid search, evidence, coverage check
  services/          analyzer, planner, script writer, term review, grounded writer,
                     claim checker, jobs, demo video pipeline
  animation/         storyboard, Manim code generation, layout checks, section animator
  evaluation/        retrieval evaluation (questions, metrics, runner)
  alembic/           database migrations
  tests/             automated tests
frontend/src/        React app (Studio, paper library, paper page, login)
```

## Setup

### Requirements

- Python 3.11+ and Node.js (or Bun)
- PostgreSQL with the pgvector extension installed
- ffmpeg on the PATH
- A Gemini API key

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate     # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env`:

```
GEMINI_API_KEY=your-key
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/edugen
# optional
GEMINI_MODEL=gemini-3.5-flash-lite
MAX_PAPER_UPLOAD_MB=...
MAX_CONCURRENT_INGESTIONS=...
RAG_ASSET_DIR=...
AUTH_COOKIE_SECURE=false
```

The URL must start with `postgresql+psycopg://`. `RAG_DATABASE_URL` takes precedence over `DATABASE_URL` if both are set.

Apply the migrations and start the server:

```bash
alembic upgrade head
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install        # or: bun install
npm run dev        # http://localhost:5173
```

The frontend calls the backend on port 8000 of the same host.

## Tests

```bash
cd backend
python -m pytest tests -q
```

Some tests need a PostgreSQL database (`RAG_TEST_DATABASE_URL`) and are skipped without one. Two tests that run ffmpeg (`test_timing.py`, `test_video_library.py`) have failed intermittently in full runs on one Windows machine and pass when run alone.

## Retrieval evaluation

```bash
cd backend
python -m evaluation.run --modes vector keyword hybrid
```

This fetches pinned public papers, stores them, validates the question files and compares the search modes. Use `--validate-only` to check the question files without calling the model.

## Known limitations

- Scripts for paper videos can still be short; the model does not always follow the length target.
- No reranking is applied to retrieved passages.
- Equations and figures are not shown as pictures.
- Scenes can look visually thin or unlabelled; the layout check finds collisions, not weak content.
- Jobs are kept in memory, so a backend restart loses any job still running (finished videos are kept).
- Quality figures were measured on a small number of topics and papers with one run each.

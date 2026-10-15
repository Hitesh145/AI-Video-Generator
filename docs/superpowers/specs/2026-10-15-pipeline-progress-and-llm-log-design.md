# Real Pipeline Progress, Video Display and LLM Call Log — Design Spec

**Date:** 2026-10-15
**Status:** Draft for review
**Branch:** `feature/studio-progress-and-llm-log` (built on `feature/beat-synced-scenes`, which is not yet merged)

## 1. Goal

Three problems reported after running the studio:

1. **The production pipeline panel is fake.** `frontend/src/App.tsx` advances one stage every 2.6 s on a timer while the backend does its work inside one blocking request, so the panel cannot show what is really happening.
2. **Generated videos are not shown in the frontend.** Findings (verified against the latest runs):
   - The result panel renders only an "MP4 ready" badge. It has no `<video>` element.
   - Every `lesson_demo.mp4` has its `moov` index at the end of the file (`ftyp, free, mdat, moov`) because `mux_video` does not use `-movflags +faststart`.
   - `/media` is a Starlette 0.38.6 `StaticFiles` mount, which ignores `Range` requests: a request with `Range: bytes=0-99` returned `200` with no `Content-Range`.
   - A tail-indexed file served without ranges is expected to leave the library cards blank or stalled. This last step cannot be confirmed without a browser; it is verified here through file layout and HTTP responses.
3. **No way to see what the LLM was asked and what it answered.** Debugging and understanding the workflow needs the input and output of every LLM call (analyzer, knowledge, planner, script writer, router, narrator, storyboard, codegen) in one place per run.

### Success criteria
1. While a video is generating, the pipeline panel shows the stage the backend is really in, with a section counter during animation ("Animating section 3 of 8 · algorithm trace"). Completed stages are marked from backend events, not from time.
2. A failed generation shows which stage failed and its error message.
3. After generation the finished video plays in the result panel. Library cards load their first frame and the video can be seeked, for old videos too.
4. Every run folder contains `llm_calls.md` and `llm_calls.json` listing, in order, every LLM call with its step label, timing, full prompt, and output or error. Both files exist even when the run fails.
5. `POST /lesson/generate-demo-video` behaves exactly as before.

### Out of scope
- LLM call timeout and retry (an earlier `getaddrinfo failed` run showed that one network blip kills a run; tracked separately).
- Job persistence across a server restart, job cancellation, and resuming the UI after a page reload.
- Logging TTS, ffmpeg or Manim subprocess output.
- Frontend unit-test infrastructure (the frontend has none; it is verified by `tsc -b`, the production build, lint and a manual check).

## 2. Design

### 2.1 Run context (shared plumbing) — `services/run_context.py` (new)

A `contextvars.ContextVar` holds the active run. Passing it implicitly avoids changing the signatures of `SectionAnimator.animate`, `AnimationRouter`, `StepNarrator`, `Storyboarder` and `CodegenRenderer`, whose fakes in the existing tests would otherwise break.

- `RunContext(recorder: LLMCallRecorder, progress: ProgressReporter)`.
- `activate(run) -> token` / `reset(token)`; `current_run() -> RunContext | None`. With no active run (all existing tests, direct calls) every helper below is a no-op.
- `llm_step(label)`: a context manager that pushes a label onto a stack. A call recorded inside it gets the joined labels, e.g. `section 3 · codegen`. Several calls under the same label get `#2`, `#3` suffixes (retries, codegen attempts).
- `report_stage(key, detail=None)`, `report_section(index, total, title, path=None)` forward to the active run's progress reporter.

### 2.2 LLM call log — `services/llm_recorder.py` (new)

- `RecordingLLM(inner)` wraps any object with `generate` and/or `generate_structured` (real `LLMService` or `FakeLLM`). `main.py` builds `llm_service = RecordingLLM(LLMService())`; every service keeps sharing one instance. Delegating `__getattr__` keeps other attributes reachable.
- For each call it records `{seq, label, kind ("structured" | "text"), schema (class name or null), started_at (ISO, UTC), duration_seconds, prompt, output, error}`. `output` is the parsed model as a dict for structured calls, the string for text calls, and `null` on error; `error` is `"ExceptionType: message"` or `null`. The exception is always re-raised unchanged.
- `LLMCallRecorder` keeps the records in memory (thread-safe) so calls made before the run folder exists are not lost. `bind_directory(path)` writes everything so far and from then on rewrites both files after every call. `flush()` rewrites them again. Writing never raises into the pipeline (a write failure is swallowed after one `logging.warning`).
- Files in the run folder:
  - `llm_calls.json`: `{"request": <user text>, "started_at", "finished_at", "status": "running|completed|failed", "error": null|str, "calls": [...]}`.
  - `llm_calls.md`: a header (request, status, call count, total LLM seconds), a one-line index table (`#`, step, schema, seconds, ok/error), then one section per call: the step label, timing, the prompt in a fenced block, and the output (pretty-printed JSON in a fenced block, or the error). Fences are one backtick longer than the longest backtick run in the content, so prompts that contain triple backticks do not break the file.
- The run folder is created only after the script is written (it is named after the topic). If the pipeline fails before that, the files are written to `output/_failed/<run_id>/` so the failure is still debuggable. `/videos` only lists `lesson_demo.mp4`, so these folders never appear in the library.

### 2.3 Pipeline instrumentation — `DemoVideoService`, `SectionAnimator`

`DemoVideoService.generate_demo_video` (signature unchanged) reports real stages through the run context. Stage keys and labels (the single source for the UI):

| key | label | reported |
|---|---|---|
| `analyze` | Understanding the request | before the analyzer call |
| `knowledge` | Gathering resources | before the knowledge call (skipped if no agent) |
| `plan` | Building the lesson plan | before the planner call |
| `script` | Creating the script | before the script writer call |
| `route` | Choosing animations | start of `SectionAnimator.animate` (router call) |
| `animate` | Animating sections | per section, with the counter |
| `assemble` | Assembling the video | before concat, audio build, subtitles, mux |

Narration is synthesised per section inside `animate`, so the old separate "Adding narration" stage is folded into the section detail. For a section the detail line says what is running: `planning beats`, `narrating`, `rendering`. `SectionAnimator` wraps each section in `llm_step(f"section {n} · …")` and calls `report_section`.

When `generate_demo_video` runs inside an active run it also binds the recorder to the run folder as soon as `_create_output_dir` returns. Outside a run context it behaves exactly as before.

`DemoVideoResponse` gains `video_url: str | None = None` (`"/media/<relative path>"`, filled by the service). The existing `video_path` is unchanged.

### 2.4 Jobs API — `services/job_service.py` (new), endpoints in `main.py`

- `JobService.start(request) -> job_id` creates a job and runs `demo_video_service.generate_demo_video` on a daemon thread with an active `RunContext`. State is in memory behind a lock; jobs are kept until the process ends. The job runner sets the final status, `finished_at` and any error on the recorder and flushes in a `finally`, so failed runs keep their log.
- `POST /lesson/jobs` (body `UserLessonRequest`) returns `{"job_id": ...}` with status 202.
- `GET /lesson/jobs/{job_id}` returns:
  ```
  {
    "job_id", "status": "running|completed|failed",
    "elapsed_seconds",
    "stages": [{"key","label","state": "pending|current|done|failed","detail": str|null}],
    "section": {"index","total","title","path"} | null,
    "result": <DemoVideoResponse> | null,
    "error": {"stage": str, "message": str} | null
  }
  ```
  Unknown id returns 404. The stage list always contains every stage so the UI never hardcodes labels; `knowledge` is marked `done` with detail "skipped" when there is no agent.
- A stage becomes `current` when reported and the previous one `done`; on an exception the current stage becomes `failed` and `error` carries `ExceptionType: message`.
- `POST /lesson/generate-demo-video` is untouched.

### 2.5 Video serving and display

- `rendering/video_renderer.mux_video`: add `-movflags +faststart` so new files have the index at the start.
- `rendering/faststart.py` (new): `is_faststart(path)` reads the top-level MP4 boxes and returns whether `moov` precedes `mdat`; `ensure_faststart(path)` remuxes with `-c copy -movflags +faststart` into a temp file next to it and replaces the original. It is a no-op when the file is already fast or when ffmpeg fails (logged). `/videos` calls it for each listed video, so old runs are fixed on first listing.
- `/media` becomes a route `GET /media/{path:path}` (replacing the `StaticFiles` mount) in `services/media_response.py`. It resolves the path under `output_root` and returns 404 for anything outside it or not a file, sets the `Content-Type` from the extension, and supports a single `Range: bytes=a-b` / `a-` / `-n` request with `206`, `Content-Range` and `Accept-Ranges: bytes`. An unsatisfiable range returns `416`; no range returns `200` with `Accept-Ranges`. It streams in chunks.
- Frontend:
  - The result panel shows `<video controls src=MEDIA_URL+video_url>` plus the existing section list and a download link.
  - The library keeps its cards, using `preload="metadata"`.
  - The stray `console.log` of the fetch response is removed.

### 2.6 Frontend progress — `App.tsx`

- `generateVideo` posts to `/lesson/jobs`, then polls `GET /lesson/jobs/{id}` every 1 s until `completed` or `failed` (and stops on unmount). The elapsed counter uses the server's `elapsed_seconds`.
- The stage list renders from `job.stages` (labels and detail come from the server). The current stage shows the section counter and the detail line. A failed stage is styled as an error and the error text is shown under the prompt.
- Network errors while polling are retried up to 5 times in a row before "Lost connection to the server" is shown.
- The generate button is disabled while a job is running.

## 3. Error handling

| Failure | Result |
|---|---|
| Any exception in the pipeline thread | job `failed` with stage and message; LLM log written with status `failed` |
| Failure before the run folder exists | log under `output/_failed/<run_id>/` |
| Log write error | swallowed after a warning; never fails the run |
| `ensure_faststart` fails | video served as is, warning logged |
| Range outside the file | `416` |
| Path traversal in `/media` | `404` |
| Poll network error | retried 5 times, then message shown |

## 4. Testing

- `RecordingLLM` with `FakeLLM`: records prompt, output, schema and label for structured calls; records errors and re-raises; numbers repeated labels; no-op without a run context.
- `LLMCallRecorder`: buffered calls are written on `bind_directory`; both files rewritten per call; JSON round-trips; the Markdown contains the index table, prompts and outputs; a prompt containing a triple-backtick fence still renders a valid fenced block; a write failure does not raise; failed-run directory fallback.
- Stage reporting: a `DemoVideoService` test with fakes (existing pattern) checks the ordered stage keys, `knowledge` skipped, and the section counter via a fake animator that calls `report_section`.
- `JobService`: a fast fake pipeline reaches `completed` with all stages `done`; a pipeline that raises ends `failed` with the failing stage; unknown id gives 404; the old endpoint test keeps passing unchanged.
- `faststart`: `is_faststart` on a synthetic box sequence; `ensure_faststart` on a real small ffmpeg-made file (marked `slow`) turns tail-indexed into head-indexed and keeps the duration.
- `mux_video`: the output of a real small mux has `moov` before `mdat` (slow).
- Media route: `200` full file; `206` for `bytes=0-99`, `bytes=100-` and `bytes=-50`; `416`; `404` for `..` traversal and missing files; content type `video/mp4`.
- Existing end-to-end test extended: after the run `llm_calls.json` and `llm_calls.md` exist, contain every FakeLLM call in order with labels such as `section 1 · storyboard`, and status `completed`.
- Frontend: `tsc -b`, `vite build` and lint pass; manual check against a live run: the pipeline panel follows real progress, the result player works, library cards show a first frame and seek.

## 5. Decisions taken in review
- The debug file is written as **both** Markdown and JSON.
- The old blocking endpoint **stays exactly as it is**; the new job endpoints are added next to it.

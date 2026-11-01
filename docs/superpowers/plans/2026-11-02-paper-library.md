# Paper Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a logged-in user upload research-paper PDFs, watch each one be read in the background, and see their library on a separate "Paper videos" page reached from a button in the nav bar.

**Architecture:** A new `papers` package holds a `papers` table (one row per upload with a status), a `PaperIngestor` that runs the existing parse → chunk → store → embed code in stages, and a `PaperService` that validates and saves uploads, de-duplicates, runs ingestion on a background thread (one at a time) and recovers from restarts. `POST/GET /papers` endpoints are private to the owner. The React app gains a nav bar with two pages (Studio, Paper videos), switched by the URL hash (no new dependency); the papers page has the upload box, the library with live status, and a per-paper page with the reading report.

**Tech Stack:** FastAPI + `python-multipart` (uploads), SQLAlchemy 2 / Alembic / PostgreSQL + pgvector, Docling (existing), React 19 + Vite + TypeScript, pytest.

**Spec:** `docs/superpowers/specs/2026-11-01-paper-videos-design.md` (sections 2, 3 "unreadable content", 5, 8, 10). This is project 2 of 5. It does **not** include generating videos from a paper (project 3), claim checking (project 4), or the equation/figure crops (a later part of project 2, planned separately once uploads work).

## Global Constraints

- Everything is private to the logged-in owner; another user's paper answers **404**, never 403 (spec section 7).
- Only PDF uploads (spec section 8). Statuses follow the spec: queued, parsing, chunking, storing, embedding, ready, failed (spec's "pending, parsing, chunking, embedding, indexed, failed", with storing split out).
- "Unreadable parts are reported plainly": the reading report lists what the parser reported and never hides a problem (spec section 3).
- Runs on the owner's machine: ingestion is one background thread at a time; no queue service (spec section 10: "do not add a new queue").
- The sample PDF and everything under `backend/data/` stay out of git. Never stage `backend/IJRTI2304061.pdf`, `backend/IJRTI2304061_assets/`, `backend/rendering/__init__.py` or `backend/output/**`.
- Backend tests run from `backend/`; the default `python -m pytest -q` excludes `slow`; the full run is `python -m pytest -q -m "slow or not slow"`. Integration tests need `RAG_TEST_DATABASE_URL`: the same URL as `RAG_DATABASE_URL` with the database name `edugen_rag_test` (that database exists on the owner's server). Set it in the shell for the session; do not write it into `.env`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Stage files by name only.
- Frontend checks: `bun run build` and `bun run lint` in `frontend/` pass (lint keeps its one pre-existing `set-state-in-effect` warning). The frontend has no unit-test runner.

## Review Focus

1. **Hostile or odd uploads:** an empty file, a non-PDF renamed `.pdf`, a file over the size limit (rejected early, nothing left on disk), and a filename such as `..\..\x.pdf` or `résumé 论文.pdf` (the client's name is only a display label; files are stored under the paper id). Tested in Task 3 and 4.
2. **The same PDF twice:** the same user uploading it again gets the existing paper back, not a second copy or a second ingestion; two different users each get their own. Tested in Task 3.
3. **A restart mid-processing:** a paper that was parsing when the server stopped must not sit at "parsing" forever; it becomes failed with a clear message. Tested in Task 3.
4. **A failure at any stage:** the paper ends as failed with a readable one-line reason, temporary files are removed, and if only embedding failed the stored text is kept and "retry" finishes the job without re-uploading. Tested in Task 3.
5. **Someone else's paper or a stale link:** `GET /papers/<other user's id>` and `/#/papers/<unknown id>` show "not found", never another user's data and never a crash. Tested in Task 4 and checked by hand in Task 7.

---

## File Structure

**Create**
- `backend/papers/__init__.py`, `models.py` (Paper), `repository.py` (PaperRepository, PaperRecord, PaperReport), `ingestor.py` (PaperIngestor), `service.py` (PaperService + errors), `router.py` (create_papers_router).
- `backend/alembic/versions/0003_papers.py`.
- Tests: `tests/test_paper_repository.py`, `tests/test_paper_ingestor.py`, `tests/test_paper_service.py`, `tests/test_papers_router.py`; additions to `tests/test_postgres_integration.py`, `tests/test_main_requires_login.py`, `tests/accounts_helpers.py`.
- Frontend: `frontend/src/useHashRoute.ts`, `Layout.tsx`, `StudioPage.tsx`, `PapersPage.tsx`, `PaperDetailPage.tsx`.

**Modify**
- `backend/rag/db_models.py` (register the papers model), `backend/main.py`, `backend/requirements.txt`, `backend/data/.gitignore` (new, ignores `uploads/`), `backend/rag/PHASE3_STORAGE_README.md` (upload notes).
- Frontend: `App.tsx` (becomes the page switcher), `index.css`.

## Calls made while planning (not in the spec)

- **A `papers` table owns the status,** because a library entry must exist (and show "parsing") before the `rag_documents` row does. It also stores the display `title` and `page_count` once reading finishes, so the library list needs no join.
- **Nav label "Paper videos"** and URL hashes `#/` (Studio), `#/papers`, `#/papers/<id>`; plain hash routing, no router library.
- **Upload limit 50 MB** (`MAX_PAPER_UPLOAD_MB` environment variable overrides it); one ingestion at a time (`MAX_CONCURRENT_INGESTIONS`, default 1) because Docling is memory-hungry.
- **No delete button yet:** deleting a paper has to deal with content-addressed asset files shared between users; it is deferred, not forgotten.
- **Reading report for now** = what the parser already knows: page count, number of text passages (chunks), number of figures, and the parser's own warnings. The per-equation "could not be read reliably" detail needs the equation reading work and comes later.
- **Retry** only re-runs the embedding step (the one that depends on the network); a paper that failed while parsing must be uploaded again.

---

### Task 1: The `papers` table and repository

**Files:**
- Create: `backend/papers/__init__.py`, `backend/papers/models.py`, `backend/papers/repository.py`, `backend/alembic/versions/0003_papers.py`, `backend/tests/test_paper_repository.py`
- Modify: `backend/rag/db_models.py` (bottom import), `backend/tests/accounts_helpers.py` (create the papers table too), `backend/tests/test_postgres_integration.py`

**Interfaces:**
- Consumes: `rag.db_models.Base`, `accounts.models.User`, `make_session_factory()`.
- Produces (`papers.models`): `Paper` with `paper_id` (String(36) pk), `user_id` (FK users, CASCADE, indexed), `filename` (String(255)), `size_bytes` (Integer), `sha256` (String(64)), `status` (String(16)), `detail` (Text, nullable), `title` (Text, nullable), `page_count` (Integer, nullable), `document_id` (String(36), nullable, FK `rag_documents.document_id` ON DELETE SET NULL), `created_at`, `updated_at` (both server default now); unique `(user_id, sha256)` named `uq_papers_user_sha256`. Constants `QUEUED, PARSING, CHUNKING, STORING, EMBEDDING, READY, FAILED` (the lowercase strings) and `IN_PROGRESS` (a frozenset of the five non-final ones).
- Produces (`papers.repository`): frozen dataclasses `PaperRecord(paper_id, user_id, filename, size_bytes, sha256, status, detail, title, page_count, document_id, created_at, updated_at)` and `PaperReport(title: str | None, authors: list[str], page_count: int | None, chunk_count: int, figure_count: int, warnings: list[str])`; `PaperRepository(session_factory)` with
  `create(user_id: str, filename: str, size_bytes: int, sha256: str) -> PaperRecord` (status `queued`; `IntegrityError` on a duplicate `(user_id, sha256)`),
  `find_by_hash(user_id: str, sha256: str) -> PaperRecord | None`,
  `get(paper_id: str, user_id: str) -> PaperRecord | None` (`None` for unknown or someone else's),
  `list_for_user(user_id: str) -> list[PaperRecord]` (newest first),
  `update(paper_id: str, **fields) -> None` (only `status`, `detail`, `title`, `page_count`, `document_id`; always bumps `updated_at`),
  `fail_interrupted(message: str) -> int` (every `IN_PROGRESS` paper becomes `failed` with `detail=message`; returns how many),
  `report(document_id: str) -> PaperReport` (reads `rag_documents`, chunk and figure counts; PostgreSQL only).

- [ ] **Step 1: Write the failing tests** in `tests/test_paper_repository.py` (SQLite; create two users with `User` rows first, as `test_video_repository.py` does):

```python
def test_create_starts_queued_and_is_private_to_the_owner():
    record = repo.create(one, "paper.pdf", 1234, "a" * 64)
    assert (record.status, record.detail, record.document_id) == ("queued", None, None)
    assert repo.get(record.paper_id, one).filename == "paper.pdf"
    assert repo.get(record.paper_id, two) is None

def test_the_same_pdf_cannot_be_added_twice_by_one_user_but_two_users_can():
    repo.create(one, "a.pdf", 1, "a" * 64)
    repo.create(two, "a.pdf", 1, "a" * 64)                      # fine
    with pytest.raises(IntegrityError):
        repo.create(one, "again.pdf", 1, "a" * 64)
    assert repo.find_by_hash(one, "a" * 64).filename == "a.pdf"
    assert repo.find_by_hash(one, "b" * 64) is None

def test_list_is_newest_first_and_only_the_users_own():
    # user one gets three papers with created_at set one minute apart, user two gets one;
    # list_for_user(one) returns user one's three, newest first; list_for_user(two) returns only the fourth
    # three papers with created_at set 1 minute apart for user one, one for user two

def test_update_changes_only_the_named_fields_and_bumps_updated_at():
    record = repo.create(one, "a.pdf", 1, "a" * 64)
    repo.update(record.paper_id, status="parsing", detail="Reading the PDF")
    after = repo.get(record.paper_id, one)
    assert (after.status, after.detail, after.filename) == ("parsing", "Reading the PDF", "a.pdf")
    assert after.updated_at >= record.updated_at

def test_update_rejects_unknown_fields():
    with pytest.raises(ValueError):
        repo.update(record.paper_id, filename="evil.pdf")

def test_fail_interrupted_only_touches_unfinished_papers():
    # one queued, one embedding, one ready, one failed -> returns 2;
    # the two unfinished become failed with the message; ready and failed are unchanged
```

- [ ] **Step 2: Run to verify it fails.** `python -m pytest tests/test_paper_repository.py -q` -> `ModuleNotFoundError: No module named 'papers'`.

- [ ] **Step 3: Implement** `papers/models.py` (SQLAlchemy 2 `Mapped` style, same portable column types as `accounts/models.py`), `papers/repository.py`, add `papers.models` to the bottom import in `rag/db_models.py` (next to `accounts.models`, same reason), and make `tests/accounts_helpers.make_session_factory` also create `Paper.__table__`. `report()` is not exercised on SQLite (see Step 6).

- [ ] **Step 4: Run to verify it passes.** `python -m pytest tests/test_paper_repository.py tests/test_accounts_models.py -q` -> all pass.

- [ ] **Step 5: Write `alembic/versions/0003_papers.py`** (revision `0003_papers`, down_revision `0002_accounts`): creates `papers` with the columns, the FK to `users` (CASCADE) and to `rag_documents` (SET NULL), `ix_papers_user_id`, and `uq_papers_user_sha256`; `downgrade` drops the table.

- [ ] **Step 6: Extend the integration tests** with
  `test_papers_table_exists_with_its_constraints` (table exists; `uq_papers_user_sha256` present; deleting the user cascades to the paper; deleting the `rag_documents` row sets `papers.document_id` to NULL) and
  `test_report_counts_chunks_figures_and_warnings` (store the fixture document with `make_fixture` + `RAGStorageService`, as `test_two_users_store_the_same_paper...` does, then `PaperRepository.report(document_id)` returns `chunk_count == 1`, `figure_count == 1`, `page_count == 1`, `title == "Test paper"`, `authors == ["Example Author"]`).
Run with `RAG_TEST_DATABASE_URL` set: `python -m pytest tests/test_postgres_integration.py -q`
Expected: fails first, then passes (8 passed).

- [ ] **Step 7: Commit**

```bash
git add papers/__init__.py papers/models.py papers/repository.py rag/db_models.py alembic/versions/0003_papers.py tests/accounts_helpers.py tests/test_paper_repository.py tests/test_postgres_integration.py
git commit -m "Add the papers table and repository" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The staged ingestor

**Files:**
- Create: `backend/papers/ingestor.py`, `backend/tests/test_paper_ingestor.py`

**Interfaces:**
- Consumes: `rag.document_ingestion.PDFIngestionService`, `rag.docling_parser.DoclingPDFParser(image_output_dir)`, `rag.chunking.StructureAwareChunker().chunk(document) -> list[CanonicalChunk]`, `rag.storage_service.RAGStorageService` (`persist_document(user_id, pdf, document, chunks) -> PersistenceResult`, `generate_missing_embeddings(document_id) -> int`), status constants from `papers.models`.
- Produces (`papers.ingestor`): `StageReporter = Callable[[str, str | None], None]` (status, detail); frozen dataclass `IngestResult(document_id: str, title: str | None, page_count: int | None, warnings: tuple[str, ...])`; `PaperIngestor(storage: RAGStorageService, parser_factory: Callable[[Path], PDFIngestionService] | None = None, chunker: StructureAwareChunker | None = None)` with
  `ingest(user_id: str, pdf_path: Path, work_dir: Path, on_stage: StageReporter) -> IngestResult` (reports `parsing`, `chunking`, `storing` in that order; the default `parser_factory(work_dir)` builds `PDFIngestionService(DoclingPDFParser(image_output_dir=work_dir / "figures"))`) and
  `embed(document_id: str, on_stage: StageReporter) -> int` (reports `embedding`).

- [ ] **Step 1: Write the failing tests** in `tests/test_paper_ingestor.py` using fakes: a parser that returns the `make_fixture` document, a recording storage double with `persist_document`/`generate_missing_embeddings`, and a recording `on_stage`:

```python
def test_ingest_reports_the_stages_in_order_and_returns_the_ids():
    result = ingestor.ingest("user-1", pdf_path, tmp_path / "work", stages.append_call)
    assert stages.names == ["parsing", "chunking", "storing"]
    assert result.document_id == storage.document_id
    assert (result.title, result.page_count) == ("Test paper", 1)

def test_the_parser_gets_a_work_directory_for_figure_images():
    # parser_factory is called once with tmp_path / "work"

def test_embed_reports_embedding_and_returns_the_count():
    assert ingestor.embed("doc-1", stages.append_call) == 3
    assert stages.names == ["embedding"] and storage.embedded == ["doc-1"]

def test_a_parser_failure_propagates_after_reporting_parsing_only():
    with pytest.raises(PDFParsingError):
        ingestor.ingest("user-1", pdf_path, tmp_path / "work", stages.append_call)   # parser fake raises PDFParsingError
    assert stages.names == ["parsing"]

def test_storage_receives_the_owner_and_the_chunks():
    # persist_document called with ("user-1", pdf_path, document, chunks) and chunks non-empty
```

- [ ] **Step 2: Run to verify it fails.** `python -m pytest tests/test_paper_ingestor.py -q` -> `ModuleNotFoundError: No module named 'papers.ingestor'`.

- [ ] **Step 3: Implement `PaperIngestor`.** It only sequences the existing pieces and reports stages; it contains no parsing or storage logic of its own.

- [ ] **Step 4: Run to verify it passes.** `python -m pytest tests/test_paper_ingestor.py -q` -> all pass.

- [ ] **Step 5: Add one real end-to-end test** marked `@pytest.mark.slow` and `@pytest.mark.integration` in the same file (skips without `RAG_TEST_DATABASE_URL`): build a one-page text PDF with a helper `make_text_pdf(path, lines)` (hand-written minimal PDF with a Helvetica text stream and correct xref offsets), migrate the test database, create a user, run the real `PaperIngestor` (real Docling, real `PostgresRAGRepository`, `ManagedAssetStore(tmp_path / "assets")`, a constant-vector embedder) and assert: the three stages ran, `chunk_count >= 1` in the database, `embed` returns the same number of chunks as have text, and the temp `work_dir` figure folder exists but is the caller's to remove.
Run: `python -m pytest tests/test_paper_ingestor.py -q -m slow` with `RAG_TEST_DATABASE_URL` set.
Expected: passes (Docling models are already cached on the owner's machine; the first run can take about a minute).

- [ ] **Step 6: Commit**

```bash
git add papers/ingestor.py tests/test_paper_ingestor.py
git commit -m "Add the staged paper ingestor" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The paper service (upload checks, de-duplication, background run, recovery)

**Files:**
- Create: `backend/papers/service.py`, `backend/tests/test_paper_service.py`
- Modify: `backend/data/.gitignore` (create: contains `uploads/`)

**Interfaces:**
- Consumes: `PaperRepository`, `PaperRecord`, `PaperReport` (Task 1); `PaperIngestor`, `IngestResult`, `StageReporter` (Task 2); status constants from `papers.models`.
- Produces (`papers.service`): exceptions `InvalidUpload(ValueError)`, `UploadTooLarge(Exception)`, `CannotRetry(Exception)` (each carries a plain-language message); constant `DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024`; `STAGE_DETAILS = {"parsing": "Reading the PDF", "chunking": "Splitting into passages", "storing": "Saving the paper", "embedding": "Indexing passages"}`;
  `PaperService(repository: PaperRepository, ingestor, upload_dir: Path, max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES, max_concurrent: int = 1, submit: Callable[[Callable[[], None]], None] | None = None)` (`submit` runs a job; the default starts a daemon thread, tests pass `lambda job: job()`), with
  `upload(user_id: str, filename: str, stream: BinaryIO) -> tuple[PaperRecord, bool]` (the bool is `True` when a new paper was created),
  `get(paper_id: str, user_id: str) -> PaperRecord | None`,
  `list(user_id: str) -> list[PaperRecord]`,
  `report(paper_id: str, user_id: str) -> PaperReport | None` (`None` for unknown/other users/not yet stored),
  `retry(paper_id: str, user_id: str) -> PaperRecord | None` (`None` for unknown/other users; raises `CannotRetry` unless the paper is `failed` and has a `document_id`),
  `fail_interrupted() -> int`,
  `wait(paper_id: str, timeout: float | None = None) -> None` (joins that paper's thread, a no-op when synchronous).

- [ ] **Step 1: Write the failing tests** in `tests/test_paper_service.py` (SQLite repository, a `FakeIngestor` whose `ingest`/`embed` record calls and can be told to raise, synchronous `submit`, `tmp_path / "uploads"`; two users). Names and assertions:

```python
PDF = b"%PDF-1.4\nbody\n%%EOF"

def test_a_valid_upload_is_read_in_the_background_and_ends_ready():
    record, created = service.upload(one, "Paper.pdf", io.BytesIO(PDF))
    final = service.get(record.paper_id, one)
    assert created is True
    assert (final.status, final.detail, final.title, final.page_count) == ("ready", None, "Fake title", 7)
    assert final.document_id == "doc-1"
    assert fake.stage_log == ["parsing", "chunking", "storing", "embedding"]

def test_the_ingestor_gets_the_owner_and_a_file_named_after_the_paper_id():
    # fake.ingest was called with user "one" and a pdf_path whose name is f"{paper_id}.pdf"
    # and whose parent is the upload directory

def test_temporary_files_are_gone_afterwards_on_success_and_on_failure():
    assert list(upload_dir.iterdir()) == []

@pytest.mark.parametrize("name, expected", [
    ("..\\..\\evil.pdf", "evil.pdf"), ("../x/y/z.pdf", "z.pdf"),
    ("résumé 论文.pdf", "résumé 论文.pdf"), ("a\x00b.pdf", "ab.pdf"),
])
def test_the_clients_filename_is_only_a_display_label(name, expected):
    record, _ = service.upload(one, name, io.BytesIO(PDF))
    assert record.filename == expected
    assert all(path.parent == upload_dir for path in fake.ingested_paths)   # nothing escaped the upload directory

def test_non_pdf_extension_empty_and_headerless_files_are_rejected_with_a_reason():
    with pytest.raises(InvalidUpload, match="PDF"): service.upload(one, "notes.txt", io.BytesIO(PDF))
    with pytest.raises(InvalidUpload, match="empty"): service.upload(one, "a.pdf", io.BytesIO(b""))
    with pytest.raises(InvalidUpload, match="not a valid PDF"): service.upload(one, "a.pdf", io.BytesIO(b"hello world"))
    assert list(upload_dir.iterdir()) == [] and repo.list_for_user(one) == []

def test_an_oversized_upload_is_refused_and_leaves_nothing_behind():
    small = build_service(max_upload_bytes=100)
    with pytest.raises(UploadTooLarge): small.upload(one, "a.pdf", io.BytesIO(PDF + b"x" * 200))
    assert list(upload_dir.iterdir()) == []

def test_the_same_pdf_twice_returns_the_existing_paper_and_reads_it_once():
    first, created_first = service.upload(one, "a.pdf", io.BytesIO(PDF))
    second, created_second = service.upload(one, "renamed.pdf", io.BytesIO(PDF))
    assert (created_first, created_second) == (True, False)
    assert second.paper_id == first.paper_id and fake.ingest_calls == 1

def test_two_users_can_each_add_the_same_pdf():
    first, created_first = service.upload(one, "a.pdf", io.BytesIO(PDF))
    second, created_second = service.upload(two, "a.pdf", io.BytesIO(PDF))
    assert (created_first, created_second) == (True, True)
    assert first.paper_id != second.paper_id and fake.ingest_calls == 2

def test_reuploading_a_paper_that_failed_while_reading_tries_again():
    fake.fail_ingest_with = RuntimeError("layout model crashed")
    failed, _ = service.upload(one, "a.pdf", io.BytesIO(PDF))
    assert service.get(failed.paper_id, one).status == "failed"
    fake.fail_ingest_with = None
    again, created = service.upload(one, "a.pdf", io.BytesIO(PDF))
    assert (created, again.paper_id) == (False, failed.paper_id)
    assert service.get(failed.paper_id, one).status == "ready"

def test_a_failure_while_reading_leaves_a_readable_one_line_reason():
    fake.fail_ingest_with = RuntimeError("Could not parse 'a.pdf':\n  line two")
    record, _ = service.upload(one, "a.pdf", io.BytesIO(PDF))
    final = service.get(record.paper_id, one)
    assert final.status == "failed" and "\n" not in final.detail and "Could not parse" in final.detail
    assert final.document_id is None

def test_an_embedding_failure_keeps_the_stored_text_and_retry_finishes_the_job():
    fake.fail_embed_with = RuntimeError("getaddrinfo failed")
    record, _ = service.upload(one, "a.pdf", io.BytesIO(PDF))
    failed = service.get(record.paper_id, one)
    assert failed.status == "failed" and failed.document_id == "doc-1"
    assert "saved" in failed.detail and "getaddrinfo failed" in failed.detail
    fake.fail_embed_with = None
    assert service.retry(record.paper_id, one).status in ("embedding", "ready")
    assert service.get(record.paper_id, one).status == "ready"
    assert fake.ingest_calls == 1                      # not re-read

def test_retry_is_refused_for_ready_papers_and_for_papers_that_never_got_stored():
    with pytest.raises(CannotRetry): service.retry(ready_paper_id, one)
    with pytest.raises(CannotRetry): service.retry(never_stored_failed_paper_id, one)

def test_papers_of_other_users_are_invisible():
    assert service.get(record.paper_id, two) is None
    assert service.retry(record.paper_id, two) is None
    assert service.report(record.paper_id, two) is None
    assert service.list(two) == []

def test_unfinished_papers_are_failed_after_a_restart():
    # create rows directly in the repository with statuses queued, parsing, ready;
    # service.fail_interrupted() == 2; the two become failed with "restarted" in the detail

def test_only_one_paper_is_read_at_a_time_and_the_rest_wait_as_queued():
    # real thread submit (the default); fake.ingest blocks on a threading.Event;
    # upload three different PDFs; while blocked: one paper is "parsing", two are "queued";
    # after setting the event and wait(): all three are "ready"
```

- [ ] **Step 2: Run to verify it fails.** `python -m pytest tests/test_paper_service.py -q` -> `ModuleNotFoundError: No module named 'papers.service'`.

- [ ] **Step 3: Implement `PaperService`.** Decisions the tests do not pin:
  - The display name is the part after the last `/` or `\`, control characters removed, at most 255 characters, `"paper.pdf"` if nothing is left; it must end in `.pdf` (any case).
  - The upload is streamed in 1 MiB chunks into `upload_dir/<random>.part` while counting bytes and computing SHA-256; over the limit aborts immediately and deletes the part file; the first 1024 bytes must contain `%PDF-`. A new paper's file is then renamed to `<paper_id>.pdf`.
  - A repository `IntegrityError` on create (a race) resolves to the existing paper (`created=False`).
  - `_process` takes a `threading.BoundedSemaphore(max_concurrent)` before the first status change (so waiting papers stay `queued`), maps stage names through `STAGE_DETAILS` for `detail`, stores `title`, `page_count`, `document_id` right after `ingest`, and in `finally` deletes the uploaded PDF and the per-paper work directory. Failure text is the exception message collapsed to one line and cut at 300 characters; an embedding failure reads `"The text was saved but indexing failed: <reason>. Press Retry."`.

- [ ] **Step 4: Run to verify it passes.** `python -m pytest tests/test_paper_service.py -q` -> all pass.

- [ ] **Step 5: Add `backend/data/.gitignore`** with the single line `uploads/`, then run `git status --short backend/data` and confirm nothing under `data/uploads` would be tracked.

- [ ] **Step 6: Commit**

```bash
git add papers/service.py data/.gitignore tests/test_paper_service.py
git commit -m "Add the paper service: validated uploads, de-duplication, background reading" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Paper endpoints and server wiring

**Files:**
- Create: `backend/papers/router.py`, `backend/tests/test_papers_router.py`
- Modify: `backend/main.py`, `backend/requirements.txt`, `backend/tests/test_main_requires_login.py`, `backend/rag/PHASE3_STORAGE_README.md`

**Interfaces:**
- Consumes: `PaperService` (Task 3), `create_current_user_dependency`, `UserInfo` (accounts).
- Produces (`papers.router`): response models `PaperOut(paper_id, filename, size_bytes, status, detail, title, page_count, can_retry: bool, created_at, updated_at)`, `PaperReportOut(title, authors: list[str], page_count, chunk_count, figure_count, warnings: list[str])`, `PaperDetailOut(PaperOut + report: PaperReportOut | None)`; `create_papers_router(service: PaperService, current_user: Callable[[Request], UserInfo]) -> APIRouter` with
  `POST /papers` (multipart field `file`; **202** with the new paper, **200** when it already existed; 400 `InvalidUpload`; 413 `UploadTooLarge`, also when the `Content-Length` header already exceeds the limit),
  `GET /papers` (the user's papers, newest first),
  `GET /papers/{paper_id}` (404 when unknown or someone else's; `report` filled once the paper has a `document_id`),
  `POST /papers/{paper_id}/retry` (202; 404; 409 with the `CannotRetry` message).
  `can_retry` is true exactly when `status == "failed"` and a `document_id` exists.

- [ ] **Step 1: Write the failing tests** in `tests/test_papers_router.py` (a small `FastAPI` app with the router, the stub `X-User`-header login dependency from `tests/test_job_service.py`, a real `PaperService` on SQLite with the fake ingestor and synchronous `submit`, and `repository.report` replaced by a lambda returning a fixed `PaperReport`):

```python
def upload(client, name="paper.pdf", data=PDF, user="u1"):
    return client.post("/papers", files={"file": (name, data, "application/pdf")}, headers={"x-user": user})

def test_everything_requires_login():
    for method, path in [("GET", "/papers"), ("POST", "/papers"), ("GET", "/papers/x"), ("POST", "/papers/x/retry")]:
        assert client.request(method, path).status_code == 401

def test_upload_returns_202_then_the_paper_appears_in_the_list_as_ready():
    response = upload(client)
    assert response.status_code == 202 and response.json()["filename"] == "paper.pdf"
    listed = client.get("/papers", headers=u1).json()
    assert [p["status"] for p in listed] == ["ready"] and listed[0]["can_retry"] is False

def test_uploading_the_same_file_again_returns_200_and_the_same_paper():
    first = upload(client)
    second = upload(client)
    assert (first.status_code, second.status_code) == (202, 200)
    assert first.json()["paper_id"] == second.json()["paper_id"]
def test_bad_uploads_get_a_plain_reason():
    assert "PDF" in upload(client, name="notes.txt").json()["detail"]
    assert "empty" in upload(client, data=b"").json()["detail"]
    bad = upload(client, name="a.pdf", data=b"hello")
    assert bad.status_code == 400 and "not a valid PDF" in bad.json()["detail"]
    # notes.txt -> 400 detail mentions PDF; b"" -> 400 "empty"; b"hello" named a.pdf -> 400 "not a valid PDF"
def test_a_declared_huge_body_is_refused_before_reading_it():
    # POST with header Content-Length: str(limit * 10) (service built with a tiny limit) -> 413
def test_detail_includes_the_reading_report_for_a_stored_paper():
    body = client.get(f"/papers/{paper_id}", headers=u1).json()
    assert body["report"] == {"title": "Fake title", "authors": ["A. Author"], "page_count": 7,
                              "chunk_count": 12, "figure_count": 3, "warnings": ["Table 2 could not be read"]}
def test_another_users_paper_is_404_on_detail_and_retry_and_missing_from_their_list():
    paper_id = upload(client, user="u1").json()["paper_id"]
    other = {"x-user": "u2"}
    assert client.get(f"/papers/{paper_id}", headers=other).status_code == 404
    assert client.post(f"/papers/{paper_id}/retry", headers=other).status_code == 404
    assert client.get("/papers", headers=other).json() == []
def test_retry_conflicts_are_409_with_the_reason():
    # retry on a ready paper -> 409, detail "Only failed papers can be retried"
def test_a_failed_embedding_shows_can_retry_and_retry_returns_202():
    fake.fail_embed_with = RuntimeError("getaddrinfo failed")
    paper_id = upload(client).json()["paper_id"]
    failed = client.get(f"/papers/{paper_id}", headers=u1).json()
    assert (failed["status"], failed["can_retry"]) == ("failed", True)
    fake.fail_embed_with = None
    assert client.post(f"/papers/{paper_id}/retry", headers=u1).status_code == 202
    assert client.get(f"/papers/{paper_id}", headers=u1).json()["status"] == "ready"
```

- [ ] **Step 2: Run to verify it fails.** `python -m pytest tests/test_papers_router.py -q` -> `ModuleNotFoundError: No module named 'papers.router'`.

- [ ] **Step 3: Implement `papers/router.py`.** The upload handler takes `file: UploadFile = File(...)` and the login dependency, passes `file.filename` and `file.file` to `service.upload`, and sets `response.status_code` to 202 or 200. Add `python-multipart>=0.0.9` to `requirements.txt`.

- [ ] **Step 4: Run to verify it passes.** `python -m pytest tests/test_papers_router.py -q` -> all pass.

- [ ] **Step 5: Extend `tests/test_main_requires_login.py`:** add `("GET", "/papers")`, `("POST", "/papers")`, `("GET", "/papers/abc")` and `("POST", "/papers/abc/retry")` to `PROTECTED` (401 without a cookie), and one test that `POST /papers` with `Origin: http://localhost:3000` is 403. Run it: expected to fail first (404 for the missing routes), then pass.

- [ ] **Step 6: Wire `main.py`.** After the account and video services exist, build
  `paper_repository = PaperRepository(session_factory)`,
  `rag_storage = RAGStorageService(PostgresRAGRepository(session_factory))`,
  `paper_service = PaperService(paper_repository, PaperIngestor(rag_storage), upload_dir=Path(__file__).parent / "data" / "uploads", max_upload_bytes=int(os.getenv("MAX_PAPER_UPLOAD_MB", "50")) * 1024 * 1024, max_concurrent=int(os.getenv("MAX_CONCURRENT_INGESTIONS", "1")))`
  and `app.include_router(create_papers_router(paper_service, current_user))`. Register `@app.on_event("startup")` that calls `paper_service.fail_interrupted()` (it must not run at import time: importing `main` in the tests must not touch a database). Add a short "Uploading papers" section to `PHASE3_STORAGE_README.md` (limits, statuses, the retry rule).

- [ ] **Step 7: Run the whole suite.** `python -m pytest -q` -> everything passes.

- [ ] **Step 8: Commit**

```bash
git add papers/router.py main.py requirements.txt rag/PHASE3_STORAGE_README.md tests/test_papers_router.py tests/test_main_requires_login.py
git commit -m "Add the paper upload, list, detail and retry endpoints" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Nav bar and page switching (no change to the studio)

**Files:**
- Create: `frontend/src/useHashRoute.ts`, `frontend/src/Layout.tsx`, `frontend/src/StudioPage.tsx`, `frontend/src/PapersPage.tsx` (a stub for now), `frontend/src/PaperDetailPage.tsx` (a stub for now)
- Modify: `frontend/src/App.tsx`, `frontend/src/index.css`

**Interfaces:**
- Produces: `type Route = { page: "studio" } | { page: "papers" } | { page: "paper"; paperId: string }`; `parseHash(hash: string): Route` (`""`, `"#"`, `"#/"` and any unknown hash give studio; `#/papers` gives papers; `#/papers/<id>` gives paper with that id, the id URL-decoded); `useHashRoute(): Route` (re-renders on `hashchange`); `Layout({ user, onLogout, active, children })` with `active: "studio" | "papers"`; `StudioPage()` (the current studio body, unchanged); `PapersPage()` and `PaperDetailPage({ paperId })` (stubs that render only a heading and, on the detail page, a link back to the library).
- `App({ user, onLogout })` keeps its props and renders `Layout` around the page chosen by `useHashRoute()`.

- [ ] **Step 1: Implement.** Move the whole current body of `App` (state, effects, `generateVideo`, and the `<section className="workspace">…</section>`) into `StudioPage` exactly as it is. `Layout` renders what `App` rendered around it: `<main className="app-shell">`, the top bar (brand, **two nav links `Studio` (`href="#/"`) and `Paper videos` (`href="#/papers"`), the active one marked with a class and `aria-current="page"`**, the status text, the account email and Log out), `{children}`, and the footer. Add nav styles to `index.css` using the existing colours (accent `#b5d85d`, muted `#899080`).

- [ ] **Step 2: Type-check, build and lint.** In `frontend/`: `bun run build` then `bun run lint`.
Expected: no errors; the one pre-existing lint warning may remain.

- [ ] **Step 3: Commit**

```bash
git add src/useHashRoute.ts src/Layout.tsx src/StudioPage.tsx src/PapersPage.tsx src/PaperDetailPage.tsx src/App.tsx src/index.css
git commit -m "Add the nav bar and a Paper videos page route" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The paper library and paper pages

**Files:**
- Modify: `frontend/src/PapersPage.tsx`, `frontend/src/PaperDetailPage.tsx`, `frontend/src/index.css`
- Create: `frontend/src/papers.ts` (types and labels)

**Interfaces:**
- Consumes: `POST /papers`, `GET /papers`, `GET /papers/{id}`, `POST /papers/{id}/retry` (Task 4), `apiFetch`, `go`/hash routes (Task 5).
- Produces (`papers.ts`): `type Paper = { paper_id; filename; size_bytes; status; detail: string | null; title: string | null; page_count: number | null; can_retry: boolean; created_at; updated_at }`, `type PaperReport = { title; authors; page_count; chunk_count; figure_count; warnings }`, `STATUS_LABELS: Record<string, string>` (`queued` "Waiting", `parsing` "Reading the PDF", `chunking` "Splitting into passages", `storing` "Saving", `embedding` "Indexing", `ready` "Ready", `failed` "Failed"), `isInProgress(status: string): boolean`, `MAX_UPLOAD_MB = 50`.

- [ ] **Step 1: Implement `PapersPage`.**
  - An upload box (a labelled file input accepting `.pdf` plus drag-and-drop). Before sending it rejects non-PDF names and files over 50 MB with a plain message; otherwise `POST /papers` as `FormData` (no `Content-Type` header, the browser adds the boundary). Server errors show the response's `detail` text. A 200 answer (already added) shows "You already added this paper."
  - The library list newest first: title (or filename while unread), size, a status chip with the label from `STATUS_LABELS`, the `detail` line, and for failed rows the reason plus a **Retry** button when `can_retry`. Ready rows link to `#/papers/<id>`. An empty library shows "Add a research paper to get started."
  - Loads on mount and after each upload; while any paper is in progress it polls `GET /papers` every 2 seconds and stops when none is (the effect cleans up on unmount; a failed poll retries up to 5 times, then shows "Lost connection to the server.").

- [ ] **Step 2: Implement `PaperDetailPage`.** Loads `GET /papers/{id}`; a 404 shows "Paper not found" with a link to `#/papers`. Shows the title (or filename), authors, page count and status (polling while in progress, with the Retry button for failed ones), a **Reading report** block (page count, number of passages, number of figures, and the parser's warnings as a list, or "The parser reported no problems." when empty; while the paper is not stored yet, "The report appears once the paper has been read."), and a **Videos from this paper** block with the empty state "No videos yet. Making videos from a paper is the next step of this feature."

- [ ] **Step 3: Style** the upload box, status chips (a colour per state: grey waiting, accent for working states, green ready, red failed), library rows and report using the existing look.

- [ ] **Step 4: Type-check, build and lint.** In `frontend/`: `bun run build` then `bun run lint`.
Expected: no errors (the one pre-existing lint warning may remain).

- [ ] **Step 5: Commit**

```bash
git add src/papers.ts src/PapersPage.tsx src/PaperDetailPage.tsx src/index.css
git commit -m "Add the paper library and paper detail pages" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Final verification (suite, real upload, restart recovery)

**Files:** none modified (scratch scripts go in `backend/scratch_*.py` and are not committed).

- [ ] **Step 1: Full suite and integration tests.** In `backend/`, with `RAG_TEST_DATABASE_URL` set: `python -m pytest -q -m "slow or not slow"`.
Expected: everything passes; report the count.

- [ ] **Step 2: Migrate the development database.** `python -m alembic -c alembic.ini upgrade head` then `python -m alembic -c alembic.ini current`.
Expected: `0003_papers (head)`.

- [ ] **Step 3: Real upload through the live server.** Start `python -m uvicorn main:app --port 8000` from `backend/`. With throwaway accounts `verify-alice@example.test` and `verify-bob@example.test` (cookie jars):
  1. Alice uploads `backend/IJRTI2304061.pdf` to `POST /papers`: 202; poll `GET /papers` until `ready` (real Docling and real Gemini embeddings, a few minutes); note the statuses seen.
  2. `GET /papers/<id>`: the report has a page count, at least one passage, and the parser's warnings.
  3. Alice uploads the same file again: 200 and the same `paper_id`. Bob uploads it: 202 and a different `paper_id`; Bob's list holds only his; Bob's `GET /papers/<alice's id>` is 404.
  4. Bad files as Alice: a 0-byte `a.pdf` gives 400; a text file named `a.pdf` gives 400; a file starting with `%PDF-` followed by 60 MB of zeros gives 413 and leaves nothing in `backend/data/uploads`.
  5. A request without a cookie to `GET /papers` gives 401; `POST /papers` with `Origin: http://localhost:3000` gives 403.
Expected: each line as stated.

- [ ] **Step 4: Restart recovery.** Upload a different PDF as Alice (copy the sample and append one byte so its hash differs), and while its status is `parsing` stop the server process. Start it again; `GET /papers` shows that paper `failed` with a "restarted" reason and not stuck in `parsing`.

- [ ] **Step 5: Clean up the test data.** Delete the `verify-*@example.test` users (their papers are removed by cascade; also delete their `rag_documents` rows if any remain), remove leftovers in `backend/data/uploads`, stop the server, delete scratch scripts.

- [ ] **Step 6: Browser check (the owner).** Start `bun run dev` in `frontend/`, sign in and confirm: the nav bar shows **Studio** and **Paper videos**; clicking Paper videos opens the library page and the URL ends in `#/papers`; choosing a PDF uploads it and the row moves through the statuses to Ready without a page refresh; opening a ready paper shows its reading report; `#/papers/not-a-real-id` shows "Paper not found"; a refresh keeps you on the same page; a second account sees none of the first account's papers. Report anything that differs; do not claim success on checks that were not performed.

- [ ] **Step 7: Report.** State per step what ran and the result, including anything not verified.

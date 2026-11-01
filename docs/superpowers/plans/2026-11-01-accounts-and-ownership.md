# Accounts and Per-User Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add email-and-password accounts, and make every paper, video and job belong to exactly one user, with the existing studio and media endpoints visible only to their owner.

**Architecture:** A new `accounts` package (models, password hashing, server-side sessions, login rate limiter, `AccountService`, FastAPI router) sits on the same PostgreSQL database and Alembic chain as the existing RAG tables. Sessions are random tokens in an HttpOnly cookie (needed because `<video src>` cannot send headers); only a hash of each token is stored. The RAG storage layer drops pgvector, stores embeddings as plain arrays, and scopes every read and write by `user_id`. Studio endpoints, `/videos` and `/media` require a logged-in user and answer 404 for anything owned by someone else.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, PostgreSQL (psycopg 3), `argon2-cffi`, React 19 + Vite + TypeScript, pytest (SQLite for fast account tests, a disposable PostgreSQL database for integration tests).

**Spec:** `docs/superpowers/specs/2026-11-01-paper-videos-design.md` (sections 7, 8, 9, 10 and the "vector storage" call in section 5). This is project 1 of 5 in section 10; later projects (paper library, grounded videos, accuracy checking) get their own plans.

## Global Constraints

- Sign-in is **email and password**, managed by this app. No "forgot password", no email verification, no Google sign-in (spec section 8).
- Passwords are stored **only as salted hashes**; sessions use a **secure random token**; **login attempts are rate-limited** (spec section 7).
- Every paper, video and job carries a **user id from the start**; users can read **only their own** (spec section 7). Ordinary topic videos belong to the user too. The existing studio page now **requires login**.
- Built in the existing Python (FastAPI) backend. PostgreSQL stays; **pgvector is dropped**: embeddings are stored as plain number arrays and compared in Python for the selected paper (spec section 5, my call). Accounts, papers, videos and jobs share the same database and Alembic chain, so the app requires PostgreSQL to be running.
- Runs on the owner's machine first (no deployment work). Sharing between users is out of scope.
- Backend tests run from `backend/`. Default `python -m pytest -q` excludes `slow`; the full run is `python -m pytest -q -m "slow or not slow"`. Fakes are imported with `from fakes import FakeLLM`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Stage files by name only. The working tree has unrelated `backend/output/**` deletions, an untracked `backend/IJRTI2304061.pdf` + `IJRTI2304061_assets/`, and an untracked `backend/rendering/__init__.py`: never stage these.
- Frontend checks: `bun run build` and `bun run lint` in `frontend/` pass (lint already has one pre-existing `set-state-in-effect` warning). The frontend has no unit-test runner.

## Review Focus

1. **Cross-user access:** user B asking for user A's job id, A's media path (`/media/<run>/lesson_demo.mp4`) or A's videos gets 404/empty, never the data and never a 403 that confirms it exists. Tested in Task 5.
2. **Guessing passwords:** after 5 failed logins for the same email from the same address the next attempt gets 429 with `Retry-After`, even with the right password; an unknown email and a wrong password produce the identical 401 body. Tested in Tasks 3 and 4.
3. **Bad cookies:** an expired, revoked (logged-out), unknown or empty session cookie gives 401, never 500, and logout invalidates the session on the server, not just in the browser. Tested in Tasks 3 and 4.
4. **Same person, different spelling:** signing up as `Alice@Example.com ` after `alice@example.com` is rejected as a duplicate (409). Tested in Task 3.
5. **Same paper, two users:** both can store the identical PDF, each sees only their own copy, and similarity search never returns another user's passages. Tested in Task 6 (including against real PostgreSQL).

---

## File Structure

**Create**
- `backend/accounts/__init__.py`, `models.py` (User, AuthSession, Video), `passwords.py`, `rate_limit.py`, `service.py` (AccountService + errors + `UserInfo`), `router.py` (auth endpoints + `create_current_user_dependency`), `videos.py` (VideoRepository).
- `backend/rag/similarity.py`: pure cosine ranking used by the repository.
- `backend/alembic/versions/0002_accounts.py`.
- Tests: `tests/accounts_helpers.py`, `tests/test_similarity.py`, `tests/test_accounts_models.py`, `tests/test_passwords.py`, `tests/test_rate_limit.py`, `tests/test_account_service.py`, `tests/test_auth_router.py`, `tests/test_video_repository.py`, `tests/test_main_requires_login.py`, `tests/test_postgres_integration.py`.
- Frontend: `frontend/src/api.ts`, `AuthGate.tsx`, `LoginPage.tsx`.

**Modify**
- `backend/alembic/versions/0001_rag_storage.py` (no pgvector), `backend/rag/db_models.py`, `rag/database.py`, `rag/pg_repository.py`, `rag/storage_service.py`, `rag/storage_schema.py` (if needed), `rag/PHASE3_STORAGE_README.md`, `scripts/check_rag_db.py`, `scripts/ingest_research_pdf.py`.
- `backend/requirements.txt` (DB and auth dependencies move here; `requirements-rag-storage.txt` is deleted), `backend/pytest.ini` (new `integration` marker).
- `backend/services/job_service.py`, `services/jobs_router.py`, `services/media_response.py`, `services/video_library.py`, `backend/main.py`.
- `backend/tests/test_rag_storage.py`, `tests/test_job_service.py`, `tests/test_media_response.py`, `tests/test_video_library.py`.
- `frontend/src/main.tsx`, `App.tsx`, `index.css`.

## Calls made while planning (not in the spec)

- **Jobs stay in memory.** The spec says every job "row" carries a user id; jobs are an in-memory dict today and the spec's non-goals exclude persistence, so each in-memory job carries `user_id` and a finished job's video is recorded in a `videos` table. A persisted jobs table is deferred.
- **All `/lesson/*` endpoints require login,** not only the ones the frontend uses, since the debugging endpoints spend Gemini quota. `/` and `/auth/*` are public.
- **Rate-limit key is (client IP, email)** held in memory, 5 failures per 15 minutes. It resets on server restart.
- **Existing output folders have no owner row,** so they are not listed or served. The owner already cleared `backend/output`.
- **Migration 0001 is rewritten in place** because it was never applied anywhere (pgvector was missing); Task 1 verifies this with `alembic current` before editing it.

---

### Task 1: Database foundation without pgvector

**Files:**
- Create: `backend/rag/similarity.py`, `backend/tests/test_similarity.py`, `backend/tests/test_postgres_integration.py`
- Modify: `backend/alembic/versions/0001_rag_storage.py`, `backend/rag/db_models.py`, `backend/rag/database.py`, `backend/rag/pg_repository.py`, `backend/scripts/check_rag_db.py`, `backend/rag/PHASE3_STORAGE_README.md`, `backend/requirements.txt`, `backend/pytest.ini`, `backend/tests/test_rag_storage.py`; delete `backend/requirements-rag-storage.txt`.

**Interfaces:**
- Produces (`rag.similarity`): `cosine_distance(a: Sequence[float], b: Sequence[float]) -> float` (0 identical direction, 1 orthogonal, 2 opposite; raises `ValueError` on length mismatch or a zero vector); `rank_by_cosine(query: Sequence[float], candidates: Sequence[tuple[str, Sequence[float]]], limit: int) -> list[tuple[str, float]]` returning `(candidate_id, distance)` closest first.
- `RAGChunkEmbedding.embedding` becomes a PostgreSQL array of `REAL`; `PostgresRAGRepository.search_similar(query_vector, model_name, limit=5)` keeps its current signature in this task (scoping arrives in Task 6) but ranks in Python via `rank_by_cosine`.
- `check_database(engine) -> dict[str, str | None]` returns `{"database": name}` and no longer requires any extension.
- Test marker `integration` (in `pytest.ini`); integration tests skip unless `RAG_TEST_DATABASE_URL` is set to a **disposable** PostgreSQL database.

- [ ] **Step 1: Confirm migration 0001 was never applied**

Run from `backend/`: `python -m alembic -c alembic.ini current`
Expected: prints no revision (or fails to connect). If it prints `0001_rag_storage (head)`, stop and ask the owner: the migration cannot be rewritten in place on a database that already ran it.

- [ ] **Step 2: Write the failing similarity tests** in `tests/test_similarity.py`:

```python
import pytest

from rag.similarity import cosine_distance, rank_by_cosine


def test_identical_direction_is_zero_and_scale_does_not_matter():
    assert cosine_distance([1.0, 2.0], [2.0, 4.0]) == pytest.approx(0.0)


def test_orthogonal_is_one_and_opposite_is_two():
    assert cosine_distance([1.0, 0.0], [0.0, 3.0]) == pytest.approx(1.0)
    assert cosine_distance([1.0, 0.0], [-2.0, 0.0]) == pytest.approx(2.0)


@pytest.mark.parametrize("a, b", [([1.0, 2.0], [1.0]), ([0.0, 0.0], [1.0, 1.0]), ([1.0, 1.0], [0.0, 0.0])])
def test_mismatched_or_zero_vectors_are_rejected(a, b):
    with pytest.raises(ValueError):
        cosine_distance(a, b)


def test_rank_orders_closest_first_and_applies_the_limit():
    candidates = [("far", [0.0, 1.0]), ("near", [1.0, 0.1]), ("mid", [1.0, 1.0])]

    ranked = rank_by_cosine([1.0, 0.0], candidates, limit=2)

    assert [item_id for item_id, _ in ranked] == ["near", "mid"]
    assert ranked[0][1] < ranked[1][1]


def test_rank_of_nothing_is_empty():
    assert rank_by_cosine([1.0], [], limit=5) == []
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_similarity.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'rag.similarity'`.

- [ ] **Step 4: Implement `rag/similarity.py`** with the two functions above (pure Python or `math`; no numpy dependency needed for a few hundred vectors).

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_similarity.py -q`
Expected: 5 passed.

- [ ] **Step 6: Add the `integration` marker and write the failing integration test**

In `pytest.ini` add `integration: needs a disposable PostgreSQL database named by RAG_TEST_DATABASE_URL` under `markers`.

Create `tests/test_postgres_integration.py` with a module-level skip (`pytestmark = [pytest.mark.integration, pytest.mark.skipif(not os.getenv("RAG_TEST_DATABASE_URL"), reason=...)]`) and a fixture `migrated_engine` that: sets `RAG_DATABASE_URL` to `RAG_TEST_DATABASE_URL` with `monkeypatch.setenv`, `chdir`s to `backend/`, runs `alembic.command.downgrade(cfg, "base")` then `upgrade(cfg, "head")` using `alembic.config.Config("alembic.ini")`, yields `rag.database.build_engine()`, and disposes it. Tests:

```python
def test_embeddings_are_stored_as_a_plain_real_array(migrated_engine):
    with migrated_engine.connect() as connection:
        data_type = connection.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'rag_chunk_embeddings' AND column_name = 'embedding'")).scalar_one()
        extensions = connection.execute(text("SELECT extname FROM pg_extension")).scalars().all()
    assert data_type == "ARRAY"
    assert "vector" not in extensions


def test_check_database_passes_without_pgvector(migrated_engine):
    assert check_database(migrated_engine)["database"]
```

- [ ] **Step 7: Run to verify it fails (with a test database)**

First create the disposable database using the same server and credentials as `RAG_DATABASE_URL` but the name `edugen_rag_test` (for example with `psql`: `CREATE DATABASE edugen_rag_test;`), then run with `RAG_TEST_DATABASE_URL=<that url>`: `python -m pytest tests/test_postgres_integration.py -q`
Expected: failure at `upgrade` because the migration still needs the `vector` extension. Without the variable the tests skip (verify that too).

- [ ] **Step 8: Remove pgvector everywhere**
  - `0001_rag_storage.py`: drop the `CREATE EXTENSION`, the `pgvector` import and the HNSW index; `rag_chunk_embeddings.embedding` becomes `postgresql.ARRAY(sa.REAL())`, not null; update the docstring and the downgrade accordingly.
  - `rag/db_models.py`: same column type (`mapped_column(ARRAY(REAL), nullable=False)`), delete the `VECTOR` import and the HNSW `Index`.
  - `rag/database.py`: `check_database` returns `{"database": name}` after a connectivity query; delete the extension check.
  - `rag/pg_repository.py`: `search_similar` loads `(chunk, document, embedding)` rows for the model name and dimensions, ranks with `rank_by_cosine`, and builds the same `SimilarityHit` objects.
  - `scripts/check_rag_db.py`: print only the database name.
  - `requirements.txt`: add `SQLAlchemy>=2.0,<3.0`, `alembic>=1.14,<2.0`, `psycopg[binary]>=3.2,<4.0`, `argon2-cffi>=23.1` (drop the separate `pgvector`); delete `requirements-rag-storage.txt`.
  - `PHASE3_STORAGE_README.md`: replace the pgvector instructions with the plain-array approach and the `RAG_TEST_DATABASE_URL` note.
  - `tests/test_rag_storage.py`: replace `test_vector_model_schema_is_available_when_pgvector_is_installed` with a test asserting `RAGChunkEmbedding.__table__.c.embedding.type` is a PostgreSQL `ARRAY` and the six table names exist.

- [ ] **Step 9: Run to verify it passes**

Run: `python -m pytest -q` then, with `RAG_TEST_DATABASE_URL` set, `python -m pytest tests/test_postgres_integration.py -q`
Expected: the default suite passes; the integration tests pass (2 passed).

- [ ] **Step 10: Commit**

```bash
git add rag/similarity.py rag/db_models.py rag/database.py rag/pg_repository.py rag/PHASE3_STORAGE_README.md alembic/versions/0001_rag_storage.py scripts/check_rag_db.py requirements.txt pytest.ini tests/test_similarity.py tests/test_postgres_integration.py tests/test_rag_storage.py
git rm requirements-rag-storage.txt
git commit -m "Store embeddings as plain arrays and drop the pgvector requirement" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Accounts schema and migration

**Files:**
- Create: `backend/accounts/__init__.py`, `backend/accounts/models.py`, `backend/alembic/versions/0002_accounts.py`, `backend/tests/accounts_helpers.py`, `backend/tests/test_accounts_models.py`
- Modify: `backend/rag/db_models.py` (add `user_id` to `RAGDocument`), `backend/tests/test_postgres_integration.py`

**Interfaces:**
- Consumes: `rag.db_models.Base` (shared metadata, so one Alembic chain).
- Produces (`accounts.models`), all ids `String(36)` UUID strings, all timestamps `DateTime(timezone=True)`, only portable column types (so SQLite works in unit tests):
  - `User`: `user_id` (pk), `email` (String(254), unique, stored lowercase), `password_hash` (Text), `created_at` (server default now).
  - `AuthSession`: `session_id` (pk), `user_id` (FK users, ON DELETE CASCADE, indexed), `token_hash` (String(64), unique), `created_at`, `expires_at`, `revoked_at` (nullable).
  - `Video`: `video_id` (pk), `user_id` (FK users CASCADE, indexed), `run_dir` (String(255), unique: folder name under the output root), `title` (Text), `kind` (String(16), default `"topic"`), `created_at`.
  - `RAGDocument.user_id` (FK users, ON DELETE CASCADE, not null) replacing the single-column unique on `source_sha256` with a unique constraint on `(user_id, source_sha256)`.
- Produces (`tests/accounts_helpers.py`): `make_session_factory() -> sessionmaker` returning an in-memory SQLite factory (`StaticPool`, `check_same_thread=False`) with only the three account tables created.

- [ ] **Step 1: Write the failing tests** in `tests/test_accounts_models.py` (use `make_session_factory`; write that helper first as part of this step):

```python
def test_email_must_be_unique():
    factory = make_session_factory()
    with factory.begin() as session:
        session.add(User(user_id=str(uuid4()), email="a@x.com", password_hash="h"))
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            session.add(User(user_id=str(uuid4()), email="a@x.com", password_hash="h"))


def test_session_and_video_rows_reference_their_user():
    factory = make_session_factory()
    user_id = str(uuid4())
    with factory.begin() as session:
        session.add(User(user_id=user_id, email="a@x.com", password_hash="h"))
        session.add(AuthSession(session_id=str(uuid4()), user_id=user_id, token_hash="t" * 64,
                                expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
        session.add(Video(video_id=str(uuid4()), user_id=user_id, run_dir="binary-search-ab12", title="Binary Search"))
    with factory() as session:
        video = session.scalars(select(Video)).one()
        assert (video.kind, video.user_id) == ("topic", user_id)


def test_run_dir_is_unique_per_video():
    # inserting two Video rows with the same run_dir raises IntegrityError
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_accounts_models.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'accounts'`.

- [ ] **Step 3: Implement** `accounts/models.py` (SQLAlchemy 2 `Mapped` style like `rag/db_models.py`) and add `user_id` + the new unique constraint to `RAGDocument`.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_accounts_models.py -q`
Expected: 3 passed.

- [ ] **Step 5: Write `alembic/versions/0002_accounts.py`** (revision `0002_accounts`, down_revision `0001_rag_storage`): creates `users`, `auth_sessions`, `videos` with the indexes above; adds `rag_documents.user_id` (not null, FK), drops `uq_rag_documents_source_sha256` and creates `uq_rag_documents_user_source_sha256` on `(user_id, source_sha256)`. If `rag_documents` already has rows, `upgrade` raises `RuntimeError("rag_documents is not empty; clear or re-ingest it before enabling accounts")` instead of guessing an owner. `downgrade` reverses every change.

- [ ] **Step 6: Extend the integration test** with `test_accounts_tables_exist_and_documents_are_owned` (asserts the three tables exist, `rag_documents.user_id` is `NOT NULL`, the new unique constraint exists and the old one is gone) and `test_upgrade_refuses_to_guess_an_owner_for_existing_documents` (migrate to `0001_rag_storage`, insert one `rag_documents` row with SQL, expect `upgrade head` to raise `RuntimeError`/`CommandError`, then clean up).
Run with `RAG_TEST_DATABASE_URL` set: `python -m pytest tests/test_postgres_integration.py -q`
Expected: fails first (before Step 5 is applied), then 4 passed.

- [ ] **Step 7: Commit**

```bash
git add accounts/__init__.py accounts/models.py rag/db_models.py alembic/versions/0002_accounts.py tests/accounts_helpers.py tests/test_accounts_models.py tests/test_postgres_integration.py
git commit -m "Add user, session and video tables and make papers owned by a user" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Password hashing, rate limiter and account service

**Files:**
- Create: `backend/accounts/passwords.py`, `backend/accounts/rate_limit.py`, `backend/accounts/service.py`, `backend/tests/test_passwords.py`, `backend/tests/test_rate_limit.py`, `backend/tests/test_account_service.py`

**Interfaces:**
- Consumes: Task 2 models and `make_session_factory`.
- Produces:
  - `accounts.passwords`: `hash_password(password: str) -> str`, `verify_password(password: str, password_hash: str) -> bool` (never raises; garbage hashes give `False`). Argon2id via `argon2-cffi` defaults.
  - `accounts.rate_limit.LoginRateLimiter(max_failures: int = 5, window_seconds: int = 900, clock: Callable[[], float] = time.monotonic)` with `retry_after(key: str) -> int | None` (seconds until allowed, `None` if allowed), `record_failure(key: str) -> None`, `reset(key: str) -> None`. Thread-safe.
  - `accounts.service`: frozen dataclass `UserInfo(user_id: str, email: str)`; exceptions `InvalidSignup(ValueError)`, `EmailTaken`, `InvalidLogin`, `TooManyAttempts(retry_after: int)`; `SESSION_TTL = timedelta(days=14)`;
    `AccountService(session_factory, rate_limiter: LoginRateLimiter | None = None, now: Callable[[], datetime] = utc_now)` with
    `signup(email: str, password: str) -> tuple[UserInfo, str]`, `login(email: str, password: str, client_ip: str) -> tuple[UserInfo, str]`, `user_for_token(token: str) -> UserInfo | None`, `logout(token: str) -> None`, `find_user(email: str) -> UserInfo | None`. The returned `str` is the raw session token; only its SHA-256 hex digest is stored.

- [ ] **Step 1: Write the failing tests.**

`tests/test_passwords.py`: the hash differs from the password and two hashes of the same password differ (salted); `verify_password` is `True` for the right password, `False` for a wrong one, `False` for `"not-a-hash"` and for an empty hash.

`tests/test_rate_limit.py` (injected clock list): after 5 failures `retry_after("k")` is a positive int ≤ 900; before the 5th it is `None`; advancing the clock past 900 s clears it; `reset` clears it; keys are independent.

`tests/test_account_service.py` (SQLite factory, fake clock via `now`, a `LoginRateLimiter` with a fake clock). Assertions by test name:

```python
def test_signup_returns_a_working_token_and_stores_only_its_hash():
    user, token = service.signup("Alice@Example.com", "correct horse")
    assert user.email == "alice@example.com"
    assert service.user_for_token(token) == user
    stored = session.scalars(select(AuthSession)).one().token_hash
    assert stored == hashlib.sha256(token.encode()).hexdigest() and token not in stored

def test_duplicate_email_differing_in_case_or_spaces_is_rejected():
    service.signup("alice@example.com", "password1")
    with pytest.raises(EmailTaken):
        service.signup("  Alice@Example.COM ", "password2")

@pytest.mark.parametrize("email, password", [("nope", "password1"), ("a@b", "password1"), ("a@b.co", "short"), ("a@b.co", "x" * 129), ("a" * 250 + "@b.co", "password1")])
def test_invalid_signup_input_is_rejected(email, password):
    with pytest.raises(InvalidSignup):
        service.signup(email, password)

def test_login_with_right_password_works_and_wrong_or_unknown_are_the_same_error():
    # wrong password and unknown email both raise InvalidLogin with the same str(exc)

def test_unknown_email_still_verifies_a_password_hash(monkeypatch):
    # count calls to accounts.service.verify_password: exactly 1 for an unknown email

def test_five_failures_lock_out_even_the_right_password_until_the_window_passes():
    # 5 InvalidLogin, then the 6th (correct password) raises TooManyAttempts with retry_after > 0;
    # after advancing the limiter clock 901 s the correct password logs in and resets the counter

def test_failures_from_another_ip_do_not_count():
    # 5 failed logins from "1.1.1.1"; a login from "2.2.2.2" with the right password succeeds,
    # and the same login from "1.1.1.1" raises TooManyAttempts

def test_expired_revoked_garbage_and_empty_tokens_resolve_to_none():
    # advance `now` past SESSION_TTL -> None; logout(token) -> None afterwards;
    # user_for_token("garbage") and user_for_token("") -> None

def test_logout_of_an_unknown_token_is_harmless():
    service.logout("never-issued")   # no exception
def test_find_user_is_case_insensitive_and_none_when_missing():
    user, _ = service.signup("alice@example.com", "password1")
    assert service.find_user(" ALICE@example.com") == user
    assert service.find_user("bob@example.com") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_passwords.py tests/test_rate_limit.py tests/test_account_service.py -q`
Expected: collection errors for the missing modules.

- [ ] **Step 3: Implement the three modules.** Approach notes the tests do not pin: email is validated with `^[^@\s]+@[^@\s]+\.[^@\s]+$`, stripped and lowercased, max 254 chars; password 8-128 characters; tokens come from `secrets.token_urlsafe(32)`; `login` checks the limiter first (key `f"{client_ip}|{email}"`), always calls `verify_password` (against a precomputed dummy hash when the email is unknown), calls `record_failure` on failure and `reset` on success; expiry and revocation are checked in `user_for_token` against the injected `now`.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_passwords.py tests/test_rate_limit.py tests/test_account_service.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add accounts/passwords.py accounts/rate_limit.py accounts/service.py tests/test_passwords.py tests/test_rate_limit.py tests/test_account_service.py
git commit -m "Add password hashing, login rate limiting and the account service" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Auth HTTP endpoints and the login dependency

**Files:**
- Create: `backend/accounts/router.py`, `backend/tests/test_auth_router.py`

**Interfaces:**
- Consumes: `AccountService`, `UserInfo`, the exceptions from Task 3.
- Produces (`accounts.router`): `SESSION_COOKIE = "edugen_session"`; `create_auth_router(service: AccountService, cookie_secure: bool = False) -> APIRouter` exposing
  `POST /auth/signup` (201), `POST /auth/login` (200), `POST /auth/logout` (204, always clears the cookie), `GET /auth/me` (200). Request body `{"email": str, "password": str}`; responses `{"user_id": str, "email": str}`.
  `create_current_user_dependency(service: AccountService) -> Callable[[Request], UserInfo]` raising `HTTPException(401, "Not logged in")` for a missing, empty, unknown, expired or revoked cookie.
- Cookie: HttpOnly, `SameSite=Lax`, `Path=/`, `Max-Age` equal to `SESSION_TTL`, `Secure` only when `cookie_secure`.
- Status mapping: `InvalidSignup` → 422 with its message; `EmailTaken` → 409 `"An account with this email already exists"`; `InvalidLogin` → 401 `"Invalid email or password"`; `TooManyAttempts` → 429 with header `Retry-After: <seconds>`.

- [ ] **Step 1: Write the failing tests** in `tests/test_auth_router.py` using a small `FastAPI` app with `create_auth_router(service)` plus a protected route `GET /private` depending on `create_current_user_dependency(service)`, and `TestClient`:

```python
def test_signup_sets_a_hardened_cookie_and_hides_secrets():
    response = client.post("/auth/signup", json={"email": "a@x.com", "password": "password1"})
    assert response.status_code == 201
    assert set(response.json()) == {"user_id", "email"}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "max-age=1209600" in cookie and "secure" not in cookie

def test_cookie_is_secure_when_configured():
    # same signup against a router built with cookie_secure=True:
    # "; secure" appears in the lower-cased Set-Cookie header

def test_me_requires_a_valid_session():
    assert client.get("/auth/me").status_code == 401
    client.cookies.set("edugen_session", "garbage")
    assert client.get("/auth/me").status_code == 401

def test_login_failures_are_identical_for_wrong_password_and_unknown_email():
    assert both responses are 401 with the same JSON body {"detail": "Invalid email or password"}

def test_sixth_attempt_is_rate_limited_with_retry_after():
    # 5 wrong passwords, then the correct one -> 429 and int(response.headers["retry-after"]) > 0

def test_logout_clears_the_cookie_and_kills_the_session_on_the_server():
    # keep the cookie value, call /auth/logout, put the old cookie back by hand -> /auth/me is 401

def test_duplicate_signup_is_409_and_bad_input_is_422():
    # second signup of the same email (any case) -> 409 {"detail": "An account with this email already exists"}
    # email "nope" or a 5-character password -> 422
def test_protected_route_is_401_without_login_and_200_with_it():
    # GET /private without a cookie -> 401 {"detail": "Not logged in"}
    # after signup the same client gets 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_auth_router.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'accounts.router'`.

- [ ] **Step 3: Implement `accounts/router.py`.** Pass `request.client.host` (or `"unknown"`) as `client_ip`. Pydantic body model with plain `str` fields (no `EmailStr`, to avoid a new dependency).

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_auth_router.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add accounts/router.py tests/test_auth_router.py
git commit -m "Add signup, login, logout and current-user endpoints" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Studio, library and media belong to a user

**Files:**
- Create: `backend/accounts/videos.py`, `backend/tests/test_video_repository.py`, `backend/tests/test_main_requires_login.py`
- Modify: `backend/services/job_service.py`, `backend/services/jobs_router.py`, `backend/services/media_response.py`, `backend/services/video_library.py`, `backend/main.py`, `backend/tests/test_job_service.py`, `backend/tests/test_media_response.py`, `backend/tests/test_video_library.py`

**Interfaces:**
- Consumes: `UserInfo`, `AccountService`, `create_current_user_dependency`, `create_auth_router` (Tasks 3-4); `Video` model (Task 2).
- Produces:
  - `accounts.videos`: frozen dataclass `VideoRecord(video_id: str, run_dir: str, title: str, kind: str, created_at: datetime)`; `VideoRepository(session_factory)` with `record(user_id: str, run_dir: str, title: str, kind: str = "topic") -> str`, `list_for_user(user_id: str) -> list[VideoRecord]` (newest first), `owner_of_run(run_dir: str) -> str | None`.
  - `JobService(pipeline, output_root, on_complete: Callable[[str, DemoVideoResponse], None] | None = None)`; `start(request, user_id: str) -> str`; `get(job_id, user_id: str) -> JobStatus | None` (`None` for unknown ids **and** other users' jobs); `run_blocking(request, user_id: str) -> DemoVideoResponse`. `on_complete(user_id, response)` runs after the pipeline succeeds and before the LLM log is finished as `completed`; if it raises, the job fails with that error.
  - `create_jobs_router(job_service, current_user: Callable[[Request], UserInfo]) -> APIRouter`; endpoints require `Depends(current_user)`.
  - `create_media_router(output_root, authorize: Callable[[Request, str], bool] | None = None)`: when given, `authorize(request, relative_path)` runs first; `False` gives the same 404 as a missing file. `authorize` may raise `HTTPException(401)` for an unauthenticated request. `None` keeps today's behaviour.
  - `list_videos(output_root, fix_video=ensure_faststart, run_dirs: set[str] | None = None)`: when `run_dirs` is given, only folders with those names are listed.

- [ ] **Step 1: Write the failing tests.**

`tests/test_video_repository.py` (SQLite factory; create two users first):
```python
def test_list_for_user_returns_only_that_users_videos_newest_first():
    # user 1 records "run-a" then "run-b", user 2 records "run-c"
    # list_for_user(user 1) -> run dirs ["run-b", "run-a"]; list_for_user(user 2) -> ["run-c"]
def test_owner_of_run_finds_the_owner_or_none():
    # owner_of_run("run-a") == user 1's id; owner_of_run("missing") is None
def test_run_dir_cannot_be_recorded_twice():
    # recording "run-a" a second time (even for another user) raises IntegrityError
```

`tests/test_job_service.py`: update every existing `start(REQUEST)`, `get(job_id)` and `run_blocking(REQUEST)` call to pass `USER = "user-1"`, then add:
```python
def test_another_users_job_is_invisible(tmp_path):
    job_id = service.start(REQUEST, "user-1"); service.wait(job_id, timeout=10)
    assert service.get(job_id, "user-2") is None
    assert service.get(job_id, "user-1").status == "completed"

def test_on_complete_receives_the_owner_and_the_result(tmp_path):
    calls = []
    service = JobService(pipeline, tmp_path, on_complete=lambda user_id, result: calls.append((user_id, result.video_url)))
    run_to_end(service)       # also run_blocking
    assert calls == [("user-1", "/media/out/lesson_demo.mp4")]

def test_a_failing_on_complete_fails_the_job_and_the_log(tmp_path):
    # on_complete raises RuntimeError("cannot record video") -> status "failed",
    # error.message == "RuntimeError: cannot record video", llm_calls.json status == "failed"

def test_jobs_endpoints_need_login_and_hide_other_users_jobs(tmp_path):
    # app = FastAPI(); stub current_user reads header X-User (401 when missing)
    # no header -> 401 on POST /lesson/jobs and GET /lesson/jobs/x
    # user-1 creates a job; user-2's GET of that id -> 404; user-1's GET -> 200
```

`tests/test_media_response.py`:
```python
def test_authorize_false_hides_an_existing_file_as_404():
    # router built with authorize=lambda request, path: False;
    # GET of an existing file -> 404, same response body as a missing file
def test_authorize_receives_the_request_and_relative_path_and_true_serves():
    # authorize records (request.url.path, relative_path) and returns True;
    # GET /media/run/lesson_demo.mp4 -> 200 and the recorded relative_path == "run/lesson_demo.mp4"
def test_authorize_can_demand_login_with_401():
    # authorize raises HTTPException(401, "Not logged in"); GET -> 401, even for a missing file
```

`tests/test_video_library.py`:
```python
def test_run_dirs_limits_the_listing(tmp_path):
    # folders "a-1" and "b-2" both contain lesson_demo.mp4; run_dirs={"a-1"} -> only a-1/lesson_demo.mp4
```

`tests/test_main_requires_login.py`: set dummy `GEMINI_API_KEY`, `GEMINI_MODEL` and `RAG_DATABASE_URL=postgresql+psycopg://u:p@localhost:1/x` with `monkeypatch.setenv` (importing `main` must not open a database connection), `importlib.import_module("main")`, then with `TestClient(main.app)` and **no cookie**:
```python
PROTECTED = [("POST", "/lesson/analyze"), ("POST", "/lesson/knowledge"), ("POST", "/lesson/plan"),
             ("POST", "/lesson/script"), ("POST", "/lesson/visual-plan"), ("POST", "/lesson/generate-demo-video"),
             ("POST", "/lesson/jobs"), ("GET", "/lesson/jobs/abc"), ("GET", "/videos"), ("GET", "/media/run/lesson_demo.mp4")]

@pytest.mark.parametrize("method, path", PROTECTED)
def test_studio_endpoints_require_login(method, path):
    assert client.request(method, path, json={} if method == "POST" else None).status_code == 401

def test_root_stays_public():
    assert client.get("/").status_code == 200
```
If a `POST` returns 422 instead of 401, declare the user dependency before the body parameter so authentication fails first.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_video_repository.py tests/test_job_service.py tests/test_media_response.py tests/test_video_library.py tests/test_main_requires_login.py -q`
Expected: failures/collection errors for the new signatures and the missing `accounts.videos`.

- [ ] **Step 3: Implement** `accounts/videos.py`, the `JobService`, jobs router, media router and `list_videos` changes exactly as specified in Interfaces. Each in-memory job stores its `user_id`; `_execute` calls `on_complete` after a successful pipeline and before `recorder.finish("completed")`, inside the existing failure handling.

- [ ] **Step 4: Wire `main.py`.**
  - Build `session_factory = build_session_factory()`, `account_service = AccountService(session_factory)`, `video_repository = VideoRepository(session_factory)`, `current_user = create_current_user_dependency(account_service)`.
  - `app.include_router(create_auth_router(account_service, cookie_secure=os.getenv("AUTH_COOKIE_SECURE", "").lower() in ("1", "true")))`.
  - Add `user: UserInfo = Depends(current_user)` to every `/lesson/*` route and `/videos`; `/lesson/generate-demo-video` calls `job_service.run_blocking(request, user.user_id)`; `/videos` calls `list_videos(output_root, run_dirs={r.run_dir for r in video_repository.list_for_user(user.user_id)})`.
  - `JobService(demo_video_service.generate_demo_video, output_root, on_complete=lambda user_id, response: video_repository.record(user_id, Path(response.output_dir).name, response.lesson_plan.title))`; `create_jobs_router(job_service, current_user)`.
  - `create_media_router(output_root, authorize=authorize_media)` where `authorize_media(request, relative_path)` reads the `edugen_session` cookie, raises `HTTPException(401, "Not logged in")` when `account_service.user_for_token(...)` is `None`, and returns `video_repository.owner_of_run(relative_path.split("/")[0]) == user.user_id`.
  - Keep the CORS settings (credentials are already allowed).

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest -q`
Expected: the whole default suite passes.

- [ ] **Step 6: Commit**

```bash
git add accounts/videos.py services/job_service.py services/jobs_router.py services/media_response.py services/video_library.py main.py tests/test_video_repository.py tests/test_job_service.py tests/test_media_response.py tests/test_video_library.py tests/test_main_requires_login.py
git commit -m "Make jobs, videos and media private to the logged-in user" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Papers and search are scoped to a user

**Files:**
- Modify: `backend/rag/pg_repository.py`, `backend/rag/storage_service.py`, `backend/scripts/ingest_research_pdf.py`, `backend/tests/test_rag_storage.py`, `backend/tests/test_postgres_integration.py`

**Interfaces:**
- Consumes: `RAGDocument.user_id` (Task 2), `AccountService.find_user` (Task 3).
- Produces: `RAGRepository` / `PostgresRAGRepository`:
  `find_document_by_sha256(user_id: str, source_sha256: str) -> str | None`,
  `persist_bundle(user_id: str, document, chunks, source_sha256: str, asset_bundle) -> tuple[str, bool]`,
  `search_similar(user_id: str, query_vector: Sequence[float], model_name: str, limit: int = 5, document_id: str | None = None) -> list[SimilarityHit]` (only chunks of documents owned by `user_id`; `document_id`, when given, narrows to that one document, and a document of another user yields `[]`).
  `RAGStorageService.persist_document(user_id: str, source_pdf, document, chunks) -> PersistenceResult` and `RAGStorageService.search_similar(user_id: str, query: str, limit: int = 5, document_id: str | None = None)`. `generate_missing_embeddings(document_id)` is unchanged.
  CLI: `python -m scripts.ingest_research_pdf <pdf> --user-email <email>` (required; exits with a clear message if the account does not exist).

- [ ] **Step 1: Write the failing tests.**

In `tests/test_rag_storage.py`, update `FakeRepository` to the new signatures (keying `existing_by_hash` by `(user_id, digest)` and recording `user_id`, `document_id` and `limit` of `search_similar` calls), update the existing calls to pass a `user_id`, and add:
```python
def test_the_same_pdf_is_stored_separately_for_each_user(tmp_path):
    first = service.persist_document("user-1", pdf_path, document, [chunk])
    second = service.persist_document("user-2", pdf_path, document, [chunk])
    assert not first.already_exists and not second.already_exists
    assert service.persist_document("user-1", pdf_path, document, [chunk]).already_exists

def test_search_passes_the_user_and_document_scope_through(tmp_path):
    service.search_similar("user-1", "what is AI?", limit=3, document_id="doc-9")
    assert repository.last_search == ("user-1", "doc-9", 3)
```

In `tests/test_postgres_integration.py` add (uses `AccountService` on the real database to create two users, `make_fixture` from `test_rag_storage`, a `ManagedAssetStore(tmp_path / "assets")` and an embedder returning a different fixed vector per distinct text):
```python
def test_two_users_store_the_same_paper_and_search_stays_private(...):
    # both persist_document calls succeed with different document ids
    # generate_missing_embeddings for each document
    # search as user A -> every hit.document_id == A's document; same for B
    # search as user A restricted to B's document_id -> []
    # search as a third user with no papers -> []
```
If storing the identical PDF a second time fails inside the asset store, that is a defect: content-addressed files that already exist with the same checksum must be reused.

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_rag_storage.py -q`, then with `RAG_TEST_DATABASE_URL` set: `python -m pytest tests/test_postgres_integration.py -q`
Expected: failures on the new signatures (TypeError) and on the missing scoping.

- [ ] **Step 3: Implement** the scoped repository methods (filter on `RAGDocument.user_id`, use the per-user unique constraint for idempotency, add `user_id` when inserting the document row), the service methods, and the CLI `--user-email` (resolve with `AccountService.find_user`, build the service from `build_session_factory()`).

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest -q`, then with `RAG_TEST_DATABASE_URL` set: `python -m pytest tests/test_postgres_integration.py -q`
Expected: all pass (integration: 5 passed).

- [ ] **Step 5: Commit**

```bash
git add rag/pg_repository.py rag/storage_service.py scripts/ingest_research_pdf.py tests/test_rag_storage.py tests/test_postgres_integration.py
git commit -m "Scope stored papers and similarity search to their owner" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Frontend: login screen and authenticated studio

**Files:**
- Create: `frontend/src/api.ts`, `frontend/src/AuthGate.tsx`, `frontend/src/LoginPage.tsx`
- Modify: `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: the Task 4 endpoints (`/auth/signup`, `/auth/login`, `/auth/logout`, `/auth/me`) and the now-private studio endpoints.
- Produces:
  - `api.ts`: `API_BASE = "http://localhost:8000"`; `apiFetch(path: string, init?: RequestInit): Promise<Response>` that always sends `credentials: "include"` and, on a 401 from any path except `/auth/login` and `/auth/signup`, dispatches `window.dispatchEvent(new Event("edugen:unauthorized"))`.
  - `AuthGate({ children }: { children: (user: AuthUser, logout: () => Promise<void>) => ReactNode })` with `type AuthUser = { user_id: string; email: string }`: asks `/auth/me` on load, shows `LoginPage` when logged out, returns to it when the unauthorized event fires.
  - `LoginPage({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void })`: one form with email and password, a switch between "Sign in" and "Create account", the server's error text (including "Too many attempts, try again in N seconds" built from `Retry-After` on a 429), and a hint that passwords need at least 8 characters.
  - `App({ user, onLogout })`: shows the account email and a "Log out" button in the top bar; every `fetch` becomes `apiFetch`.

- [ ] **Step 1: Implement** the three new files, update `main.tsx` to render `<AuthGate>{(user, logout) => <App user={user} onLogout={logout} />}</AuthGate>`, update `App.tsx` as described (leave the job polling, library and result player behaviour unchanged), and add login-card styles to `index.css` reusing the existing dark colours and fonts.

- [ ] **Step 2: Type-check, build and lint**

Run in `frontend/`: `bun run build` then `bun run lint`
Expected: `tsc -b` and `vite build` finish without errors; lint shows no errors (the one pre-existing `set-state-in-effect` warning may remain).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api.ts frontend/src/AuthGate.tsx frontend/src/LoginPage.tsx frontend/src/main.tsx frontend/src/App.tsx frontend/src/index.css
git commit -m "Add the login screen and send the session cookie with every request" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Final verification (suite, real database, two real users)

**Files:** none modified (scratch scripts go in `backend/scratch_*.py` and are not committed).

- [ ] **Step 1: Full suite and integration tests**

Run in `backend/`: `python -m pytest -q -m "slow or not slow"` then, with `RAG_TEST_DATABASE_URL` pointing at the disposable `edugen_rag_test` database, `python -m pytest tests/test_postgres_integration.py -q`
Expected: everything passes; report both counts.

- [ ] **Step 2: Migrate the development database**

Run: `python -m alembic -c alembic.ini upgrade head` then `python -m scripts.check_rag_db`
Expected: both migrations apply (this creates the tables in the database named by `RAG_DATABASE_URL`, which is the owner's development database); `check_rag_db` prints the database name.

- [ ] **Step 3: Two accounts against the real server**

Start `python -m uvicorn main:app --port 8000 --reload-exclude "output/*"` (or without `--reload`). With `curl -c`/`-b` cookie jars:
1. `GET /videos` without a cookie gives 401.
2. Sign up `alice@example.com` and `bob@example.com` (password at least 8 characters); `GET /auth/me` for each shows the right email.
3. A wrong password five times, then the right one, gives 429 with `Retry-After`.
4. As alice, `POST /lesson/jobs` with `{"request": "Explain binary search to a beginner"}`, poll to `completed` (about 10 minutes, uses Gemini). Then `GET /videos` as alice lists it; as bob it is `[]`; bob's `GET /lesson/jobs/<alice's id>` and `GET /media/<alice's run>/lesson_demo.mp4` are both 404; alice's media request with `Range: bytes=0-99` is 206.
5. After `POST /auth/logout`, alice's old cookie gives 401 on `/auth/me`.
Expected: each line behaves as stated.

- [ ] **Step 4: Browser check (the owner)**

Start the frontend (`bun run dev` in `frontend/`), open it, and confirm: the login screen appears first; creating an account works; the studio shows the account email and a Log out button; a generated video plays in the result panel and the library cards show a first frame (this proves the cookie reaches `<video>`); after logging out and signing in as another account the first account's videos are not listed. Report anything that differs; do not claim success on checks that were not performed.

- [ ] **Step 5: Report**

State per step what ran and the result, including anything not verified. Stop the server and delete scratch scripts. Anything failing goes back to the owning task, not into a quick patch.

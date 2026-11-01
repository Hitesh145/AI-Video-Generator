import io
import threading
from uuid import uuid4

import pytest
from accounts_helpers import make_session_factory

from accounts.models import User
from papers.ingestor import IngestResult
from papers.repository import PaperRepository
from papers.service import (
    CannotRetry,
    InvalidUpload,
    PaperService,
    UploadTooLarge,
)

PDF = b"%PDF-1.4\nbody\n%%EOF"


class FakeIngestor:
    def __init__(self):
        self.stage_log: list[str] = []
        self.ingest_calls = 0
        self.embed_calls = 0
        self.ingested_paths = []
        self.ingest_users = []
        self.path_existed = []
        self.fail_ingest_with: Exception | None = None
        self.fail_embed_with: Exception | None = None
        self.block: threading.Event | None = None
        self.entered = threading.Event()

    def ingest(self, user_id, pdf_path, work_dir, on_stage):
        self.ingest_calls += 1
        self.ingest_users.append(user_id)
        self.ingested_paths.append(pdf_path)
        self.path_existed.append(pdf_path.exists())
        on_stage("parsing", None)
        self.stage_log.append("parsing")
        self.entered.set()
        if self.block is not None:
            self.block.wait(timeout=10)
        if self.fail_ingest_with is not None:
            raise self.fail_ingest_with
        for stage in ("chunking", "storing"):
            on_stage(stage, None)
            self.stage_log.append(stage)
        return IngestResult(document_id="doc-1", title="Fake title", page_count=7, warnings=())

    def embed(self, document_id, on_stage):
        self.embed_calls += 1
        on_stage("embedding", None)
        self.stage_log.append("embedding")
        if self.fail_embed_with is not None:
            raise self.fail_embed_with
        return 1


@pytest.fixture
def env(tmp_path):
    class Env:
        pass

    e = Env()
    e.factory = make_session_factory()
    e.one, e.two = str(uuid4()), str(uuid4())
    with e.factory.begin() as session:
        session.add(User(user_id=e.one, email="one@x.com", password_hash="h"))
        session.add(User(user_id=e.two, email="two@x.com", password_hash="h"))
    e.repo = PaperRepository(e.factory)
    e.fake = FakeIngestor()
    e.upload_dir = tmp_path / "uploads"
    e.build = lambda **kw: PaperService(e.repo, e.fake, e.upload_dir, submit=lambda job: job(), **kw)
    e.service = e.build()
    return e


def upload(env, name="a.pdf", data=PDF, user=None):
    return env.service.upload(user or env.one, name, io.BytesIO(data))


def test_a_valid_upload_is_read_in_the_background_and_ends_ready(env):
    record, created = upload(env, "Paper.pdf")

    final = env.service.get(record.paper_id, env.one)
    assert created is True
    assert (final.status, final.detail, final.title, final.page_count) == ("ready", None, "Fake title", 7)
    assert final.document_id == "doc-1"
    assert env.fake.stage_log == ["parsing", "chunking", "storing", "embedding"]


def test_the_ingestor_gets_the_owner_and_a_file_named_after_the_paper_id(env):
    record, _ = upload(env)

    assert env.fake.ingest_users == [env.one]
    assert env.fake.ingested_paths[0].name == f"{record.paper_id}.pdf"
    assert env.fake.ingested_paths[0].parent == env.upload_dir
    assert env.fake.path_existed == [True]


def test_temporary_files_are_gone_afterwards_on_success_and_on_failure(env):
    upload(env, "ok.pdf")
    assert list(env.upload_dir.iterdir()) == []

    env.fake.fail_ingest_with = RuntimeError("boom")
    upload(env, "bad.pdf", PDF + b"2")
    assert list(env.upload_dir.iterdir()) == []


@pytest.mark.parametrize("name, expected", [
    ("..\\..\\evil.pdf", "evil.pdf"),
    ("../x/y/z.pdf", "z.pdf"),
    ("résumé 论文.pdf", "résumé 论文.pdf"),
    ("a\x00b.pdf", "ab.pdf"),
])
def test_the_clients_filename_is_only_a_display_label(env, name, expected):
    record, _ = upload(env, name)

    assert record.filename == expected
    assert all(path.parent == env.upload_dir for path in env.fake.ingested_paths)


def test_non_pdf_extension_empty_and_headerless_files_are_rejected_with_a_reason(env):
    with pytest.raises(InvalidUpload, match="PDF"):
        upload(env, "notes.txt")
    with pytest.raises(InvalidUpload, match="empty"):
        upload(env, "a.pdf", b"")
    with pytest.raises(InvalidUpload, match="not a valid PDF"):
        upload(env, "a.pdf", b"hello world")

    assert list(env.upload_dir.iterdir()) == []
    assert env.repo.list_for_user(env.one) == []


def test_an_oversized_upload_is_refused_and_leaves_nothing_behind(env):
    small = env.build(max_upload_bytes=100)

    with pytest.raises(UploadTooLarge):
        small.upload(env.one, "a.pdf", io.BytesIO(PDF + b"x" * 200))

    assert list(env.upload_dir.iterdir()) == []
    assert env.repo.list_for_user(env.one) == []


def test_the_same_pdf_twice_returns_the_existing_paper_and_reads_it_once(env):
    first, created_first = upload(env, "a.pdf")
    second, created_second = upload(env, "renamed.pdf")

    assert (created_first, created_second) == (True, False)
    assert second.paper_id == first.paper_id
    assert env.fake.ingest_calls == 1


def test_two_users_can_each_add_the_same_pdf(env):
    first, created_first = upload(env, "a.pdf", user=env.one)
    second, created_second = upload(env, "a.pdf", user=env.two)

    assert (created_first, created_second) == (True, True)
    assert first.paper_id != second.paper_id
    assert env.fake.ingest_calls == 2


def test_reuploading_a_paper_that_failed_while_reading_tries_again(env):
    env.fake.fail_ingest_with = RuntimeError("layout model crashed")
    failed, _ = upload(env)
    assert env.service.get(failed.paper_id, env.one).status == "failed"

    env.fake.fail_ingest_with = None
    again, created = upload(env)

    assert (created, again.paper_id) == (False, failed.paper_id)
    assert env.service.get(failed.paper_id, env.one).status == "ready"
    assert env.fake.ingest_calls == 2


def test_a_failure_while_reading_leaves_a_readable_one_line_reason(env):
    env.fake.fail_ingest_with = RuntimeError("Could not parse 'a.pdf':\n  line two")
    record, _ = upload(env)

    final = env.service.get(record.paper_id, env.one)

    assert final.status == "failed"
    assert "\n" not in final.detail and "Could not parse" in final.detail
    assert final.document_id is None


def test_a_very_long_failure_reason_is_cut(env):
    env.fake.fail_ingest_with = RuntimeError("x" * 1000)
    record, _ = upload(env)

    assert len(env.service.get(record.paper_id, env.one).detail) <= 300


def test_an_embedding_failure_keeps_the_stored_text_and_retry_finishes_the_job(env):
    env.fake.fail_embed_with = RuntimeError("getaddrinfo failed")
    record, _ = upload(env)
    failed = env.service.get(record.paper_id, env.one)
    assert failed.status == "failed" and failed.document_id == "doc-1"
    assert "saved" in failed.detail and "getaddrinfo failed" in failed.detail

    env.fake.fail_embed_with = None
    assert env.service.retry(record.paper_id, env.one).status in ("embedding", "ready")

    assert env.service.get(record.paper_id, env.one).status == "ready"
    assert env.fake.ingest_calls == 1                      # not read again


def test_retry_is_refused_for_ready_papers_and_for_papers_that_never_got_stored(env):
    ready, _ = upload(env, "ok.pdf")
    env.fake.fail_ingest_with = RuntimeError("boom")
    never_stored, _ = upload(env, "bad.pdf", PDF + b"2")

    with pytest.raises(CannotRetry, match="Only failed papers"):
        env.service.retry(ready.paper_id, env.one)
    with pytest.raises(CannotRetry, match="upload it again"):
        env.service.retry(never_stored.paper_id, env.one)


def test_papers_of_other_users_are_invisible(env):
    record, _ = upload(env)

    assert env.service.get(record.paper_id, env.two) is None
    assert env.service.retry(record.paper_id, env.two) is None
    assert env.service.report(record.paper_id, env.two) is None
    assert env.service.list(env.two) == []


def test_report_is_only_available_once_the_paper_is_stored(env):
    stored, _ = upload(env, "ok.pdf")
    env.fake.fail_ingest_with = RuntimeError("boom")
    unstored, _ = upload(env, "bad.pdf", PDF + b"2")
    env.repo.report = lambda document_id: f"report for {document_id}"

    assert env.service.report(stored.paper_id, env.one) == "report for doc-1"
    assert env.service.report(unstored.paper_id, env.one) is None


def test_unfinished_papers_are_failed_after_a_restart(env):
    queued = env.repo.create(env.one, "q.pdf", 1, "1" * 64)
    parsing = env.repo.create(env.one, "p.pdf", 1, "2" * 64)
    ready = env.repo.create(env.one, "r.pdf", 1, "3" * 64)
    env.repo.update(parsing.paper_id, status="parsing")
    env.repo.update(ready.paper_id, status="ready")

    assert env.service.fail_interrupted() == 2

    for paper in (queued, parsing):
        after = env.service.get(paper.paper_id, env.one)
        assert after.status == "failed" and "restarted" in after.detail
    assert env.service.get(ready.paper_id, env.one).status == "ready"


def test_only_one_paper_is_read_at_a_time_and_the_rest_wait_as_queued(env, tmp_path):
    threaded = PaperService(PaperRepository(make_session_factory(tmp_path / "threads.db")), env.fake, env.upload_dir)
    repo = threaded.repository
    with repo._session_factory.begin() as session:
        session.add(User(user_id=env.one, email="one@x.com", password_hash="h"))
    env.fake.block = threading.Event()

    ids = [threaded.upload(env.one, f"{i}.pdf", io.BytesIO(PDF + bytes([i])))[0].paper_id for i in range(3)]
    assert env.fake.entered.wait(10)

    assert sorted(threaded.get(i, env.one).status for i in ids) == ["parsing", "queued", "queued"]
    env.fake.block.set()
    for paper_id in ids:
        threaded.wait(paper_id, timeout=20)
    assert {threaded.get(i, env.one).status for i in ids} == {"ready"}


def test_a_restart_clears_files_left_behind_by_an_interrupted_read(env):
    env.upload_dir.mkdir(parents=True)
    (env.upload_dir / "old-paper.pdf").write_bytes(PDF)
    (env.upload_dir / "half-uploaded.part").write_bytes(b"%PDF-")
    (env.upload_dir / "old-paper.work" / "figures").mkdir(parents=True)
    (env.upload_dir / "old-paper.work" / "figures" / "figure_1.png").write_bytes(b"png")

    env.service.fail_interrupted()

    assert list(env.upload_dir.iterdir()) == []


def test_a_restart_with_no_upload_folder_yet_is_fine(env):
    assert not env.upload_dir.exists()

    assert env.service.fail_interrupted() == 0

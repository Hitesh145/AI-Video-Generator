from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from accounts_helpers import make_session_factory
from sqlalchemy.exc import IntegrityError

from accounts.models import User
from papers.models import Paper
from papers.repository import PaperRepository

HASH_A, HASH_B = "a" * 64, "b" * 64


@pytest.fixture
def env():
    class Env:
        pass

    e = Env()
    e.factory = make_session_factory()
    e.repo = PaperRepository(e.factory)
    e.one, e.two = str(uuid4()), str(uuid4())
    with e.factory.begin() as session:
        session.add(User(user_id=e.one, email="one@x.com", password_hash="h"))
        session.add(User(user_id=e.two, email="two@x.com", password_hash="h"))
    return e


def test_create_starts_queued_and_is_private_to_the_owner(env):
    record = env.repo.create(env.one, "paper.pdf", 1234, HASH_A)

    assert (record.status, record.detail, record.document_id) == ("queued", None, None)
    assert env.repo.get(record.paper_id, env.one).filename == "paper.pdf"
    assert env.repo.get(record.paper_id, env.two) is None


def test_the_same_pdf_cannot_be_added_twice_by_one_user_but_two_users_can(env):
    env.repo.create(env.one, "a.pdf", 1, HASH_A)
    env.repo.create(env.two, "a.pdf", 1, HASH_A)                      # fine

    with pytest.raises(IntegrityError):
        env.repo.create(env.one, "again.pdf", 1, HASH_A)
    assert env.repo.find_by_hash(env.one, HASH_A).filename == "a.pdf"
    assert env.repo.find_by_hash(env.one, HASH_B) is None


def test_list_is_newest_first_and_only_the_users_own(env):
    names = ["first.pdf", "second.pdf", "third.pdf"]
    records = [env.repo.create(env.one, name, 1, str(index) * 64) for index, name in enumerate(names)]
    env.repo.create(env.two, "other.pdf", 1, "9" * 64)
    base = datetime(2026, 11, 2, tzinfo=timezone.utc)
    with env.factory.begin() as session:
        for offset, record in enumerate(records):
            session.get(Paper, record.paper_id).created_at = base + timedelta(minutes=offset)

    assert [p.filename for p in env.repo.list_for_user(env.one)] == ["third.pdf", "second.pdf", "first.pdf"]
    assert [p.filename for p in env.repo.list_for_user(env.two)] == ["other.pdf"]


def test_update_changes_only_the_named_fields_and_bumps_updated_at(env):
    record = env.repo.create(env.one, "a.pdf", 1, HASH_A)

    env.repo.update(record.paper_id, status="parsing", detail="Reading the PDF")

    after = env.repo.get(record.paper_id, env.one)
    assert (after.status, after.detail, after.filename) == ("parsing", "Reading the PDF", "a.pdf")
    assert after.updated_at >= record.updated_at


def test_update_can_clear_a_field_and_set_the_result(env):
    record = env.repo.create(env.one, "a.pdf", 1, HASH_A)
    env.repo.update(record.paper_id, status="failed", detail="boom")

    env.repo.update(record.paper_id, status="ready", detail=None, title="A title", page_count=7)

    after = env.repo.get(record.paper_id, env.one)
    assert (after.status, after.detail, after.title, after.page_count) == ("ready", None, "A title", 7)


def test_update_rejects_unknown_fields(env):
    record = env.repo.create(env.one, "a.pdf", 1, HASH_A)

    with pytest.raises(ValueError):
        env.repo.update(record.paper_id, filename="evil.pdf")


def test_fail_interrupted_only_touches_unfinished_papers(env):
    queued = env.repo.create(env.one, "q.pdf", 1, "1" * 64)
    embedding = env.repo.create(env.one, "e.pdf", 1, "2" * 64)
    ready = env.repo.create(env.one, "r.pdf", 1, "3" * 64)
    failed = env.repo.create(env.one, "f.pdf", 1, "4" * 64)
    env.repo.update(embedding.paper_id, status="embedding")
    env.repo.update(ready.paper_id, status="ready")
    env.repo.update(failed.paper_id, status="failed", detail="earlier problem")

    changed = env.repo.fail_interrupted("The server restarted")

    assert changed == 2
    assert env.repo.get(queued.paper_id, env.one).status == "failed"
    assert env.repo.get(embedding.paper_id, env.one).detail == "The server restarted"
    assert env.repo.get(ready.paper_id, env.one).status == "ready"
    assert env.repo.get(failed.paper_id, env.one).detail == "earlier problem"


def test_claiming_a_paper_for_reading_works_once_and_only_for_failed_papers_without_a_document(env):
    failed = env.repo.create(env.one, "f.pdf", 1, "1" * 64)
    env.repo.update(failed.paper_id, status="failed", detail="boom")
    stored = env.repo.create(env.one, "s.pdf", 1, "2" * 64)
    env.repo.update(stored.paper_id, status="failed", document_id="doc-1")
    ready = env.repo.create(env.one, "r.pdf", 1, "3" * 64)
    env.repo.update(ready.paper_id, status="ready")

    assert env.repo.claim_for_reading(failed.paper_id) is True
    assert env.repo.claim_for_reading(failed.paper_id) is False         # already claimed
    assert env.repo.claim_for_reading(stored.paper_id) is False         # has stored text: use retry
    assert env.repo.claim_for_reading(ready.paper_id) is False
    after = env.repo.get(failed.paper_id, env.one)
    assert (after.status, after.detail) == ("queued", None)


def test_claiming_a_paper_for_retry_works_once_and_only_for_failed_papers_with_a_document(env):
    stored = env.repo.create(env.one, "s.pdf", 1, "2" * 64)
    env.repo.update(stored.paper_id, status="failed", document_id="doc-1", detail="indexing failed")
    unstored = env.repo.create(env.one, "u.pdf", 1, "4" * 64)
    env.repo.update(unstored.paper_id, status="failed")

    assert env.repo.claim_for_retry(stored.paper_id) is True
    assert env.repo.claim_for_retry(stored.paper_id) is False
    assert env.repo.claim_for_retry(unstored.paper_id) is False
    after = env.repo.get(stored.paper_id, env.one)
    assert (after.status, after.detail) == ("embedding", "Indexing passages")

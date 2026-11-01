from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from accounts_helpers import make_session_factory
from sqlalchemy.exc import IntegrityError

from accounts.models import User, Video
from accounts.videos import VideoRepository


def make_repo():
    factory = make_session_factory()
    ids = {name: str(uuid4()) for name in ("one", "two")}
    with factory.begin() as session:
        for name, user_id in ids.items():
            session.add(User(user_id=user_id, email=f"{name}@x.com", password_hash="h"))
    return VideoRepository(factory), factory, ids


def test_list_for_user_returns_only_that_users_videos_newest_first():
    repo, factory, ids = make_repo()
    repo.record(ids["one"], "run-a", "First")
    repo.record(ids["one"], "run-b", "Second")
    repo.record(ids["two"], "run-c", "Other")
    with factory.begin() as session:           # make the ordering unambiguous
        base = datetime(2026, 11, 1, tzinfo=timezone.utc)
        for offset, run_dir in enumerate(["run-a", "run-b", "run-c"]):
            session.query(Video).filter(Video.run_dir == run_dir).update({"created_at": base + timedelta(minutes=offset)})

    assert [v.run_dir for v in repo.list_for_user(ids["one"])] == ["run-b", "run-a"]
    assert [v.run_dir for v in repo.list_for_user(ids["two"])] == ["run-c"]
    first = repo.list_for_user(ids["one"])[1]
    assert (first.title, first.kind) == ("First", "topic")


def test_owner_of_run_finds_the_owner_or_none():
    repo, _, ids = make_repo()
    repo.record(ids["one"], "run-a", "First")

    assert repo.owner_of_run("run-a") == ids["one"]
    assert repo.owner_of_run("missing") is None


def test_run_dir_cannot_be_recorded_twice():
    repo, _, ids = make_repo()
    repo.record(ids["one"], "run-a", "First")

    with pytest.raises(IntegrityError):
        repo.record(ids["two"], "run-a", "Stolen")

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from accounts_helpers import make_session_factory

from accounts.models import User, Video
from accounts.videos import VideoRepository
from papers.models import Paper


def make_world():
    factory = make_session_factory()
    users = {name: str(uuid4()) for name in ("one", "two")}
    papers = {name: str(uuid4()) for name in ("a", "b", "other")}
    owners = {"a": "one", "b": "one", "other": "two"}
    with factory.begin() as session:
        for name, user_id in users.items():
            session.add(User(user_id=user_id, email=f"{name}@x.com", password_hash="h"))
        for name, paper_id in papers.items():
            session.add(Paper(paper_id=paper_id, user_id=users[owners[name]], filename=f"{name}.pdf",
                              size_bytes=1, sha256=name * 64))
    return VideoRepository(factory), factory, users, papers


def test_record_stores_the_paper_and_kind():
    repo, _, users, papers = make_world()

    repo.record(users["one"], "run-a", "From the paper", kind="paper", paper_id=papers["a"])

    record = repo.list_for_user(users["one"])[0]
    assert (record.kind, record.paper_id) == ("paper", papers["a"])


def test_list_for_paper_returns_only_that_users_videos_of_that_paper_newest_first():
    repo, factory, users, papers = make_world()
    repo.record(users["one"], "run-1", "One", kind="paper", paper_id=papers["a"])
    repo.record(users["one"], "run-2", "Two", kind="general", paper_id=papers["a"])
    repo.record(users["one"], "run-3", "Other paper", kind="paper", paper_id=papers["b"])
    repo.record(users["two"], "run-4", "Someone else", kind="paper", paper_id=papers["other"])
    with factory.begin() as session:
        base = datetime(2026, 11, 1, tzinfo=timezone.utc)
        for offset, run_dir in enumerate(["run-1", "run-2", "run-3", "run-4"]):
            session.query(Video).filter(Video.run_dir == run_dir).update({"created_at": base + timedelta(minutes=offset)})

    found = repo.list_for_paper(users["one"], papers["a"])

    assert [v.run_dir for v in found] == ["run-2", "run-1"]
    assert [v.kind for v in found] == ["general", "paper"]


def test_list_for_paper_with_someone_elses_paper_id_is_empty():
    repo, _, users, papers = make_world()
    repo.record(users["two"], "run-4", "Someone else", kind="paper", paper_id=papers["other"])

    assert repo.list_for_paper(users["one"], papers["other"]) == []


def test_existing_calls_without_a_paper_still_work():
    repo, _, users, _ = make_world()

    repo.record(users["one"], "run-a", "Studio video")

    record = repo.list_for_user(users["one"])[0]
    assert (record.kind, record.paper_id) == ("topic", None)

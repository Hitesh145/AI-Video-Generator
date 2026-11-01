from uuid import uuid4

import pytest
from accounts_helpers import make_session_factory
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from test_paper_service import PDF, FakeIngestor

from accounts.models import User
from accounts.service import UserInfo
from papers.repository import PaperReport, PaperRepository
from papers.router import create_papers_router
from papers.service import PaperService

U1, U2 = {"x-user": "u1"}, {"x-user": "u2"}


def stub_current_user(request: Request) -> UserInfo:
    user_id = request.headers.get("x-user")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    return UserInfo(user_id, f"{user_id}@x.com")


@pytest.fixture
def env(tmp_path):
    class Env:
        pass

    e = Env()
    e.factory = make_session_factory()
    with e.factory.begin() as session:
        for user_id in ("u1", "u2"):
            session.add(User(user_id=user_id, email=f"{user_id}@x.com", password_hash="h"))
    e.repo = PaperRepository(e.factory)
    e.repo.report = lambda document_id: PaperReport(
        title="Fake title", authors=["A. Author"], page_count=7, chunk_count=12, figure_count=3,
        warnings=["Table 2 could not be read"],
    )
    e.fake = FakeIngestor()
    e.build = lambda **kw: TestClient(_app(PaperService(e.repo, e.fake, tmp_path / "uploads", submit=lambda job: job(), **kw)))
    e.client = e.build()
    return e


def _app(service):
    app = FastAPI()
    app.include_router(create_papers_router(service, stub_current_user))
    return app


def upload(client, name="paper.pdf", data=PDF, headers=U1):
    return client.post("/papers", files={"file": (name, data, "application/pdf")}, headers=headers)


def test_everything_requires_login(env):
    for method, path in [("GET", "/papers"), ("POST", "/papers"), ("GET", "/papers/x"), ("POST", "/papers/x/retry")]:
        assert env.client.request(method, path).status_code == 401, path


def test_upload_returns_202_then_the_paper_appears_in_the_list_as_ready(env):
    response = upload(env.client)

    assert response.status_code == 202
    assert response.json()["filename"] == "paper.pdf"
    listed = env.client.get("/papers", headers=U1).json()
    assert [p["status"] for p in listed] == ["ready"]
    assert listed[0]["can_retry"] is False and listed[0]["title"] == "Fake title"


def test_uploading_the_same_file_again_returns_200_and_the_same_paper(env):
    first = upload(env.client)
    second = upload(env.client)

    assert (first.status_code, second.status_code) == (202, 200)
    assert first.json()["paper_id"] == second.json()["paper_id"]


def test_bad_uploads_get_a_plain_reason(env):
    assert "PDF" in upload(env.client, name="notes.txt").json()["detail"]
    assert "empty" in upload(env.client, data=b"").json()["detail"]
    bad = upload(env.client, name="a.pdf", data=b"hello")
    assert bad.status_code == 400 and "not a valid PDF" in bad.json()["detail"]


def test_an_oversized_file_is_413(env):
    small = env.build(max_upload_bytes=100)

    response = upload(small, data=PDF + b"x" * 500)

    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


def test_detail_includes_the_reading_report_for_a_stored_paper(env):
    paper_id = upload(env.client).json()["paper_id"]

    body = env.client.get(f"/papers/{paper_id}", headers=U1).json()

    assert body["report"] == {
        "title": "Fake title", "authors": ["A. Author"], "page_count": 7,
        "chunk_count": 12, "figure_count": 3, "warnings": ["Table 2 could not be read"],
    }
    assert body["status"] == "ready"


def test_detail_has_no_report_for_a_paper_that_was_never_stored(env):
    env.fake.fail_ingest_with = RuntimeError("layout model crashed")
    paper_id = upload(env.client).json()["paper_id"]

    body = env.client.get(f"/papers/{paper_id}", headers=U1).json()

    assert body["status"] == "failed" and body["report"] is None and body["can_retry"] is False


def test_another_users_paper_is_404_on_detail_and_retry_and_missing_from_their_list(env):
    paper_id = upload(env.client, headers=U1).json()["paper_id"]

    assert env.client.get(f"/papers/{paper_id}", headers=U2).status_code == 404
    assert env.client.post(f"/papers/{paper_id}/retry", headers=U2).status_code == 404
    assert env.client.get("/papers", headers=U2).json() == []
    assert env.client.get(f"/papers/{uuid4()}", headers=U1).status_code == 404


def test_retry_conflicts_are_409_with_the_reason(env):
    paper_id = upload(env.client).json()["paper_id"]

    response = env.client.post(f"/papers/{paper_id}/retry", headers=U1)

    assert response.status_code == 409
    assert response.json() == {"detail": "Only failed papers can be retried"}


def test_a_failed_embedding_shows_can_retry_and_retry_returns_202(env):
    env.fake.fail_embed_with = RuntimeError("getaddrinfo failed")
    paper_id = upload(env.client).json()["paper_id"]
    failed = env.client.get(f"/papers/{paper_id}", headers=U1).json()
    assert (failed["status"], failed["can_retry"]) == ("failed", True)

    env.fake.fail_embed_with = None
    assert env.client.post(f"/papers/{paper_id}/retry", headers=U1).status_code == 202
    assert env.client.get(f"/papers/{paper_id}", headers=U1).json()["status"] == "ready"

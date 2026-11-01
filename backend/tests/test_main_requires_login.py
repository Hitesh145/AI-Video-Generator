import importlib

import pytest
from fastapi.testclient import TestClient

PROTECTED = [
    ("POST", "/lesson/analyze"),
    ("POST", "/lesson/knowledge"),
    ("POST", "/lesson/plan"),
    ("POST", "/lesson/script"),
    ("POST", "/lesson/visual-plan"),
    ("POST", "/lesson/generate-demo-video"),
    ("POST", "/lesson/jobs"),
    ("GET", "/lesson/jobs/abc"),
    ("GET", "/videos"),
    ("GET", "/media/run/lesson_demo.mp4"),
    ("GET", "/papers"),
    ("POST", "/papers"),
    ("GET", "/papers/abc"),
    ("POST", "/papers/abc/retry"),
]


@pytest.fixture(scope="module")
def client():
    # Importing main must not open a database connection or call Gemini; dummy settings are enough.
    mp = pytest.MonkeyPatch()
    mp.setenv("GEMINI_API_KEY", "test-key")
    mp.setenv("GEMINI_MODEL", "test-model")
    mp.setenv("RAG_DATABASE_URL", "postgresql+psycopg://user:pw@localhost:1/none")
    try:
        main = importlib.import_module("main")
        yield TestClient(main.app)
    finally:
        mp.undo()


@pytest.mark.parametrize("method, path", PROTECTED)
def test_studio_endpoints_require_login(client, method, path):
    response = client.request(method, path, json={} if method == "POST" else None)

    assert response.status_code == 401


def test_root_stays_public(client):
    assert client.get("/").status_code == 200


def test_auth_endpoints_are_mounted(client):
    paths = {route.path for route in client.app.routes}

    assert {"/auth/signup", "/auth/login", "/auth/logout", "/auth/me"} <= paths


def test_state_changing_requests_from_untrusted_origins_are_refused(client):
    for path in ("/auth/logout", "/lesson/jobs", "/auth/login"):
        response = client.post(path, json={}, headers={"Origin": "http://localhost:3000"})
        assert response.status_code == 403, path


def test_the_apps_own_origin_is_not_blocked(client):
    response = client.post("/auth/logout", headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 204


def test_paper_uploads_from_untrusted_origins_are_refused(client):
    response = client.post("/papers", json={}, headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 403


def test_an_oversized_upload_is_refused_with_headers_the_browser_can_read(client):
    too_big = b"x" * (51 * 1024 * 1024 + 70_000)       # more than the 50 MB default plus form overhead

    response = client.post("/papers", content=too_big, headers={"Origin": "http://localhost:5173"})

    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "larger than" in response.json()["detail"]

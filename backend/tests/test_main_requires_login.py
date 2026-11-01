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

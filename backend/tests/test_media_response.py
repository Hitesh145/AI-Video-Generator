import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.media_response import create_media_router


DATA = bytes(range(256)) * 4        # 1024 bytes


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "output"
    (root / "run").mkdir(parents=True)
    (root / "run" / "lesson_demo.mp4").write_bytes(DATA)
    (root / "run" / "notes.json").write_text("{}", encoding="utf-8")
    (root / "run" / "empty.mp4").write_bytes(b"")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    app = FastAPI()
    app.include_router(create_media_router(root))
    return TestClient(app)


URL = "/media/run/lesson_demo.mp4"


def test_whole_file_is_served_with_range_support_advertised(client):
    response = client.get(URL)

    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "1024"


@pytest.mark.parametrize("header, expected, content_range", [
    ("bytes=0-99", DATA[:100], "bytes 0-99/1024"),
    ("bytes=100-", DATA[100:], "bytes 100-1023/1024"),
    ("bytes=-50", DATA[-50:], "bytes 974-1023/1024"),
    ("bytes=1000-5000", DATA[1000:], "bytes 1000-1023/1024"),
    ("bytes=0-0", DATA[:1], "bytes 0-0/1024"),
])
def test_ranges_return_partial_content(client, header, expected, content_range):
    response = client.get(URL, headers={"Range": header})

    assert response.status_code == 206
    assert response.content == expected
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(expected))


@pytest.mark.parametrize("header", ["bytes=2000-", "bytes=5-2", "bytes=-0", "bytes=1024-1030"])
def test_unsatisfiable_ranges_return_416(client, header):
    response = client.get(URL, headers={"Range": header})

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */1024"


@pytest.mark.parametrize("header", ["bytes=abc", "bytes=0-1,5-6", "items=0-5", "bytes=-"])
def test_unsupported_range_syntax_falls_back_to_the_whole_file(client, header):
    response = client.get(URL, headers={"Range": header})

    assert response.status_code == 200
    assert response.content == DATA


def test_other_file_types_get_their_own_content_type(client):
    response = client.get("/media/run/notes.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


def test_empty_file_is_served_empty(client):
    response = client.get("/media/run/empty.mp4")

    assert response.status_code == 200
    assert response.content == b""


@pytest.mark.parametrize("path", [
    "/media/run/missing.mp4",
    "/media/run",
    "/media/../secret.txt",
    "/media/%2e%2e/secret.txt",
    "/media/run/../../secret.txt",
    "/media/run/%2e%2e/%2e%2e/secret.txt",
])
def test_missing_files_directories_and_traversal_are_404(client, path):
    assert client.get(path).status_code == 404


def test_head_returns_the_headers_without_a_body(client):
    response = client.head(URL)

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == "1024"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"


def test_head_honours_a_range(client):
    response = client.head(URL, headers={"Range": "bytes=0-99"})

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-99/1024"
    assert response.content == b""


def test_last_modified_is_sent_for_caching(client):
    response = client.get(URL)

    assert response.headers["last-modified"].endswith("GMT")


def test_download_flag_asks_the_browser_to_save_the_file(client):
    plain = client.get(URL)
    download = client.get(URL + "?download=1")

    assert "content-disposition" not in plain.headers
    assert download.headers["content-disposition"] == 'attachment; filename="lesson_demo.mp4"'
    assert download.content == DATA


def make_authorized_client(tmp_path, authorize):
    root = tmp_path / "output"
    (root / "run").mkdir(parents=True)
    (root / "run" / "lesson_demo.mp4").write_bytes(DATA)
    app = FastAPI()
    app.include_router(create_media_router(root, authorize=authorize))
    return TestClient(app)


def test_authorize_false_hides_an_existing_file_as_404(tmp_path):
    client = make_authorized_client(tmp_path, lambda request, path: False)

    denied = client.get("/media/run/lesson_demo.mp4")
    missing = client.get("/media/run/missing.mp4")

    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()


def test_authorize_receives_the_request_and_relative_path_and_true_serves(tmp_path):
    seen = []

    def authorize(request, relative_path):
        seen.append((request.url.path, relative_path))
        return True

    client = make_authorized_client(tmp_path, authorize)

    response = client.get("/media/run/lesson_demo.mp4")

    assert response.status_code == 200
    assert seen == [("/media/run/lesson_demo.mp4", "run/lesson_demo.mp4")]


def test_authorize_can_demand_login_with_401(tmp_path):
    from fastapi import HTTPException

    def authorize(request, relative_path):
        raise HTTPException(status_code=401, detail="Not logged in")

    client = make_authorized_client(tmp_path, authorize)

    assert client.get("/media/run/lesson_demo.mp4").status_code == 401
    assert client.get("/media/run/missing.mp4").status_code == 401


def make_two_owner_client(tmp_path):
    root = tmp_path / "output"
    for name, body in (("alice-run", b"ALICE"), ("bob-run", b"BOB-SECRET")):
        (root / name).mkdir(parents=True)
        (root / name / "lesson_demo.mp4").write_bytes(body)
    (root / "bob-run" / "llm_calls.json").write_text("{}", encoding="utf-8")
    owners = {"alice-run": "alice", "bob-run": "bob"}

    def authorize(request, relative_path):          # the same rule main.py uses: first segment decides
        return owners.get(relative_path.split("/")[0]) == "alice"

    app = FastAPI()
    app.include_router(create_media_router(root, authorize=authorize))
    return TestClient(app)


def test_the_owner_can_still_read_their_own_run(tmp_path):
    response = make_two_owner_client(tmp_path).get("/media/alice-run/lesson_demo.mp4")

    assert (response.status_code, response.content) == (200, b"ALICE")


@pytest.mark.parametrize("url", [
    "/media/bob-run/lesson_demo.mp4",
    "/media/alice-run/%2e%2e/bob-run/lesson_demo.mp4",
    "/media/alice-run%2F..%2Fbob-run%2Flesson_demo.mp4",
    "/media/alice-run/..%5Cbob-run/lesson_demo.mp4",
    "/media/alice-run/%2e%2e/bob-run/llm_calls.json",
    "/media/alice-run//bob-run/lesson_demo.mp4",
    "/media/alice-run/./../bob-run/lesson_demo.mp4",
    "/media/alice-run/C:%5Cwindows%5Cwin.ini",
])
def test_encoded_dot_segments_cannot_borrow_another_runs_ownership(tmp_path, url):
    response = make_two_owner_client(tmp_path).get(url)

    assert response.status_code == 404
    assert b"BOB-SECRET" not in response.content

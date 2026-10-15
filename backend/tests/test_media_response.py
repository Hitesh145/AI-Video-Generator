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

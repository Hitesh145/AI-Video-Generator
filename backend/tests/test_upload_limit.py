import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from papers.limits import UploadSizeLimitMiddleware


def build(max_body_bytes=1000):
    app = FastAPI()
    app.state.reads = 0

    @app.post("/papers")
    async def upload(request: Request):
        body = await request.body()
        app.state.reads += 1
        return {"size": len(body)}

    @app.post("/other")
    async def other(request: Request):
        return {"size": len(await request.body())}

    app.add_middleware(UploadSizeLimitMiddleware, max_body_bytes=max_body_bytes,
                       message="The file is larger than the limit")
    return app, TestClient(app)


def test_a_small_upload_passes_through():
    app, client = build()

    response = client.post("/papers", content=b"x" * 500)

    assert response.status_code == 200 and response.json() == {"size": 500}


def test_a_declared_oversized_body_is_refused_before_the_app_runs():
    app, client = build()

    response = client.post("/papers", content=b"x" * 5000)

    assert response.status_code == 413
    assert response.json() == {"detail": "The file is larger than the limit"}
    assert app.state.reads == 0


def test_a_streamed_body_without_a_content_length_is_cut_off_too():
    app, client = build()

    def chunks():
        for _ in range(10):
            yield b"x" * 500

    response = client.post("/papers", content=chunks())      # chunked: no Content-Length header

    assert response.status_code == 413
    assert app.state.reads == 0


@pytest.mark.parametrize("method, path", [("POST", "/other"), ("GET", "/papers")])
def test_other_requests_are_not_limited(method, path):
    app, client = build()

    response = client.request(method, path, content=b"x" * 5000)

    assert response.status_code != 413

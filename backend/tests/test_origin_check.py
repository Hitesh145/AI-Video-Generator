from fastapi import FastAPI
from fastapi.testclient import TestClient

from accounts.origin import add_origin_check

ALLOWED = ["http://localhost:5173", "http://127.0.0.1:5173"]


def build():
    app = FastAPI()
    add_origin_check(app, ALLOWED)

    @app.post("/change")
    def change():
        return {"ok": True}

    @app.get("/read")
    def read():
        return {"ok": True}

    return TestClient(app)


def test_post_from_the_app_origin_is_allowed():
    assert build().post("/change", headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_post_without_an_origin_header_is_allowed():
    # curl, scripts and tests do not send Origin; browsers always do for cross-origin POSTs.
    assert build().post("/change").status_code == 200


def test_post_from_another_local_site_is_refused():
    response = build().post("/change", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Untrusted origin"}


def test_post_from_an_opaque_origin_is_refused():
    assert build().post("/change", headers={"Origin": "null"}).status_code == 403


def test_reads_are_not_affected():
    assert build().get("/read", headers={"Origin": "http://localhost:3000"}).status_code == 200

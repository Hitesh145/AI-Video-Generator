import pytest
from accounts_helpers import make_session_factory
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import accounts.passwords
from accounts.rate_limit import LoginRateLimiter
from accounts.router import SESSION_COOKIE, create_auth_router, create_current_user_dependency
from accounts.service import AccountService, UserInfo

GOOD = {"email": "a@x.com", "password": "password1"}


@pytest.fixture(autouse=True)
def cheap_hashing(monkeypatch):
    monkeypatch.setattr(accounts.passwords, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


def build(cookie_secure=False):
    service = AccountService(make_session_factory(), LoginRateLimiter())
    app = FastAPI()
    app.include_router(create_auth_router(service, cookie_secure=cookie_secure))
    current_user = create_current_user_dependency(service)

    @app.get("/private")
    def private(user: UserInfo = Depends(current_user)):
        return {"email": user.email}

    return TestClient(app)


def test_signup_sets_a_hardened_cookie_and_hides_secrets():
    client = build()

    response = client.post("/auth/signup", json=GOOD)

    assert response.status_code == 201
    assert set(response.json()) == {"user_id", "email"}
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "max-age=1209600" in cookie
    assert "secure" not in cookie


def test_cookie_is_secure_when_configured():
    response = build(cookie_secure=True).post("/auth/signup", json=GOOD)

    assert "; secure" in response.headers["set-cookie"].lower()


def test_me_requires_a_valid_session():
    client = build()
    assert client.get("/auth/me").status_code == 401

    client.cookies.set(SESSION_COOKIE, "garbage")
    assert client.get("/auth/me").status_code == 401


def test_me_returns_the_logged_in_user():
    client = build()
    client.post("/auth/signup", json=GOOD)

    response = client.get("/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == "a@x.com"


def test_login_failures_are_identical_for_wrong_password_and_unknown_email():
    client = build()
    client.post("/auth/signup", json=GOOD)
    client.cookies.clear()

    wrong = client.post("/auth/login", json={"email": "a@x.com", "password": "bad-password"})
    unknown = client.post("/auth/login", json={"email": "nobody@x.com", "password": "password1"})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid email or password"}


def test_login_with_the_right_password_sets_a_session():
    client = build()
    client.post("/auth/signup", json=GOOD)
    client.cookies.clear()

    response = client.post("/auth/login", json=GOOD)

    assert response.status_code == 200
    assert client.get("/auth/me").status_code == 200


def test_sixth_attempt_is_rate_limited_with_retry_after():
    client = build()
    client.post("/auth/signup", json=GOOD)
    client.cookies.clear()
    for _ in range(5):
        client.post("/auth/login", json={"email": "a@x.com", "password": "bad-password"})

    response = client.post("/auth/login", json=GOOD)

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_logout_clears_the_cookie_and_kills_the_session_on_the_server():
    client = build()
    client.post("/auth/signup", json=GOOD)
    old_cookie = client.cookies.get(SESSION_COOKIE)

    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert client.get("/auth/me").status_code == 401
    client.cookies.set(SESSION_COOKIE, old_cookie)         # a stolen copy of the old cookie
    assert client.get("/auth/me").status_code == 401


def test_duplicate_signup_is_409_and_bad_input_is_422():
    client = build()
    client.post("/auth/signup", json=GOOD)

    duplicate = client.post("/auth/signup", json={"email": "A@X.com", "password": "password2"})
    bad_email = client.post("/auth/signup", json={"email": "nope", "password": "password1"})
    short_password = client.post("/auth/signup", json={"email": "b@x.com", "password": "short"})

    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "An account with this email already exists"}
    assert bad_email.status_code == 422
    assert short_password.status_code == 422


def test_protected_route_is_401_without_login_and_200_with_it():
    client = build()

    denied = client.get("/private")
    assert denied.status_code == 401
    assert denied.json() == {"detail": "Not logged in"}

    client.post("/auth/signup", json=GOOD)
    assert client.get("/private").json() == {"email": "a@x.com"}

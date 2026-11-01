import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from accounts_helpers import make_session_factory
from argon2 import PasswordHasher
from sqlalchemy import select

import accounts.passwords
import accounts.service
from accounts.models import AuthSession
from accounts.rate_limit import LoginRateLimiter
from accounts.service import (
    SESSION_TTL,
    AccountService,
    EmailTaken,
    InvalidLogin,
    InvalidSignup,
    TooManyAttempts,
)


class LimiterClock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def cheap_hashing(monkeypatch):
    # Real Argon2 settings are deliberately slow; unit tests do not need that cost.
    monkeypatch.setattr(accounts.passwords, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))


@pytest.fixture
def env():
    class Env:
        pass

    e = Env()
    e.factory = make_session_factory()
    e.limiter_clock = LimiterClock()
    e.now = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
    e.limiter = LoginRateLimiter(clock=e.limiter_clock)
    e.service = AccountService(e.factory, e.limiter, now=lambda: e.now)
    return e


def test_signup_returns_a_working_token_and_stores_only_its_hash(env):
    user, token = env.service.signup("Alice@Example.com", "correct horse")

    assert user.email == "alice@example.com"
    assert env.service.user_for_token(token) == user
    with env.factory() as session:
        stored = session.scalars(select(AuthSession)).one().token_hash
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored


def test_duplicate_email_differing_in_case_or_spaces_is_rejected(env):
    env.service.signup("alice@example.com", "password1")

    with pytest.raises(EmailTaken):
        env.service.signup("  Alice@Example.COM ", "password2")


@pytest.mark.parametrize("email, password", [
    ("nope", "password1"),
    ("a@b", "password1"),
    ("a@b.co", "short"),
    ("a@b.co", "x" * 129),
    ("a" * 250 + "@b.co", "password1"),
])
def test_invalid_signup_input_is_rejected(env, email, password):
    with pytest.raises(InvalidSignup):
        env.service.signup(email, password)


def test_login_with_the_right_password_works(env):
    user, _ = env.service.signup("alice@example.com", "password1")

    logged_in, token = env.service.login("Alice@example.com ", "password1", "1.1.1.1")

    assert logged_in == user
    assert env.service.user_for_token(token) == user


def test_wrong_password_and_unknown_email_are_the_same_error(env):
    env.service.signup("alice@example.com", "password1")

    with pytest.raises(InvalidLogin) as wrong_password:
        env.service.login("alice@example.com", "bad-password", "1.1.1.1")
    with pytest.raises(InvalidLogin) as unknown_email:
        env.service.login("nobody@example.com", "password1", "1.1.1.1")

    assert str(wrong_password.value) == str(unknown_email.value) == "Invalid email or password"


def test_unknown_email_still_verifies_a_password_hash(env, monkeypatch):
    calls = []
    original = accounts.service.verify_password
    monkeypatch.setattr(accounts.service, "verify_password",
                        lambda password, stored: calls.append(1) or original(password, stored))

    with pytest.raises(InvalidLogin):
        env.service.login("nobody@example.com", "password1", "1.1.1.1")

    assert len(calls) == 1


def test_five_failures_lock_out_even_the_right_password_until_the_window_passes(env):
    env.service.signup("alice@example.com", "password1")
    for _ in range(5):
        with pytest.raises(InvalidLogin):
            env.service.login("alice@example.com", "bad-password", "1.1.1.1")

    with pytest.raises(TooManyAttempts) as locked:
        env.service.login("alice@example.com", "password1", "1.1.1.1")
    assert locked.value.retry_after > 0

    env.limiter_clock.now += 901
    user, _ = env.service.login("alice@example.com", "password1", "1.1.1.1")
    assert user.email == "alice@example.com"


def test_failures_from_another_ip_do_not_count(env):
    env.service.signup("alice@example.com", "password1")
    for _ in range(5):
        with pytest.raises(InvalidLogin):
            env.service.login("alice@example.com", "bad-password", "1.1.1.1")

    user, _ = env.service.login("alice@example.com", "password1", "2.2.2.2")
    assert user.email == "alice@example.com"
    with pytest.raises(TooManyAttempts):
        env.service.login("alice@example.com", "password1", "1.1.1.1")


def test_expired_revoked_garbage_and_empty_tokens_resolve_to_none(env):
    _, expiring = env.service.signup("alice@example.com", "password1")
    _, revoked = env.service.login("alice@example.com", "password1", "1.1.1.1")
    env.service.logout(revoked)

    assert env.service.user_for_token(revoked) is None
    assert env.service.user_for_token("garbage") is None
    assert env.service.user_for_token("") is None

    env.now += SESSION_TTL + timedelta(seconds=1)
    assert env.service.user_for_token(expiring) is None


def test_logout_of_an_unknown_token_is_harmless(env):
    env.service.logout("never-issued")   # no exception


def test_find_user_is_case_insensitive_and_none_when_missing(env):
    user, _ = env.service.signup("alice@example.com", "password1")

    assert env.service.find_user(" ALICE@example.com") == user
    assert env.service.find_user("bob@example.com") is None

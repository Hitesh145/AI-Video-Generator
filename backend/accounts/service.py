"""Accounts: signup, login with rate limiting, and server-side sessions."""

from __future__ import annotations

import functools
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from accounts.models import AuthSession, User
from accounts.passwords import hash_password, verify_password
from accounts.rate_limit import LoginRateLimiter

SESSION_TTL = timedelta(days=14)
MAX_EMAIL_LENGTH = 254
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class UserInfo:
    user_id: str
    email: str


class InvalidSignup(ValueError):
    pass


class EmailTaken(Exception):
    pass


class InvalidLogin(Exception):
    def __init__(self) -> None:
        super().__init__("Invalid email or password")


class TooManyAttempts(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Too many failed attempts; try again in {retry_after} seconds")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@functools.cache
def _dummy_hash() -> str:
    # Verified against when the email is unknown, so timing does not reveal which emails exist.
    return hash_password("not-a-real-password")


class AccountService:
    def __init__(
        self,
        session_factory: sessionmaker,
        rate_limiter: LoginRateLimiter | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._limiter = rate_limiter or LoginRateLimiter()
        self._now = now

    def signup(self, email: str, password: str) -> tuple[UserInfo, str]:
        email = normalize_email(email)
        if len(email) > MAX_EMAIL_LENGTH or not _EMAIL_PATTERN.match(email):
            raise InvalidSignup("Enter a valid email address")
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            raise InvalidSignup(
                f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters long"
            )

        user_id = str(uuid4())
        password_hash = hash_password(password)     # slow and memory-hungry: do it before opening a transaction
        try:
            with self._session_factory.begin() as session:
                session.add(User(user_id=user_id, email=email, password_hash=password_hash))
                session.flush()
                token = self._start_session(session, user_id)
        except IntegrityError as exc:
            raise EmailTaken() from exc
        return UserInfo(user_id, email), token

    def login(self, email: str, password: str, client_ip: str) -> tuple[UserInfo, str]:
        email = normalize_email(email)
        key = f"{client_ip}|{email}"
        retry = self._limiter.retry_after(key)
        if retry is not None:
            raise TooManyAttempts(retry)

        with self._session_factory() as session:
            user = session.scalar(select(User).where(User.email == email))
            found = (user.user_id, user.email, user.password_hash) if user else None

        # Verified with no database session open, so a slow hash cannot exhaust the connection pool.
        matches = verify_password(password, found[2] if found else _dummy_hash())
        if found is None or not matches:
            self._limiter.record_failure(key)
            raise InvalidLogin()
        self._limiter.reset(key)
        with self._session_factory.begin() as session:
            token = self._start_session(session, found[0])
        return UserInfo(found[0], found[1]), token

    def user_for_token(self, token: str) -> UserInfo | None:
        if not token:
            return None
        statement = (
            select(User)
            .join(AuthSession, AuthSession.user_id == User.user_id)
            .where(
                AuthSession.token_hash == _token_digest(token),
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > self._now(),
            )
        )
        with self._session_factory() as session:
            user = session.scalar(statement)
            return UserInfo(user.user_id, user.email) if user else None

    def logout(self, token: str) -> None:
        if not token:
            return
        with self._session_factory.begin() as session:
            session.execute(
                update(AuthSession)
                .where(AuthSession.token_hash == _token_digest(token), AuthSession.revoked_at.is_(None))
                .values(revoked_at=self._now())
            )

    def find_user(self, email: str) -> UserInfo | None:
        with self._session_factory() as session:
            user = session.scalar(select(User).where(User.email == normalize_email(email)))
            return UserInfo(user.user_id, user.email) if user else None

    def _start_session(self, session, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        session.add(
            AuthSession(
                session_id=str(uuid4()),
                user_id=user_id,
                token_hash=_token_digest(token),
                expires_at=self._now() + SESSION_TTL,
            )
        )
        return token

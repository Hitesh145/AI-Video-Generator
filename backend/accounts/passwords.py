"""Password hashing with Argon2id (salted; parameters are stored inside each hash)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True only for a matching password; any bad or unreadable hash is simply False."""
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, ValueError):
        return False

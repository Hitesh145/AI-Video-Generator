"""Password hashing with Argon2id (salted; parameters are stored inside each hash)."""

from __future__ import annotations

import threading

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

_hasher = PasswordHasher()

# Each Argon2 hash uses ~64 MiB; without a cap a burst of logins (or fake logins for
# unknown emails) could allocate gigabytes at once.
MAX_CONCURRENT_HASHES = 4
_slots = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)


def hash_password(password: str) -> str:
    with _slots:
        return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True only for a matching password; any bad or unreadable hash is simply False."""
    try:
        with _slots:
            return _hasher.verify(password_hash, password)
    except (Argon2Error, ValueError):
        return False

"""In-memory login attempt limiter. Resets when the server restarts."""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from typing import Callable


class LoginRateLimiter:
    def __init__(
        self,
        max_failures: int = 5,
        window_seconds: int = 900,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int | None:
        """Seconds until another attempt is allowed, or None if the key is not locked."""
        with self._lock:
            recent = self._prune(key)
            if len(recent) < self.max_failures:
                return None
            unlock_at = recent[0] + self.window_seconds
            return max(1, math.ceil(unlock_at - self._clock()))

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._prune(key).append(self._clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _prune(self, key: str) -> list[float]:
        cutoff = self._clock() - self.window_seconds
        recent = [stamp for stamp in self._failures[key] if stamp > cutoff]
        self._failures[key] = recent
        return recent

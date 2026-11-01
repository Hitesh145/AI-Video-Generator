from accounts.rate_limit import LoginRateLimiter


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(max_failures=5, window=900):
    clock = Clock()
    return LoginRateLimiter(max_failures=max_failures, window_seconds=window, clock=clock), clock


def test_the_fifth_failure_locks_the_key_and_only_then():
    limiter, _ = make()

    for _ in range(4):
        limiter.record_failure("k")
        assert limiter.retry_after("k") is None
    limiter.record_failure("k")

    retry = limiter.retry_after("k")
    assert isinstance(retry, int) and 0 < retry <= 900


def test_the_lock_expires_when_the_window_has_passed():
    limiter, clock = make()
    for _ in range(5):
        limiter.record_failure("k")

    clock.now += 901

    assert limiter.retry_after("k") is None


def test_retry_after_counts_down():
    limiter, clock = make()
    for _ in range(5):
        limiter.record_failure("k")
    first = limiter.retry_after("k")

    clock.now += 100

    assert limiter.retry_after("k") == first - 100


def test_reset_clears_the_failures():
    limiter, _ = make()
    for _ in range(5):
        limiter.record_failure("k")

    limiter.reset("k")

    assert limiter.retry_after("k") is None


def test_keys_are_independent():
    limiter, _ = make()
    for _ in range(5):
        limiter.record_failure("a")

    assert limiter.retry_after("b") is None

from accounts.passwords import hash_password, verify_password


def test_the_hash_is_not_the_password_and_is_salted():
    first = hash_password("correct horse")
    second = hash_password("correct horse")

    assert first != "correct horse"
    assert first != second


def test_the_right_password_verifies_and_a_wrong_one_does_not():
    stored = hash_password("correct horse")

    assert verify_password("correct horse", stored) is True
    assert verify_password("wrong horse", stored) is False


def test_garbage_or_empty_hashes_are_a_failed_login_not_an_error():
    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "") is False


def test_concurrent_hashing_is_bounded(monkeypatch):
    import threading
    import time

    import accounts.passwords as passwords

    state = {"now": 0, "peak": 0}
    lock = threading.Lock()

    class SlowHasher:
        def hash(self, password):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return "hash"

    monkeypatch.setattr(passwords, "_hasher", SlowHasher())
    threads = [threading.Thread(target=passwords.hash_password, args=("x",)) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert state["peak"] <= passwords.MAX_CONCURRENT_HASHES

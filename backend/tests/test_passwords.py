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

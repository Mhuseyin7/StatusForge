from app.security import hash_password, verify_password


def test_passwords_are_argon2_hashed() -> None:
    hashed = hash_password("a-long-safe-test-password")
    assert hashed.startswith("$argon2")
    assert verify_password("a-long-safe-test-password", hashed)
    assert not verify_password("incorrect-password", hashed)

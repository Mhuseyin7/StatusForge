from app.security import hash_password, verify_password
from app.services.rate_limit import login_key


def test_passwords_are_argon2_hashed() -> None:
    hashed = hash_password("a-long-safe-test-password")
    assert hashed.startswith("$argon2")
    assert verify_password("a-long-safe-test-password", hashed)
    assert not verify_password("incorrect-password", hashed)


def test_login_rate_limit_key_does_not_expose_identity() -> None:
    key = login_key("User@Example.com", "203.0.113.10")

    assert key.startswith("statusforge:login:")
    assert "User@Example.com" not in key
    assert login_key("user@example.com", "203.0.113.10") == key

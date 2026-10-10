import pytest
from pydantic import ValidationError

from app.config import Settings
from app.schemas import RefreshTokenRequest
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


def test_refresh_token_is_a_request_body_field() -> None:
    token = "a" * 48

    assert RefreshTokenRequest(refresh_token=token).refresh_token == token


def test_cors_wildcard_is_rejected_when_credentials_are_enabled() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS cannot contain"):
        Settings(
            database_url="postgresql+psycopg://user:password@localhost:5432/statusforge",
            redis_url="redis://localhost:6379/0",
            secret_key="test-secret-key-that-is-long-enough-for-validation",
            cors_origins="*",
        )

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings

hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "typ": "access", "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    if payload.get("typ") != "access" or not payload.get("sub"):
        raise jwt.InvalidTokenError("unexpected token")
    return str(payload["sub"])


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_api_key() -> tuple[str, str, str]:
    secret = secrets.token_urlsafe(32)
    value = f"sf_{secret}"
    return value, value[:11], token_hash(value)

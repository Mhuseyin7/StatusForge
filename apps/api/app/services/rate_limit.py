import hashlib

from fastapi import HTTPException, status
from redis import Redis
from redis.exceptions import RedisError

from app.config import get_settings

MAX_LOGIN_ATTEMPTS = 5
WINDOW_SECONDS = 900


def login_key(email: str, ip_address: str) -> str:
    digest = hashlib.sha256(f"{email.lower()}:{ip_address}".encode()).hexdigest()
    return f"statusforge:login:{digest}"


def _client() -> Redis:
    return Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1)


def ensure_login_allowed(email: str, ip_address: str) -> None:
    try:
        if int(_client().get(login_key(email, ip_address)) or 0) >= MAX_LOGIN_ATTEMPTS:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts. Try again later.")
    except RedisError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Authentication service temporarily unavailable") from None


def record_login_failure(email: str, ip_address: str) -> None:
    try:
        key = login_key(email, ip_address)
        pipeline = _client().pipeline()
        pipeline.incr(key)
        pipeline.expire(key, WINDOW_SECONDS)
        pipeline.execute()
    except RedisError:
        return


def clear_login_failures(email: str, ip_address: str) -> None:
    try:
        _client().delete(login_key(email, ip_address))
    except RedisError:
        return

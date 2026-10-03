from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    try:
        Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1).ping()
    except RedisError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis is unavailable") from None
    return {"status": "ready"}


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def metrics(db: Session = Depends(get_db)) -> str:
    monitor_count = db.execute(text("SELECT count(*) FROM monitors")).scalar_one()
    down_count = db.execute(text("SELECT count(*) FROM monitors WHERE status = 'DOWN'")).scalar_one()
    return f"# HELP statusforge_monitors_total Number of configured monitors\n# TYPE statusforge_monitors_total gauge\nstatusforge_monitors_total {monitor_count}\n# HELP statusforge_monitors_down Number of monitors currently down\n# TYPE statusforge_monitors_down gauge\nstatusforge_monitors_down {down_count}\n"

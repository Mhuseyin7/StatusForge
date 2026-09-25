import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user, membership_for
from app.models import Monitor, MonitorCheck, MonitorStatus, MonitorType, Role, User, utcnow
from app.schemas import CheckResponse, HeartbeatResponse, MonitorCreate, MonitorResponse
from app.services.audit import record
from app.worker.tasks import enqueue_monitor

router = APIRouter(prefix="/organizations/{organization_id}/monitors", tags=["monitors"])


def require_editor(organization_id: uuid.UUID, user: User, db: Session):
    membership = membership_for(organization_id, user, db)
    if membership.role in {Role.VIEWER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Editor role required")
    return membership


@router.get("", response_model=list[MonitorResponse])
def list_monitors(organization_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Monitor]:
    membership_for(organization_id, user, db)
    return list(db.scalars(select(Monitor).where(Monitor.organization_id == organization_id).order_by(Monitor.created_at.desc())))


@router.post("", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
def create_monitor(organization_id: uuid.UUID, payload: MonitorCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Monitor:
    require_editor(organization_id, user, db)
    if db.scalar(select(Monitor.id).where(Monitor.organization_id == organization_id, Monitor.slug == payload.slug)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Monitor slug already exists")
    if payload.type in {MonitorType.HTTP, MonitorType.KEYWORD, MonitorType.JSON} and not payload.config.get("url"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="HTTP-style monitors require config.url")
    monitor = Monitor(organization_id=organization_id, **payload.model_dump())
    if monitor.type == MonitorType.HEARTBEAT:
        monitor.heartbeat_token = secrets.token_urlsafe(32)
    db.add(monitor)
    db.flush()
    record(db, organization_id, user.id, "monitor.created", f"monitor:{monitor.id}", metadata={"type": monitor.type.value})
    db.commit()
    db.refresh(monitor)
    return monitor


@router.post("/{monitor_id}/check", status_code=status.HTTP_202_ACCEPTED)
def check_now(organization_id: uuid.UUID, monitor_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    require_editor(organization_id, user, db)
    monitor = db.scalar(select(Monitor).where(Monitor.id == monitor_id, Monitor.organization_id == organization_id))
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    enqueue_monitor.delay(str(monitor.id))
    return {"status": "queued"}


@router.get("/{monitor_id}/checks", response_model=list[CheckResponse])
def list_checks(organization_id: uuid.UUID, monitor_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[MonitorCheck]:
    membership_for(organization_id, user, db)
    monitor = db.scalar(select(Monitor.id).where(Monitor.id == monitor_id, Monitor.organization_id == organization_id))
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    return list(db.scalars(select(MonitorCheck).where(MonitorCheck.monitor_id == monitor_id).order_by(MonitorCheck.checked_at.desc()).limit(100)))


@router.post("/heartbeat/{token}", response_model=HeartbeatResponse)
def heartbeat(organization_id: uuid.UUID, token: str, db: Session = Depends(get_db)) -> HeartbeatResponse:
    monitor = db.scalar(select(Monitor).where(Monitor.organization_id == organization_id, Monitor.heartbeat_token == token, Monitor.type == MonitorType.HEARTBEAT))
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Heartbeat not found")
    monitor.last_checked_at = utcnow()
    monitor.status = MonitorStatus.UP
    monitor.failure_count = 0
    db.add(MonitorCheck(monitor_id=monitor.id, status=MonitorStatus.UP, response_time_ms=0, metadata_={"source": "heartbeat"}))
    db.commit()
    return HeartbeatResponse(accepted=True)

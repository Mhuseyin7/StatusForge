import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user, membership_for
from app.models import (
    Incident,
    IncidentStatus,
    Monitor,
    MonitorCheck,
    MonitorStatus,
    Organization,
    OrganizationMember,
    Role,
    User,
)
from app.schemas import MembershipResponse, OrganizationCreate, OrganizationResponse
from app.services.audit import record

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationResponse])
def list_organizations(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Organization]:
    return list(db.scalars(select(Organization).join(OrganizationMember).where(OrganizationMember.user_id == user.id).order_by(Organization.name)))


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
def create_organization(payload: OrganizationCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Organization:
    if db.scalar(select(Organization.id).where(Organization.slug == payload.slug)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Organization slug already exists")
    organization = Organization(**payload.model_dump())
    db.add(organization)
    db.flush()
    db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role=Role.OWNER))
    record(db, organization.id, user.id, "organization.created", f"organization:{organization.id}")
    db.commit()
    db.refresh(organization)
    return organization


@router.get("/{organization_id}/members", response_model=list[MembershipResponse])
def list_members(organization_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[OrganizationMember]:
    membership_for(organization_id, user, db)
    return list(db.scalars(select(OrganizationMember).where(OrganizationMember.organization_id == organization_id)))


@router.get("/{organization_id}/dashboard")
def dashboard(organization_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    membership_for(organization_id, user, db)
    monitors = db.scalars(select(Monitor).where(Monitor.organization_id == organization_id).order_by(Monitor.updated_at.desc())).all()
    monitor_ids = [monitor.id for monitor in monitors]
    active_incidents = db.scalar(select(func.count()).select_from(Incident).where(Incident.organization_id == organization_id, Incident.status != IncidentStatus.RESOLVED)) or 0
    checks = db.scalars(select(MonitorCheck).where(MonitorCheck.monitor_id.in_(monitor_ids)).order_by(MonitorCheck.checked_at.desc()).limit(500)).all() if monitor_ids else []
    successful = [check for check in checks if check.status == MonitorStatus.UP]
    response_times = [check.response_time_ms for check in successful if check.response_time_ms is not None]
    return {
        "summary": {
            "total_monitors": len(monitors),
            "monitors_up": sum(monitor.status == MonitorStatus.UP for monitor in monitors),
            "monitors_down": sum(monitor.status == MonitorStatus.DOWN for monitor in monitors),
            "active_incidents": active_incidents,
            "uptime_percentage": round((len(successful) / len(checks) * 100) if checks else 0, 2),
            "average_response_time_ms": round(sum(response_times) / len(response_times)) if response_times else None,
        },
        "monitors": [{"id": monitor.id, "name": monitor.name, "type": monitor.type.value, "status": monitor.status.value, "last_checked_at": monitor.last_checked_at} for monitor in monitors],
        "recent_checks": [{"monitor_id": check.monitor_id, "checked_at": check.checked_at, "response_time_ms": check.response_time_ms, "status": check.status.value} for check in checks[:100]],
    }

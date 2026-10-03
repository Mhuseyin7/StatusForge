import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user, membership_for
from app.models import Incident, IncidentStatus, IncidentUpdate, Monitor, Role, User, utcnow
from app.schemas import IncidentCreate, IncidentResponse, IncidentUpdateCreate
from app.services.audit import record

router = APIRouter(prefix="/organizations/{organization_id}/incidents", tags=["incidents"])


def require_incident_editor(organization_id: uuid.UUID, user: User, db: Session) -> None:
    membership = membership_for(organization_id, user, db)
    if membership.role == Role.VIEWER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Editor role required")


@router.get("", response_model=list[IncidentResponse])
def list_incidents(organization_id: uuid.UUID, include_resolved: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Incident]:
    membership_for(organization_id, user, db)
    query = select(Incident).where(Incident.organization_id == organization_id)
    if not include_resolved:
        query = query.where(Incident.status != IncidentStatus.RESOLVED)
    return list(db.scalars(query.order_by(Incident.started_at.desc()).limit(100)))


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def create_incident(organization_id: uuid.UUID, payload: IncidentCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Incident:
    require_incident_editor(organization_id, user, db)
    if payload.monitor_id and not db.scalar(select(Monitor.id).where(Monitor.id == payload.monitor_id, Monitor.organization_id == organization_id)):
        raise HTTPException(status_code=422, detail="Monitor not found")
    incident = Incident(organization_id=organization_id, monitor_id=payload.monitor_id, title=payload.title, severity=payload.severity)
    db.add(incident)
    db.flush()
    db.add(IncidentUpdate(incident_id=incident.id, author_id=user.id, message=payload.message, status=incident.status))
    record(db, organization_id, user.id, "incident.created", f"incident:{incident.id}")
    db.commit()
    db.refresh(incident)
    return incident


@router.post("/{incident_id}/updates", response_model=IncidentResponse)
def add_update(organization_id: uuid.UUID, incident_id: uuid.UUID, payload: IncidentUpdateCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Incident:
    require_incident_editor(organization_id, user, db)
    incident = db.scalar(select(Incident).where(Incident.id == incident_id, Incident.organization_id == organization_id))
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident.status = payload.status
    if payload.status == IncidentStatus.RESOLVED:
        incident.resolved_at = utcnow()
    elif incident.resolved_at:
        incident.resolved_at = None
    db.add(IncidentUpdate(incident_id=incident.id, author_id=user.id, message=payload.message, status=payload.status))
    record(db, organization_id, user.id, "incident.updated", f"incident:{incident.id}", metadata={"status": payload.status.value})
    db.commit()
    db.refresh(incident)
    return incident

import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog


def record(db: Session, organization_id: uuid.UUID, actor_id: uuid.UUID | None, action: str, resource: str, ip_address: str | None = None, user_agent: str | None = None, metadata: dict | None = None) -> None:
    db.add(AuditLog(organization_id=organization_id, actor_id=actor_id, action=action, resource=resource, ip_address=ip_address, user_agent=user_agent, metadata_=metadata or {}))

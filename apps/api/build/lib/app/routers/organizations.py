import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user, membership_for
from app.models import Organization, OrganizationMember, Role, User
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

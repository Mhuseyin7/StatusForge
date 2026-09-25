import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user, membership_for
from app.models import ApiKey, Role, User
from app.routers.monitors import require_editor
from app.schemas import ApiKeyCreate, ApiKeyCreated
from app.security import new_api_key
from app.services.audit import record

router = APIRouter(prefix="/organizations/{organization_id}/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(organization_id: uuid.UUID, payload: ApiKeyCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> ApiKeyCreated:
    require_editor(organization_id, user, db)
    value, prefix, key_hash = new_api_key()
    api_key = ApiKey(organization_id=organization_id, name=payload.name, prefix=prefix, key_hash=key_hash, scopes=payload.scopes)
    db.add(api_key)
    db.flush()
    record(db, organization_id, user.id, "api_key.created", f"api_key:{api_key.id}", metadata={"scopes": payload.scopes})
    db.commit()
    return ApiKeyCreated(id=api_key.id, key=value, prefix=prefix, scopes=payload.scopes)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(organization_id: uuid.UUID, key_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    membership = membership_for(organization_id, user, db)
    if membership.role in {Role.VIEWER, Role.MEMBER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator role required")
    api_key = db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.organization_id == organization_id))
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    db.delete(api_key)
    record(db, organization_id, user.id, "api_key.deleted", f"api_key:{key_id}")
    db.commit()

import uuid

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import OrganizationMember, User
from app.security import decode_access_token


def current_user(authorization: str = Header(), db: Session = Depends(get_db)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        user_id = uuid.UUID(decode_access_token(authorization.removeprefix("Bearer ")))
    except (ValueError, jwt.PyJWTError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    return user


def membership_for(organization_id: uuid.UUID, user: User, db: Session) -> OrganizationMember:
    membership = db.scalar(select(OrganizationMember).where(OrganizationMember.organization_id == organization_id, OrganizationMember.user_id == user.id))
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return membership

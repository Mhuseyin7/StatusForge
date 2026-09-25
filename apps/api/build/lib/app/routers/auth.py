import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import current_user
from app.models import Organization, OrganizationMember, Role, SessionToken, User
from app.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.security import (
    create_access_token,
    hash_password,
    new_refresh_token,
    token_hash,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def issue_tokens(db: Session, user: User, request: Request) -> TokenResponse:
    refresh = new_refresh_token()
    settings = get_settings()
    db.add(SessionToken(user_id=user.id, token_hash=token_hash(refresh), expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days), user_agent=request.headers.get("user-agent", "")[:512], ip_address=request.client.host if request.client else None))
    return TokenResponse(access_token=create_access_token(str(user.id)), refresh_token=refresh)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    email = str(payload.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    base_slug = "-".join(payload.organization_name.lower().split())
    slug = "".join(char for char in base_slug if char.isalnum() or char == "-")[:80] or "workspace"
    if db.scalar(select(Organization.id).where(Organization.slug == slug)):
        slug = f"{slug[:70]}-{uuid.uuid4().hex[:8]}"
    user = User(email=email, password_hash=hash_password(payload.password))
    organization = Organization(name=payload.organization_name, slug=slug)
    db.add_all([user, organization])
    db.flush()
    db.add(OrganizationMember(user_id=user.id, organization_id=organization.id, role=Role.OWNER))
    tokens = issue_tokens(db, user, request)
    db.commit()
    return tokens


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    tokens = issue_tokens(db, user, request)
    db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
def refresh(refresh_token: str, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == token_hash(refresh_token), SessionToken.revoked_at.is_(None)))
    if session is None or session.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account unavailable")
    session.revoked_at = datetime.now(UTC)
    tokens = issue_tokens(db, user, request)
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(refresh_token: str, db: Session = Depends(get_db)) -> Response:
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == token_hash(refresh_token), SessionToken.revoked_at.is_(None)))
    if session:
        session.revoked_at = datetime.now(UTC)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(current_user)) -> User:
    return user

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import current_user
from app.models import (
    AuthActionToken,
    Organization,
    OrganizationMember,
    Role,
    SessionToken,
    User,
    utcnow,
)
from app.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    TokenResponse,
    UserResponse,
)
from app.security import (
    create_access_token,
    hash_password,
    new_refresh_token,
    token_hash,
    verify_password,
)
from app.services.mailer import send_message
from app.services.rate_limit import clear_login_failures, ensure_login_allowed, record_login_failure

router = APIRouter(prefix="/auth", tags=["auth"])


def issue_tokens(db: Session, user: User, request: Request) -> TokenResponse:
    refresh = new_refresh_token()
    settings = get_settings()
    db.add(SessionToken(user_id=user.id, token_hash=token_hash(refresh), expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days), user_agent=request.headers.get("user-agent", "")[:512], ip_address=request.client.host if request.client else None))
    return TokenResponse(access_token=create_access_token(str(user.id)), refresh_token=refresh)


def create_action_token(db: Session, user: User, purpose: str) -> str:
    token = secrets.token_urlsafe(48)
    db.add(AuthActionToken(user_id=user.id, purpose=purpose, token_hash=token_hash(token), expires_at=datetime.now(UTC) + timedelta(hours=24)))
    return token


def deliver_action_email(user: User, purpose: str, token: str) -> None:
    settings = get_settings()
    path = "verify-email" if purpose == "verify_email" else "reset-password"
    send_message(user.email, "StatusForge account action", f"Open {settings.app_url}/{path}?token={token} to complete your request. This link expires in 24 hours.")


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
    verification_token = create_action_token(db, user, "verify_email")
    deliver_action_email(user, "verify_email", verification_token)
    tokens = issue_tokens(db, user, request)
    db.commit()
    return tokens


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    email = str(payload.email).lower()
    ip_address = request.client.host if request.client else "unknown"
    ensure_login_allowed(email, ip_address)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        record_login_failure(email, ip_address)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    tokens = issue_tokens(db, user, request)
    db.commit()
    clear_login_failures(email, ip_address)
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


@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    action = db.scalar(select(AuthActionToken).where(AuthActionToken.token_hash == token_hash(token), AuthActionToken.purpose == "verify_email", AuthActionToken.used_at.is_(None), AuthActionToken.expires_at > datetime.now(UTC)))
    if action is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")
    user = db.get(User, action.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification token")
    user.is_verified = True
    action.used_at = utcnow()
    db.commit()
    return {"verified": True}


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict[str, bool]:
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user and user.is_active:
        token = create_action_token(db, user, "reset_password")
        deliver_action_email(user, "reset_password", token)
        db.commit()
    return {"accepted": True}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> Response:
    action = db.scalar(select(AuthActionToken).where(AuthActionToken.token_hash == token_hash(payload.token), AuthActionToken.purpose == "reset_password", AuthActionToken.used_at.is_(None), AuthActionToken.expires_at > datetime.now(UTC)))
    if action is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")
    user = db.get(User, action.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")
    user.password_hash = hash_password(payload.password)
    action.used_at = utcnow()
    for session in db.scalars(select(SessionToken).where(SessionToken.user_id == user.id, SessionToken.revoked_at.is_(None))):
        session.revoked_at = utcnow()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[SessionToken]:
    now = datetime.now(UTC)
    return list(db.scalars(select(SessionToken).where(SessionToken.user_id == user.id, SessionToken.revoked_at.is_(None), SessionToken.expires_at > now).order_by(SessionToken.created_at.desc())))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(session_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    session = db.scalar(select(SessionToken).where(SessionToken.id == session_id, SessionToken.user_id == user.id, SessionToken.revoked_at.is_(None)))
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    session.revoked_at = datetime.now(UTC)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

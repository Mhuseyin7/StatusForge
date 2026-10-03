import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import current_user, membership_for
from app.models import (
    Incident,
    MaintenanceWindow,
    Monitor,
    NotificationProvider,
    NotificationProviderType,
    NotificationRule,
    StatusPage,
    StatusPageComponent,
    User,
    Webhook,
)
from app.routers.monitors import require_editor
from app.schemas import (
    MaintenanceCreate,
    MaintenanceResponse,
    NotificationProviderCreate,
    NotificationRuleCreate,
    StatusPageComponentCreate,
    StatusPageCreate,
    StatusPageResponse,
    WebhookCreate,
    WebhookCreated,
)
from app.services.audit import record
from app.services.monitoring import UnsafeTargetError, validate_url

router = APIRouter(prefix="/organizations/{organization_id}", tags=["operations"])
public_router = APIRouter(prefix="/status", tags=["public-status"])


@router.get("/maintenance", response_model=list[MaintenanceResponse])
def list_maintenance(organization_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[MaintenanceWindow]:
    membership_for(organization_id, user, db)
    return list(db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.organization_id == organization_id).order_by(MaintenanceWindow.starts_at.desc())))


@router.post("/maintenance", response_model=MaintenanceResponse, status_code=status.HTTP_201_CREATED)
def create_maintenance(organization_id: uuid.UUID, payload: MaintenanceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> MaintenanceWindow:
    require_editor(organization_id, user, db)
    monitor_ids = [str(value) for value in payload.affected_monitor_ids]
    if monitor_ids:
        found = db.scalars(select(Monitor.id).where(Monitor.organization_id == organization_id, Monitor.id.in_(payload.affected_monitor_ids))).all()
        if len(found) != len(monitor_ids):
            raise HTTPException(status_code=422, detail="All affected monitors must belong to the organization")
    window = MaintenanceWindow(organization_id=organization_id, **payload.model_dump(mode="json"))
    db.add(window)
    db.flush()
    record(db, organization_id, user.id, "maintenance.created", f"maintenance:{window.id}")
    db.commit()
    db.refresh(window)
    return window


@router.get("/status-pages", response_model=list[StatusPageResponse])
def list_status_pages(organization_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[StatusPage]:
    membership_for(organization_id, user, db)
    return list(db.scalars(select(StatusPage).where(StatusPage.organization_id == organization_id).order_by(StatusPage.name)))


@router.post("/status-pages", response_model=StatusPageResponse, status_code=status.HTTP_201_CREATED)
def create_status_page(organization_id: uuid.UUID, payload: StatusPageCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> StatusPage:
    require_editor(organization_id, user, db)
    if db.scalar(select(StatusPage.id).where(StatusPage.slug == payload.slug)):
        raise HTTPException(status_code=409, detail="Status page slug already exists")
    page = StatusPage(organization_id=organization_id, **payload.model_dump())
    db.add(page)
    db.flush()
    record(db, organization_id, user.id, "status_page.created", f"status_page:{page.id}")
    db.commit()
    db.refresh(page)
    return page


@router.post("/status-pages/{page_id}/components", status_code=status.HTTP_201_CREATED)
def add_component(organization_id: uuid.UUID, page_id: uuid.UUID, payload: StatusPageComponentCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_editor(organization_id, user, db)
    page = db.scalar(select(StatusPage).where(StatusPage.id == page_id, StatusPage.organization_id == organization_id))
    if page is None:
        raise HTTPException(status_code=404, detail="Status page not found")
    if payload.monitor_id and not db.scalar(select(Monitor.id).where(Monitor.id == payload.monitor_id, Monitor.organization_id == organization_id)):
        raise HTTPException(status_code=422, detail="Monitor not found")
    component = StatusPageComponent(status_page_id=page.id, **payload.model_dump())
    db.add(component)
    db.commit()
    return {"id": str(component.id)}


@router.post("/notification-providers", status_code=status.HTTP_201_CREATED)
def create_provider(organization_id: uuid.UUID, payload: NotificationProviderCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_editor(organization_id, user, db)
    if payload.type in {NotificationProviderType.WEBHOOK, NotificationProviderType.DISCORD}:
        url = str(payload.config.get("url", ""))
        try:
            validate_url(url)
        except UnsafeTargetError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.type == NotificationProviderType.TELEGRAM and not {"bot_token", "chat_id"}.issubset(payload.config):
        raise HTTPException(status_code=422, detail="Telegram providers require bot_token and chat_id")
    provider = NotificationProvider(organization_id=organization_id, **payload.model_dump())
    db.add(provider)
    db.flush()
    record(db, organization_id, user.id, "notification_provider.created", f"provider:{provider.id}")
    db.commit()
    return {"id": str(provider.id)}


@router.post("/notification-rules", status_code=status.HTTP_201_CREATED)
def create_notification_rule(organization_id: uuid.UUID, payload: NotificationRuleCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    require_editor(organization_id, user, db)
    provider = db.scalar(select(NotificationProvider).where(NotificationProvider.id == payload.provider_id, NotificationProvider.organization_id == organization_id))
    if provider is None:
        raise HTTPException(status_code=422, detail="Notification provider not found")
    monitor_ids = [str(value) for value in payload.monitor_ids]
    if monitor_ids:
        owned_monitors = db.scalars(select(Monitor.id).where(Monitor.organization_id == organization_id, Monitor.id.in_(payload.monitor_ids))).all()
        if len(owned_monitors) != len(monitor_ids):
            raise HTTPException(status_code=422, detail="All monitors must belong to the organization")
    rule = NotificationRule(organization_id=organization_id, provider_id=provider.id, events=payload.events, monitor_ids=monitor_ids, delay_seconds=payload.delay_seconds)
    db.add(rule)
    db.flush()
    record(db, organization_id, user.id, "notification_rule.created", f"notification_rule:{rule.id}")
    db.commit()
    return {"id": str(rule.id)}


@router.post("/webhooks", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
def create_webhook(organization_id: uuid.UUID, payload: WebhookCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> WebhookCreated:
    require_editor(organization_id, user, db)
    try:
        validate_url(payload.url)
    except UnsafeTargetError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    secret = secrets.token_urlsafe(32)
    webhook = Webhook(organization_id=organization_id, url=payload.url, secret=secret, events=payload.events)
    db.add(webhook)
    db.flush()
    record(db, organization_id, user.id, "webhook.created", f"webhook:{webhook.id}")
    db.commit()
    return WebhookCreated(id=webhook.id, secret=secret)


@public_router.get("/{slug}")
def public_status(slug: str, db: Session = Depends(get_db)) -> dict:
    page = db.scalar(select(StatusPage).where(StatusPage.slug == slug, StatusPage.is_published.is_(True)))
    if page is None:
        raise HTTPException(status_code=404, detail="Status page not found")
    components = db.scalars(select(StatusPageComponent).where(StatusPageComponent.status_page_id == page.id).order_by(StatusPageComponent.position)).all()
    monitor_ids = [component.monitor_id for component in components if component.monitor_id]
    monitors = {monitor.id: monitor for monitor in db.scalars(select(Monitor).where(Monitor.id.in_(monitor_ids))).all()} if monitor_ids else {}
    incidents = db.scalars(select(Incident).where(Incident.organization_id == page.organization_id, Incident.resolved_at.is_(None)).order_by(Incident.started_at.desc()).limit(10)).all()
    return {
        "name": page.name,
        "description": page.description,
        "theme": page.theme,
        "overall_status": "DOWN" if any(monitor.status.value == "DOWN" for monitor in monitors.values()) else "UP",
        "components": [{"name": component.name, "status": monitors[component.monitor_id].status.value if component.monitor_id in monitors else "UNKNOWN"} for component in components],
        "incidents": [{"title": incident.title, "status": incident.status.value, "severity": incident.severity.value, "started_at": incident.started_at} for incident in incidents],
    }

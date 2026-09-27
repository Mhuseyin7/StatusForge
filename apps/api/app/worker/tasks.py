import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import timedelta

import httpx
from celery import shared_task
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Incident,
    IncidentStatus,
    MaintenanceWindow,
    Monitor,
    MonitorCheck,
    MonitorStatus,
    Webhook,
    WebhookDelivery,
    utcnow,
)
from app.services.monitoring import CheckResult, execute
from app.worker.celery_app import celery_app


@shared_task(name="statusforge.run_monitor", bind=True, autoretry_for=(ConnectionError,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def enqueue_monitor(self, monitor_id: str) -> None:
    with SessionLocal() as db:
        monitor = db.get(Monitor, uuid.UUID(monitor_id))
        if monitor is None or not monitor.enabled:
            return
        previous_status = monitor.status
        if monitor.type.value == "HEARTBEAT":
            if monitor.last_checked_at and monitor.last_checked_at + timedelta(seconds=monitor.interval_seconds) >= utcnow():
                return
            result = CheckResult(MonitorStatus.DOWN, None, error_code="HEARTBEAT_MISSED", error_message="Expected heartbeat did not arrive")
        else:
            result = asyncio.run(execute(monitor))
        check = MonitorCheck(monitor_id=monitor.id, status=result.status, response_time_ms=result.response_time_ms, status_code=result.status_code, error_code=result.error_code, error_message=result.error_message, metadata_=result.metadata or {})
        monitor.last_checked_at = utcnow()
        if result.status == MonitorStatus.UP:
            monitor.failure_count = 0
            monitor.recovery_count += 1
            if monitor.status == MonitorStatus.DOWN and monitor.recovery_count >= monitor.retry_count:
                monitor.status = MonitorStatus.UP
                incident = db.scalar(select(Incident).where(Incident.monitor_id == monitor.id, Incident.status != IncidentStatus.RESOLVED).order_by(Incident.started_at.desc()))
                if incident:
                    incident.status = IncidentStatus.RESOLVED
                    incident.resolved_at = utcnow()
            elif monitor.status in {MonitorStatus.PENDING, MonitorStatus.UNKNOWN}:
                monitor.status = MonitorStatus.UP
        else:
            monitor.recovery_count = 0
            monitor.failure_count += 1
            if monitor.failure_count >= monitor.retry_count and monitor.status != MonitorStatus.DOWN:
                monitor.status = MonitorStatus.DOWN
                db.add(Incident(organization_id=monitor.organization_id, monitor_id=monitor.id, title=f"{monitor.name} is unavailable"))
        db.add(check)
        db.commit()
        event = None
        if previous_status != MonitorStatus.DOWN and monitor.status == MonitorStatus.DOWN:
            event = "MONITOR_DOWN"
        elif previous_status == MonitorStatus.DOWN and monitor.status == MonitorStatus.UP:
            event = "MONITOR_RECOVERED"
        if event and not is_maintenance(db, monitor):
            deliver_event.delay(str(monitor.organization_id), event, {"monitor": {"id": str(monitor.id), "name": monitor.name, "status": monitor.status.value}, "check": {"status": result.status.value, "response_time_ms": result.response_time_ms}})


def is_maintenance(db, monitor: Monitor) -> bool:
    now = utcnow()
    windows = db.scalars(select(MaintenanceWindow).where(MaintenanceWindow.organization_id == monitor.organization_id, MaintenanceWindow.starts_at <= now, MaintenanceWindow.ends_at >= now, MaintenanceWindow.suppress_notifications.is_(True))).all()
    return any(not window.affected_monitor_ids or str(monitor.id) in window.affected_monitor_ids for window in windows)


@celery_app.task(name="statusforge.deliver_event", bind=True, autoretry_for=(httpx.HTTPError,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def deliver_event(self, organization_id: str, event: str, payload: dict) -> None:
    with SessionLocal() as db:
        webhooks = db.scalars(select(Webhook).where(Webhook.organization_id == uuid.UUID(organization_id), Webhook.enabled.is_(True))).all()
        for webhook in webhooks:
            if event not in webhook.events:
                continue
            body = json.dumps({"event": event, "timestamp": utcnow().isoformat(), "organization_id": organization_id, **payload}, default=str).encode()
            signature = hmac.new(webhook.secret.encode(), body, hashlib.sha256).hexdigest()
            try:
                response = httpx.post(webhook.url, content=body, headers={"Content-Type": "application/json", "X-StatusForge-Signature": f"sha256={signature}"}, timeout=10)
                db.add(WebhookDelivery(webhook_id=webhook.id, event=event, status_code=response.status_code, error=None if response.is_success else f"HTTP {response.status_code}"))
            except httpx.HTTPError as exc:
                db.add(WebhookDelivery(webhook_id=webhook.id, event=event, error=str(exc)[:500]))
        db.commit()


@celery_app.task(name="statusforge.enqueue_due")
def enqueue_due_monitors() -> None:
    with SessionLocal() as db:
        now = utcnow()
        monitors = db.scalars(select(Monitor).where(Monitor.enabled.is_(True))).all()
        for monitor in monitors:
            if monitor.last_checked_at is None or monitor.last_checked_at + timedelta(seconds=monitor.interval_seconds) <= now:
                enqueue_monitor.delay(str(monitor.id))

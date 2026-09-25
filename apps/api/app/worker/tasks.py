import asyncio
import uuid
from datetime import timedelta

from celery import shared_task
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Incident, IncidentStatus, Monitor, MonitorCheck, MonitorStatus, utcnow
from app.services.monitoring import execute
from app.worker.celery_app import celery_app


@shared_task(name="statusforge.run_monitor", bind=True, autoretry_for=(ConnectionError,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def enqueue_monitor(self, monitor_id: str) -> None:
    with SessionLocal() as db:
        monitor = db.get(Monitor, uuid.UUID(monitor_id))
        if monitor is None or not monitor.enabled or monitor.type.value == "HEARTBEAT":
            return
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
            if monitor.failure_count >= monitor.retry_count:
                if monitor.status != MonitorStatus.DOWN:
                    monitor.status = MonitorStatus.DOWN
                    db.add(Incident(organization_id=monitor.organization_id, monitor_id=monitor.id, title=f"{monitor.name} is unavailable"))
        db.add(check)
        db.commit()


@celery_app.task(name="statusforge.enqueue_due")
def enqueue_due_monitors() -> None:
    with SessionLocal() as db:
        now = utcnow()
        monitors = db.scalars(select(Monitor).where(Monitor.enabled.is_(True))).all()
        for monitor in monitors:
            if monitor.last_checked_at is None or monitor.last_checked_at + timedelta(seconds=monitor.interval_seconds) <= now:
                enqueue_monitor.delay(str(monitor.id))

from celery import Celery

from app.config import get_settings

settings = get_settings()
celery_app = Celery("statusforge", broker=settings.redis_url, backend=settings.redis_url, include=["app.worker.tasks"])
celery_app.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, task_time_limit=150, task_soft_time_limit=130, broker_connection_retry_on_startup=True, timezone="UTC", beat_schedule={"enqueue-due-monitors": {"task": "statusforge.enqueue_due", "schedule": 30.0}})

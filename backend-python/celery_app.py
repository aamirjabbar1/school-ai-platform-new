from celery import Celery
from config.settings import REDIS_URL

celery_app = Celery(
    "school_ai",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "tasks.document_tasks",
        "tasks.student_import_tasks",
        "tasks.conversion_tasks",
        "tasks.online_class_tasks",
        "tasks.erp_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Reliability: re-queue tasks if the worker dies mid-execution
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    # Result expiry: keep task results for 1 day
    result_expires=86400,
    # Suppress CPendingDeprecationWarning in Celery 5.x / 6.x
    broker_connection_retry_on_startup=True,
    # Document conversion runs on its own queue and its own container: headless
    # LibreOffice is heavy and can hang on a malformed deck, which must never
    # hold up document ingestion or anything a live class waits on.
    task_routes={
        "tasks.conversion_tasks.*": {"queue": "conversion"},
    },
)

# ─── Scheduled work ───────────────────────────────────────────────────────────
# Run by the `celery_beat` service. Everything here is ordinary bookkeeping —
# closing abandoned classes, reminding students, expiring old recordings — and
# none of it calls an AI model.
celery_app.conf.beat_schedule = {
    # The ERP event outbox. Sixty seconds is the gap between an admission being
    # confirmed and the rest of the system acting on it, which is well inside
    # the time it takes the clerk to hand over the login slip.
    "drain-erp-events": {
        "task": "tasks.erp_tasks.drain_domain_events",
        "schedule": 60.0,
    },
    "close-abandoned-classes": {
        "task": "tasks.online_class_tasks.close_abandoned_classes",
        "schedule": 120.0,
    },
    "materialize-schedules": {
        "task": "tasks.online_class_tasks.materialize_schedules",
        "schedule": 600.0,
    },
    "class-reminders": {
        "task": "tasks.online_class_tasks.send_class_reminders",
        "schedule": 300.0,
    },
    "expire-recordings": {
        "task": "tasks.online_class_tasks.expire_recordings",
        "schedule": 3600.0,
    },
}

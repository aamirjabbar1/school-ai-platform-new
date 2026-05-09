from celery import Celery
from config.settings import REDIS_URL

celery_app = Celery(
    "school_ai",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.document_tasks"],
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
)

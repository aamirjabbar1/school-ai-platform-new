import asyncio
import os

from celery_app import celery_app


@celery_app.task(
    bind=True,
    name="tasks.student_import_tasks.process_student_import",
    acks_late=True,
)
def process_student_import_task(self, batch_id: str, file_path: str, custom_password: str | None = None):
    """Celery task: run a bulk student Excel import in the background.

    Heavy CPU work (≈1000 bcrypt password hashes) and the DB writes run here so
    the upload HTTP request returns immediately and never hits the reverse-proxy
    timeout. Errors are recorded on the StudentImportBatch row (the service never
    raises), so the task itself does not retry — a failed import is surfaced to
    the admin via the batch status.
    """
    asyncio.run(_run_import(batch_id, file_path, custom_password))


async def _run_import(batch_id: str, file_path: str, custom_password: str | None):
    """Run the import inside a fresh event loop with a dedicated engine.

    Mirrors tasks/document_tasks.py: asyncio.run() closes its loop on exit, so we
    build a per-invocation async engine rather than reusing the shared pool that
    is bound to the FastAPI process's loop.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from config.settings import DATABASE_URL
    from services.student_excel_import_service import process_student_import

    engine = create_async_engine(
        DATABASE_URL,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
        except Exception as exc:
            # Can't even read the upload — mark the batch failed directly.
            await _mark_failed(session_factory, batch_id, f"Could not read uploaded file: {exc}")
            return

        async with session_factory() as session:
            await process_student_import(batch_id, file_bytes, session, custom_password=custom_password)
        print(f"[Celery] Student import {batch_id} processed.")
    finally:
        await engine.dispose()
        # Clean up the temporary source file; the credentials file is kept.
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass


async def _mark_failed(session_factory, batch_id: str, message: str):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from models.models import StudentImportBatch

    async with session_factory() as session:
        res = await session.execute(select(StudentImportBatch).where(StudentImportBatch.id == batch_id))
        batch = res.scalar_one_or_none()
        if batch:
            batch.status = "failed"
            batch.error_message = message[:1000]
            batch.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await session.commit()

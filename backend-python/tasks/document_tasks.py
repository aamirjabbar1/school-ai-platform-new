import asyncio
from celery_app import celery_app


@celery_app.task(
    bind=True,
    name="tasks.document_tasks.ingest_document",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def ingest_document_task(self, document_id: str):
    """
    Celery task: extract text from an uploaded document, split into chunks,
    and persist them in the database for RAG search.
    Retries up to 3 times with a 60-second delay on failure.
    """
    try:
        asyncio.run(_run_ingestion(document_id))
    except Exception as exc:
        raise self.retry(exc=exc)


async def _run_ingestion(document_id: str):
    from config.database import async_session
    from services.document_service import ingest_document

    async with async_session() as session:
        result = await ingest_document(document_id, session)
        print(f"[Celery] Document {document_id} ingested — {result['chunks_created']} chunks created.")

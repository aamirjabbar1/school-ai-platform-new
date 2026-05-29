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
    Celery task: extract, chunk, embed and persist a document for RAG search.
    Retries up to 3 times with a 60-second delay on failure.
    """
    try:
        asyncio.run(_run_ingestion(document_id))
    except Exception as exc:
        raise self.retry(exc=exc)


async def _run_ingestion(document_id: str):
    """
    Run the full ingestion pipeline inside a fresh event loop.

    Key design decisions:
    - We create a new async engine + session factory per invocation instead of
      reusing the shared `config.database.async_session`. The shared engine's
      connection pool is bound to the event loop that was current when the
      engine was first used. Because `asyncio.run()` closes its loop on exit,
      a retry in the same worker process would find those connections attached
      to a closed loop → RuntimeError. A fresh engine avoids this entirely.
    - We explicitly call `vector_service.connect()` because the Milvus
      connection is established in `main.py` lifespan, which runs only in the
      FastAPI process. The Celery worker is a separate process with no
      connection until we make one here. pymilvus connection state is
      synchronous and persists across `asyncio.run()` calls in the same
      process, so it only needs to be set up once per worker process lifetime;
      the guard inside `connect()` (connections.connect is idempotent) handles
      that safely.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from config.settings import DATABASE_URL, MILVUS_HOST, MILVUS_PORT
    from services import vector_service
    from services.document_service import ingest_document, reset_gemini_client

    # ── Gemini: drop any client cached on a previous (now-closed) event loop ──
    # asyncio.run() gives each task a fresh loop; the Gemini SDK's async httpx
    # pool is bound to the loop it was built on, so a reused client raises
    # "Event loop is closed" on the next task. Rebuild it per run.
    reset_gemini_client()

    # ── Milvus: connect + ensure collection exists in this worker process ──
    try:
        vector_service.connect(MILVUS_HOST, MILVUS_PORT)
        vector_service.ensure_collection()
    except Exception as exc:
        print(f"[Celery] Milvus setup warning: {exc}")
        raise  # fail fast — no point continuing without a vector store

    # ── Fresh async engine for this event-loop instance ───────────────────
    # pool_size=2, max_overflow=0: minimal pool — the task only needs one
    # connection, and we dispose the engine when finished.
    engine = create_async_engine(
        DATABASE_URL,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        async with session_factory() as session:
            result = await ingest_document(document_id, session)
            print(
                f"[Celery] Document {document_id} ingested — "
                f"{result['chunks_created']} chunks created."
            )
    finally:
        # Always release DB connections; prevents fd/connection leaks across
        # retries in the same worker process.
        await engine.dispose()

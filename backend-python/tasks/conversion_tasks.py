"""
Document conversion worker (spec §7).

Turns PowerPoint, Word and similar files into a PDF the classroom can present
page by page, using headless LibreOffice. It runs in its own container on its
own queue because LibreOffice is heavy and occasionally wedges: a slide deck
that refuses to convert must not stall document ingestion or a live class.

The result is cached in object storage and indexed by `document_conversions`,
so the same book or deck is converted once and reused for every period that
opens it. Converted decks are also fed back into the Knowledge Base ingestion
pipeline, so what is on a slide becomes searchable like any other material.

No third-party conversion service is involved — this is LibreOffice on our own
hardware, with no per-document cost.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile

from celery_app import celery_app

# LibreOffice occasionally hangs on a malformed file; without a hard limit the
# worker would sit on it forever.
CONVERT_TIMEOUT_SECONDS = 180


@celery_app.task(
    bind=True,
    name="tasks.conversion_tasks.convert_document",
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def convert_document_task(self, document_id: str):
    try:
        return asyncio.run(_run_conversion(document_id))
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            asyncio.run(_mark_failed(document_id, str(exc)))
            return {"success": False, "error": str(exc)}
        raise self.retry(exc=exc)


# ─── Pipeline ─────────────────────────────────────────────────────────────────

async def _run_conversion(document_id: str) -> dict:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from config.settings import DATABASE_URL
    from models.models import Document
    from models.online_classes import DocumentConversion
    from services import presentation_service, storage_service

    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with session_factory() as db:
            doc = (await db.execute(
                select(Document).where(Document.id == document_id)
            )).scalar_one_or_none()
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            conversion = (await db.execute(
                select(DocumentConversion).where(DocumentConversion.document_id == document_id)
            )).scalar_one_or_none()
            if conversion is None:
                conversion = DocumentConversion(document_id=document_id)
                db.add(conversion)

            ext = (doc.file_type or "").lower().lstrip(".")
            conversion.source_type = ext
            conversion.status = "processing"
            await db.commit()

            source = await asyncio.to_thread(storage_service.download_file, doc.file_path)
            pdf_bytes = await asyncio.to_thread(_libreoffice_to_pdf, source, ext)

            object_name = presentation_service.converted_object_name(document_id)
            await asyncio.to_thread(
                storage_service.upload_file, object_name, pdf_bytes, "application/pdf"
            )

            conversion.object_name = object_name
            conversion.size_bytes = len(pdf_bytes)
            conversion.page_count = _count_pages(pdf_bytes)
            conversion.status = "ready"
            conversion.error = None
            await db.commit()

            # A converted deck carries teachable text; feeding it back into the
            # Knowledge Base means "explain slide 12" can be answered later from
            # an approved source rather than guessed at.
            if not doc.is_ingested:
                await _ingest_converted(db, document_id, object_name)

            return {"success": True, "pages": conversion.page_count}
    finally:
        await engine.dispose()


def _libreoffice_to_pdf(data: bytes, ext: str) -> bytes:
    """Run headless LibreOffice in a scratch directory and read the PDF back."""
    with tempfile.TemporaryDirectory() as workdir:
        source_path = os.path.join(workdir, f"source.{ext or 'bin'}")
        with open(source_path, "wb") as handle:
            handle.write(data)

        # A private user profile per run: a shared profile is the usual cause of
        # LibreOffice refusing to start a second conversion.
        profile = os.path.join(workdir, "profile")
        result = subprocess.run(
            [
                "soffice", "--headless", "--norestore", "--invisible",
                f"-env:UserInstallation=file://{profile}",
                "--convert-to", "pdf", "--outdir", workdir, source_path,
            ],
            capture_output=True,
            timeout=CONVERT_TIMEOUT_SECONDS,
            check=False,
        )

        output_path = os.path.join(workdir, "source.pdf")
        if not os.path.exists(output_path):
            detail = (result.stderr or result.stdout or b"").decode("utf-8", "replace")[:400]
            raise RuntimeError(f"LibreOffice produced no PDF: {detail or 'no output'}")

        with open(output_path, "rb") as handle:
            return handle.read()


def _count_pages(pdf_bytes: bytes) -> int | None:
    try:
        import io
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        return None


async def _ingest_converted(db, document_id: str, object_name: str) -> None:
    """Index the converted PDF's text, without disturbing the original record."""
    try:
        from config.settings import MILVUS_HOST, MILVUS_PORT
        from services import vector_service
        from services.document_service import ingest_document, reset_gemini_client

        reset_gemini_client()
        await asyncio.to_thread(vector_service.connect, MILVUS_HOST, MILVUS_PORT)
        await asyncio.to_thread(vector_service.ensure_collection)
        await ingest_document(document_id, db, source_object=object_name, source_type="pdf")
    except Exception as exc:  # pragma: no cover - indexing is a bonus, not the job
        print(f"[Celery] converted-document ingestion skipped for {document_id}: {exc}")


async def _mark_failed(document_id: str, error: str) -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from config.settings import DATABASE_URL
    from models.online_classes import DocumentConversion

    engine = create_async_engine(DATABASE_URL, pool_size=1, max_overflow=0)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as db:
            conversion = (await db.execute(
                select(DocumentConversion).where(DocumentConversion.document_id == document_id)
            )).scalar_one_or_none()
            if conversion:
                conversion.status = "failed"
                conversion.error = error[:1000]
                await db.commit()
    finally:
        await engine.dispose()

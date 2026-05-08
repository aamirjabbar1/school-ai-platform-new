import asyncio
import os
import time
import random
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user, require_roles
from models.models import User, Document, DocumentChunk
from services import storage_service, vector_service
from tasks.document_tasks import ingest_document_task

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "txt", "inp"}

CONTENT_TYPES = {
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc":  "application/msword",
    "txt":  "text/plain",
    "inp":  "application/octet-stream",
}


# ─── List documents ───────────────────────────────────────────────────────────

@router.get("")
async def get_documents(
    subject: str = None,
    class_level: str = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Document)
    if subject:
        query = query.where(Document.subject == subject)
    if class_level:
        query = query.where(Document.class_level == class_level)
    query = query.order_by(Document.created_at.desc())
    result = await db.execute(query)
    return [d.to_dict() for d in result.scalars().all()]


# ─── Upload ───────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_document(
    document: UploadFile = File(...),
    title: str = Form(...),
    subject: str = Form(...),
    class_level: str = Form(...),
    description: str = Form(None),
    user: User = Depends(require_roles("admin", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    ext = os.path.splitext(document.filename)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type .{ext} not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await document.read()

    # Build a safe, unique object name
    unique = f"{int(time.time())}-{random.randint(0, 999_999_999)}"
    safe_stem = "".join(c if c.isalnum() else "_" for c in os.path.splitext(document.filename)[0])
    safe_filename = f"{safe_stem}-{unique}.{ext}"

    # Create DB record first to get document_id
    doc = Document(
        title=title, subject=subject, class_level=class_level,
        description=description,
        file_path="",          # filled in after MinIO upload
        file_name=document.filename,
        file_type=ext,
        file_size=len(content),
        uploaded_by=user.id,
        is_ingested=False,
    )
    db.add(doc)
    await db.flush()  # get doc.id without committing

    # Upload to MinIO: documents/{doc.id}/{safe_filename}
    object_name = storage_service.make_object_name(doc.id, safe_filename)
    content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
    await asyncio.to_thread(storage_service.upload_file, object_name, content, content_type)

    # Persist object name as file_path
    doc.file_path = object_name
    await db.commit()
    await db.refresh(doc)

    # Dispatch ingestion to Celery worker (non-blocking)
    ingest_document_task.delay(doc.id)

    resp = doc.to_dict()
    resp["message"] = "Document uploaded to MinIO. Ingestion queued in background worker."
    return resp


# ─── Download (stream from MinIO) ─────────────────────────────────────────────

@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_bytes = await asyncio.to_thread(storage_service.download_file, doc.file_path)
    content_type = CONTENT_TYPES.get(doc.file_type, "application/octet-stream")

    return StreamingResponse(
        iter([file_bytes]),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.file_name}"'},
    )


# ─── Re-ingest ────────────────────────────────────────────────────────────────

@router.post("/{document_id}/reingest")
async def reingest_document(
    document_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.is_ingested = False
    doc.total_chunks = 0
    doc.ingestion_error = None
    await db.commit()

    ingest_document_task.delay(doc.id)
    return {"message": "Re-ingestion queued."}


# ─── Delete ───────────────────────────────────────────────────────────────────

@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove PostgreSQL chunks
    await db.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == doc.id)
    )
    await db.delete(doc)
    await db.commit()

    # Remove from MinIO + Milvus (best-effort, non-blocking)
    async def _cleanup():
        await asyncio.to_thread(storage_service.delete_file, doc.file_path)
        await asyncio.to_thread(vector_service.delete_document_chunks, document_id)

    asyncio.create_task(_cleanup())
    return {"message": "Document deleted."}


# ─── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    stats_sql = text("""
        SELECT
            COUNT(DISTINCT d.id)                                     AS total_documents,
            COUNT(DISTINCT d.id) FILTER (WHERE d.is_ingested = true) AS ingested_documents,
            COUNT(DISTINCT dc.id)                                    AS total_chunks,
            COUNT(DISTINCT d.subject)                                AS subjects_covered,
            COUNT(DISTINCT d.class_level)                            AS class_levels
        FROM documents d
        LEFT JOIN document_chunks dc ON dc.document_id = d.id
    """)
    row = (await db.execute(stats_sql)).mappings().first()
    stats = dict(row)

    by_subject_sql = text("""
        SELECT subject, COUNT(*) AS count, COALESCE(SUM(total_chunks), 0) AS chunks
        FROM documents
        WHERE is_ingested = true
        GROUP BY subject
        ORDER BY count DESC
    """)
    by_subject = [dict(r) for r in (await db.execute(by_subject_sql)).mappings().all()]
    stats["by_subject"] = by_subject
    return stats

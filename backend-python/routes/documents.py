import os
import asyncio
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db, async_session
from config.settings import UPLOAD_DIR
from middleware.auth import get_current_user, require_roles
from models.models import User, Document, DocumentChunk
from services.document_service import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "txt", "inp"}


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
    docs = result.scalars().all()
    return [d.to_dict() for d in docs]


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
        raise HTTPException(status_code=400, detail=f"File type .{ext} not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    # Save file
    upload_dir = os.path.join(UPLOAD_DIR, "documents")
    os.makedirs(upload_dir, exist_ok=True)

    import time, random
    unique = f"{int(time.time())}-{random.randint(0, 999999999)}"
    safe_name = "".join(c if c.isalnum() else "_" for c in os.path.splitext(document.filename)[0])
    file_name = f"{safe_name}-{unique}.{ext}"
    file_path = os.path.join(upload_dir, file_name)

    content = await document.read()
    with open(file_path, "wb") as f:
        f.write(content)

    doc = Document(
        title=title, subject=subject, class_level=class_level,
        description=description, file_path=file_path,
        file_name=document.filename, file_type=ext,
        file_size=len(content), uploaded_by=user.id, is_ingested=False,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Background ingestion
    async def _ingest():
        async with async_session() as session:
            try:
                result = await ingest_document(doc.id, session)
                print(f'✅ Document "{title}" ingested: {result["chunks_created"]} chunks')
            except Exception as e:
                print(f'❌ Document ingestion failed for "{title}": {e}')

    asyncio.create_task(_ingest())

    resp = doc.to_dict()
    resp["message"] = "Document uploaded. Ingestion is in progress."
    return resp


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

    async def _reingest():
        async with async_session() as session:
            try:
                res = await ingest_document(doc.id, session)
                print(f'✅ Re-ingestion completed for "{doc.title}": {res["chunks_created"]} chunks')
            except Exception as e:
                print(f'❌ Re-ingestion failed for "{doc.title}": {e}')

    asyncio.create_task(_reingest())
    return {"message": "Re-ingestion started"}


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

    await db.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == doc.id)
    )
    await db.delete(doc)
    await db.commit()
    return {"message": "Document deleted"}


@router.get("/stats")
async def get_stats(
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    stats_sql = text("""
        SELECT
            COUNT(DISTINCT d.id) as total_documents,
            COUNT(DISTINCT CASE WHEN d.is_ingested = 1 THEN d.id END) as ingested_documents,
            COUNT(DISTINCT dc.id) as total_chunks,
            COUNT(DISTINCT d.subject) as subjects_covered,
            COUNT(DISTINCT d.class_level) as class_levels
        FROM documents d
        LEFT JOIN document_chunks dc ON dc.document_id = d.id
    """)
    result = await db.execute(stats_sql)
    stats = dict(result.mappings().first())

    by_subject_sql = text("""
        SELECT subject, COUNT(*) as count, SUM(total_chunks) as chunks
        FROM documents
        WHERE is_ingested = 1
        GROUP BY subject
        ORDER BY count DESC
    """)
    result2 = await db.execute(by_subject_sql)
    by_subject = [dict(r) for r in result2.mappings().all()]

    stats["by_subject"] = by_subject
    return stats

import asyncio
import os
import re
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

# ─── Auto-detection helpers ───────────────────────────────────────────────────

_SUBJECT_KEYWORDS: dict[str, list[str]] = {
    "Mathematics":      ["math", "maths", "algebra", "geometry", "calculus", "arithmetic", "trigonometry"],
    "Physics":          ["physics", "phys"],
    "Chemistry":        ["chemistry", "chem"],
    "Biology":          ["biology", "bio"],
    "Science":          ["science", "sci"],
    "General Science":  ["general science", "general_science"],
    "English":          ["english", "eng", "literature", "grammar"],
    "Urdu":             ["urdu"],
    "Islamiat":         ["islamiat", "islam", "islamic"],
    "Computer Science": ["computer", "cs", "ict", "programming", "it"],
    "Social Studies":   ["social", "civics", "citizenship"],
    "History":          ["history", "hist"],
    "Geography":        ["geography", "geo"],
    "Economics":        ["economics", "econ"],
}

def _detect_subject(text: str) -> str:
    lower = text.lower()
    for subject, keywords in _SUBJECT_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return subject
    return "General"

def _detect_class(text: str) -> str:
    lower = text.lower()
    for pattern in (
        r"class\s*(\d{1,2})",
        r"grade\s*(\d{1,2})",
        r"\b(\d{1,2})(?:th|st|nd|rd)\s*(?:class|grade)\b",
    ):
        m = re.search(pattern, lower)
        if m:
            return f"Class {m.group(1)}"
    return "General"

def _title_from_filename(filename: str) -> str:
    stem = os.path.splitext(filename)[0]
    return re.sub(r"[\-_]+", " ", stem).strip()


# ─── List documents ───────────────────────────────────────────────────────────

@router.get("")
async def get_documents(
    subject: str = None,
    class_level: str = None,
    document_type: str = None,
    language: str = None,
    academic_year: str = None,
    term: str = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Document)
    if subject:
        query = query.where(Document.subject == subject)
    if class_level:
        query = query.where(Document.class_level == class_level)
    if document_type:
        query = query.where(Document.document_type == document_type)
    if language:
        query = query.where(Document.language == language)
    if academic_year:
        query = query.where(Document.academic_year == academic_year)
    if term:
        query = query.where(Document.term == term)
    query = query.order_by(Document.created_at.desc())
    result = await db.execute(query)
    return [d.to_dict() for d in result.scalars().all()]


# ─── Upload ───────────────────────────────────────────────────────────────────

ALLOWED_DOCUMENT_TYPES = {"book", "exam", "assignment", "notes", "worksheet"}
ALLOWED_LANGUAGES = {"English", "Urdu", "Bilingual"}
# Sub-classification for question papers (document_type == "exam")
ALLOWED_PAPER_TYPES = {"past_paper", "test", "midterm", "final", "mcqs"}


@router.post("/upload")
async def upload_document(
    document: UploadFile = File(...),
    title: str = Form(None),
    subject: str = Form(None),
    class_level: str = Form(None),
    description: str = Form(None),
    document_type: str = Form(None),
    language: str = Form(None),
    academic_year: str = Form(None),
    term: str = Form(None),
    paper_type: str = Form(None),
    chapter: str = Form(None),
    user: User = Depends(require_roles("admin", "teacher")),
    db: AsyncSession = Depends(get_db),
):
    ext = os.path.splitext(document.filename)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type .{ext} not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Auto-detect anything the caller did not supply
    detected_title    = (title or "").strip()     or _title_from_filename(document.filename)
    detected_subject  = (subject or "").strip()   or _detect_subject(document.filename)
    detected_class    = (class_level or "").strip() or _detect_class(document.filename)
    detected_type     = (document_type or "").strip() or "book"
    detected_language = (language or "").strip()  or "English"

    if detected_type not in ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail=f"document_type must be one of: {', '.join(ALLOWED_DOCUMENT_TYPES)}")
    if detected_language not in ALLOWED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"language must be one of: {', '.join(ALLOWED_LANGUAGES)}")

    detected_paper_type = (paper_type or "").strip() or None
    if detected_paper_type and detected_paper_type not in ALLOWED_PAPER_TYPES:
        raise HTTPException(status_code=400, detail=f"paper_type must be one of: {', '.join(ALLOWED_PAPER_TYPES)}")
    detected_chapter = (chapter or "").strip() or None

    content = await document.read()

    # Build a safe, unique object name
    unique = f"{int(time.time())}-{random.randint(0, 999_999_999)}"
    safe_stem = "".join(c if c.isalnum() else "_" for c in os.path.splitext(document.filename)[0])
    safe_filename = f"{safe_stem}-{unique}.{ext}"

    # Create DB record first to get document_id
    doc = Document(
        title=detected_title,
        subject=detected_subject,
        class_level=detected_class,
        description=description or None,
        document_type=detected_type,
        language=detected_language,
        academic_year=academic_year or None,
        term=term or None,
        paper_type=detected_paper_type,
        chapter=detected_chapter,
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
    resp["message"] = "Document uploaded. Ingestion queued in background worker."
    resp["auto_detected"] = {
        "title":         not (title or "").strip(),
        "subject":       not (subject or "").strip(),
        "class_level":   not (class_level or "").strip(),
        "document_type": not (document_type or "").strip(),
        "language":      not (language or "").strip(),
    }
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
            COUNT(DISTINCT d.id)                                          AS total_documents,
            COUNT(DISTINCT d.id) FILTER (WHERE d.is_ingested = true)      AS ingested_documents,
            COUNT(DISTINCT d.id) FILTER (WHERE d.document_type = 'exam')  AS question_papers,
            COUNT(DISTINCT d.id) FILTER (WHERE d.document_type != 'exam'
                                          OR d.document_type IS NULL)     AS books,
            COUNT(DISTINCT dc.id)                                         AS total_chunks,
            COUNT(DISTINCT d.subject)                                     AS subjects_covered,
            COUNT(DISTINCT d.class_level)                                 AS class_levels
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

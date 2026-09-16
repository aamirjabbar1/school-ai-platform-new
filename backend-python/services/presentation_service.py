"""
Book and resource presentation (spec §7).

The classroom presents material from the existing Knowledge Base: a teacher
picks Grade 5 → Science → Oxford Book → page 62 and every student sees that
page. What actually crosses the network is the page number, not a video of it —
each student's browser renders the PDF locally. On a home connection in
Pakistan that is the difference between a readable page and a smear.

Formats are normalised to PDF: PDFs are served as they are, PowerPoint and Word
are converted once by a LibreOffice worker and cached, images are served
directly. Nothing is re-uploaded by the teacher — the Knowledge Base already
has it.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Document
from models.online_classes import DocumentConversion
from services import class_matching, storage_service
from services.curriculum_service import resolve_curriculum_class

logger = logging.getLogger("agent")

# Served straight from the Knowledge Base.
NATIVE_PDF = {"pdf"}
NATIVE_IMAGE = {"png", "jpg", "jpeg", "gif", "webp"}
# Converted to PDF once, then cached.
CONVERTIBLE = {"pptx", "ppt", "docx", "doc", "odp", "odt", "xlsx", "txt"}

PRESENTABLE = NATIVE_PDF | NATIVE_IMAGE | CONVERTIBLE

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def converted_object_name(document_id: str) -> str:
    return f"converted/{document_id}/presentation.pdf"


def presentation_kind(file_type: str | None) -> str:
    """How a browser should render this document: pdf | image | unsupported."""
    ext = (file_type or "").lower().lstrip(".")
    if ext in NATIVE_PDF or ext in CONVERTIBLE:
        return "pdf"
    if ext in NATIVE_IMAGE:
        return "image"
    return "unsupported"


# ─── What a class may present ─────────────────────────────────────────────────

async def resources_for_class(
    db: AsyncSession,
    *,
    class_name: str,
    subject: str | None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Knowledge Base material relevant to this classroom.

    Filtered by the class being taught and, by default, the subject of the
    lesson — a Grade 5 Science teacher should not have to scroll past Grade 9
    Chemistry to find their book. The Pre-Board curriculum mapping is applied,
    so a class that studies a different year's syllabus sees the right books.
    """
    kb_class = await resolve_curriculum_class(class_name, db)

    query = select(Document)
    if subject:
        query = query.where(or_(Document.subject == subject, Document.subject == "Other"))
    query = query.order_by(Document.created_at.desc()).limit(limit * 3)

    result = await db.execute(query)
    documents = result.scalars().all()

    conversions = await _conversion_map(db, [d.id for d in documents])

    out = []
    for doc in documents:
        if presentation_kind(doc.file_type) == "unsupported":
            continue
        if not _class_matches(doc.class_level, kb_class):
            continue
        if search and search.lower() not in (doc.title or "").lower():
            continue

        conversion = conversions.get(doc.id)
        out.append({
            "document_id": doc.id,
            "title": doc.title,
            "subject": doc.subject,
            "class_level": doc.class_level,
            "document_type": doc.document_type,
            "file_type": doc.file_type,
            "chapter": doc.chapter,
            "kind": presentation_kind(doc.file_type),
            "needs_conversion": (doc.file_type or "").lower() in CONVERTIBLE,
            "conversion_status": conversion.status if conversion else None,
            "page_count": conversion.page_count if conversion else None,
        })
        if len(out) >= limit:
            break
    return out


def _class_matches(doc_class: str | None, target_class: str | None) -> bool:
    """"All Classes" material belongs to every classroom; otherwise compare
    canonically, because the Knowledge Base and teachers spell classes
    differently."""
    if not doc_class:
        return True
    if doc_class.strip().lower() in ("all classes", "general", "all"):
        return True
    return class_matching.same_class(doc_class, target_class)


async def _conversion_map(db: AsyncSession, document_ids: list[str]) -> dict[str, DocumentConversion]:
    if not document_ids:
        return {}
    result = await db.execute(
        select(DocumentConversion).where(DocumentConversion.document_id.in_(document_ids))
    )
    return {c.document_id: c for c in result.scalars().all()}


# ─── Resolving a document to something presentable ────────────────────────────

async def ensure_presentable(db: AsyncSession, document: Document) -> dict:
    """Return how to serve this document, converting it first if necessary.

    Returns {"state": "ready"|"converting"|"failed"|"unsupported", ...}. The
    caller shows the teacher a spinner for "converting" rather than a broken
    page — a conversion takes seconds, and pretending otherwise makes a teacher
    think the class is broken.
    """
    ext = (document.file_type or "").lower().lstrip(".")

    if ext in NATIVE_PDF:
        return {"state": "ready", "kind": "pdf", "object_name": document.file_path,
                "content_type": "application/pdf"}

    if ext in NATIVE_IMAGE:
        return {"state": "ready", "kind": "image", "object_name": document.file_path,
                "content_type": CONTENT_TYPES.get(ext, "application/octet-stream")}

    if ext not in CONVERTIBLE:
        return {"state": "unsupported", "kind": "unsupported"}

    conversion = (await db.execute(
        select(DocumentConversion).where(DocumentConversion.document_id == document.id)
    )).scalar_one_or_none()

    if conversion and conversion.status == "ready" and conversion.object_name:
        # Trust but verify: a cache row whose object has been swept away would
        # otherwise present a teacher with an empty page mid-lesson.
        if await asyncio.to_thread(_object_exists, conversion.object_name):
            return {"state": "ready", "kind": "pdf", "object_name": conversion.object_name,
                    "content_type": "application/pdf", "page_count": conversion.page_count}
        conversion.status = "pending"
        conversion.object_name = None

    if conversion is None:
        conversion = DocumentConversion(document_id=document.id, status="pending", source_type=ext)
        db.add(conversion)

    if conversion.status in ("pending", "failed"):
        conversion.status = "processing"
        conversion.error = None
        await db.commit()
        _queue_conversion(document.id)
        return {"state": "converting", "kind": "pdf"}

    await db.commit()
    if conversion.status == "processing":
        return {"state": "converting", "kind": "pdf"}
    return {"state": conversion.status, "kind": "pdf", "error": conversion.error}


def _object_exists(object_name: str) -> bool:
    try:
        storage_service.get_client().stat_object(storage_service.MINIO_BUCKET, object_name)
        return True
    except Exception:
        return False


def _queue_conversion(document_id: str) -> None:
    """Hand the document to the LibreOffice worker. Never raises: a broker
    hiccup should surface as "still converting", not as a failed class."""
    try:
        from tasks.conversion_tasks import convert_document_task
        convert_document_task.delay(document_id)
    except Exception as exc:  # pragma: no cover - broker unavailable
        logger.warning("[PRESENTATION] could not queue conversion for %s: %s", document_id, exc)


# ─── Streaming ────────────────────────────────────────────────────────────────

def read_object(object_name: str) -> bytes:
    return storage_service.download_file(object_name)


def read_object_range(object_name: str, offset: int, length: int) -> bytes:
    """Byte range read — lets a browser's PDF viewer fetch one page's worth of a
    400-page textbook instead of the whole book."""
    client = storage_service.get_client()
    response = client.get_object(
        storage_service.MINIO_BUCKET, object_name, offset=offset, length=length
    )
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def object_size(object_name: str) -> int:
    stat = storage_service.get_client().stat_object(storage_service.MINIO_BUCKET, object_name)
    return int(stat.size)

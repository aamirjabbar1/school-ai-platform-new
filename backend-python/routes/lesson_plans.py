from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user, require_roles
from models.models import User, LessonPlan
from services import audit_service
from services.ai_service import generate_lesson_plan
from services.lesson_plan_store import publish_plan_safely
from services.pdf_service import build_lesson_plan_pdf
from services.docx_service import build_lesson_plan_docx
from utils.http import attachment_disposition

router = APIRouter(prefix="/lesson-plans", tags=["lesson-plans"])


class GenerateLessonPlanRequest(BaseModel):
    subject: str
    class_name: str
    section: str | None = None
    plan_type: str = "weekly"
    board: str | None = None
    book_name: str | None = None
    academic_session: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    num_weeks: int | None = None
    days_per_week: int | None = None
    periods_per_week: int | None = None
    chapters: list[str] = []
    topics: list[str] = []
    learning_objectives: str | None = None
    bloom_level: str | None = None
    methodology: str | None = None
    resources: str | None = None
    homework_pref: str | None = None
    assessment_pref: str | None = None
    holidays: str | None = None
    exam_schedule: str | None = None
    revision_week: str | None = None
    teacher_notes: str | None = None


class SaveLessonPlanRequest(BaseModel):
    title: str
    subject: str
    class_name: str
    section: str | None = None
    plan_type: str = "weekly"
    board: str | None = None
    book_name: str | None = None
    academic_session: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    plan_data: dict = {}
    inputs: dict = {}


class UpdateLessonPlanRequest(BaseModel):
    title: str | None = None
    plan_data: dict | None = None


PLAN_TYPES = {
    "daily", "date_wise", "weekly", "monthly", "unit", "chapter", "term",
    "annual", "revision", "exam_prep", "practical",
}


def _plan_title(body: GenerateLessonPlanRequest) -> str:
    section = (body.section or "").strip() or None
    class_label = f"{body.class_name} - {section}" if section else body.class_name
    type_label = body.plan_type.replace("_", " ").title()
    return f"{type_label} Lesson Plan - {body.subject} ({class_label})"


@router.get("")
async def get_lesson_plans(
    subject: str = None,
    class_name: str = None,
    plan_type: str = None,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(LessonPlan).where(LessonPlan.is_archived.is_(False))
    if user.role == "teacher":
        query = query.where(LessonPlan.teacher_id == user.id)
    if subject:
        query = query.where(LessonPlan.subject == subject)
    if class_name:
        query = query.where(LessonPlan.class_name == class_name)
    if plan_type:
        query = query.where(LessonPlan.plan_type == plan_type)
    query = query.order_by(LessonPlan.created_at.desc())

    result = await db.execute(query)
    return [p.to_dict() for p in result.scalars().all()]


@router.get("/{plan_id}")
async def get_lesson_plan(
    plan_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    plan = await _get_owned_plan(plan_id, user, db)
    return plan.to_dict()


@router.post("/generate")
async def generate_plan(
    body: GenerateLessonPlanRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    if body.plan_type not in PLAN_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid plan type: {body.plan_type}")
    try:
        result = await generate_lesson_plan({
            "subject": body.subject,
            "class_level": body.class_name,
            "plan_type": body.plan_type,
            "board": body.board,
            "book_name": body.book_name,
            "academic_session": body.academic_session,
            "start_date": body.start_date,
            "end_date": body.end_date,
            "num_weeks": body.num_weeks,
            "days_per_week": body.days_per_week,
            "periods_per_week": body.periods_per_week,
            "chapters": body.chapters,
            "topics": body.topics,
            "learning_objectives": body.learning_objectives,
            "bloom_level": body.bloom_level,
            "methodology": body.methodology,
            "resources": body.resources,
            "homework_pref": body.homework_pref,
            "assessment_pref": body.assessment_pref,
            "holidays": body.holidays,
            "exam_schedule": body.exam_schedule,
            "revision_week": body.revision_week,
            "teacher_notes": body.teacher_notes,
        }, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    plan_data = result["plan_data"]
    section = (body.section or "").strip() or None
    title = plan_data.get("title") or _plan_title(body)
    plan = LessonPlan(
        title=title, subject=body.subject, class_name=body.class_name, section=section,
        teacher_id=user.id, plan_type=body.plan_type, board=body.board,
        book_name=body.book_name, academic_session=body.academic_session,
        start_date=body.start_date, end_date=body.end_date,
        plan_data=plan_data, inputs=body.model_dump(), is_published=False,
    )
    db.add(plan)
    await db.flush()
    audit_service.record_change(
        db, plan, content_type=audit_service.LESSON_PLAN,
        action="created", actor=user, ai_inputs=body.model_dump(),
    )
    await db.commit()
    await db.refresh(plan)

    # File the plan in the Knowledge Base straight away, so it is available for
    # curriculum validation and coverage checks without anyone uploading it.
    document_id = await publish_plan_safely(db, plan, uploaded_by=user.id)
    await db.refresh(plan)

    return {
        "plan": plan.to_dict(),
        "sources_used": result["sources"],
        "knowledge_base_document_id": document_id,
        "saved_to_knowledge_base": document_id is not None,
    }


@router.post("")
async def create_plan(
    body: SaveLessonPlanRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    plan = LessonPlan(
        title=body.title, subject=body.subject, class_name=body.class_name,
        section=(body.section or "").strip() or None, teacher_id=user.id,
        plan_type=body.plan_type, board=body.board, book_name=body.book_name,
        academic_session=body.academic_session, start_date=body.start_date,
        end_date=body.end_date, plan_data=body.plan_data, inputs=body.inputs,
    )
    db.add(plan)
    await db.flush()
    audit_service.record_change(
        db, plan, content_type=audit_service.LESSON_PLAN, action="created", actor=user,
    )
    await db.commit()
    await db.refresh(plan)
    return plan.to_dict()


@router.put("/{plan_id}")
async def update_plan(
    plan_id: str,
    body: UpdateLessonPlanRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    plan = await _get_owned_plan(plan_id, user, db)
    if body.title is not None:
        plan.title = body.title
    if body.plan_data is not None:
        plan.plan_data = body.plan_data
    audit_service.record_change(
        db, plan, content_type=audit_service.LESSON_PLAN, action="updated", actor=user,
    )
    await db.commit()
    await db.refresh(plan)
    return plan.to_dict()


@router.put("/{plan_id}/publish")
async def publish_plan(
    plan_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    plan = await _get_owned_plan(plan_id, user, db)
    plan.is_published = not plan.is_published
    audit_service.record_event(
        db, plan, content_type=audit_service.LESSON_PLAN,
        action="published" if plan.is_published else "unpublished", actor=user,
    )
    await db.commit()
    return {"message": f"Plan {'published' if plan.is_published else 'unpublished'}", "plan": plan.to_dict()}


@router.post("/{plan_id}/duplicate")
async def duplicate_plan(
    plan_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    src = await _get_owned_plan(plan_id, user, db)
    copy = LessonPlan(
        title=f"{src.title} (Copy)", subject=src.subject, class_name=src.class_name,
        section=src.section, teacher_id=user.id, plan_type=src.plan_type,
        board=src.board, book_name=src.book_name, academic_session=src.academic_session,
        start_date=src.start_date, end_date=src.end_date,
        plan_data=src.plan_data, inputs=src.inputs, is_published=False,
    )
    db.add(copy)
    await db.flush()
    audit_service.record_change(
        db, copy, content_type=audit_service.LESSON_PLAN, action="created",
        actor=user, note=f"Duplicated from {src.title}",
    )
    await db.commit()
    await db.refresh(copy)
    return copy.to_dict()


@router.delete("/{plan_id}")
async def delete_plan(
    plan_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    plan = await _get_owned_plan(plan_id, user, db)
    await db.delete(plan)
    await db.commit()
    return {"message": "Lesson plan deleted"}


@router.get("/{plan_id}/pdf")
async def download_plan_pdf(
    plan_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    plan = await _get_owned_plan(plan_id, user, db)
    pdf_bytes = build_lesson_plan_pdf(plan.to_dict())
    return _file_response(pdf_bytes, plan.title, "pdf", "application/pdf")


@router.get("/{plan_id}/docx")
async def download_plan_docx(
    plan_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    plan = await _get_owned_plan(plan_id, user, db)
    docx_bytes = build_lesson_plan_docx(plan.to_dict())
    return _file_response(
        docx_bytes, plan.title, "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ─── helpers ──────────────────────────────────────────────────────────────────

async def _get_owned_plan(plan_id: str, user: User, db: AsyncSession) -> LessonPlan:
    result = await db.execute(select(LessonPlan).where(LessonPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Lesson plan not found")
    if plan.teacher_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    return plan


def _file_response(data: bytes, title: str, ext: str, media_type: str) -> StreamingResponse:
    return StreamingResponse(
        iter([data]),
        media_type=media_type,
        headers={
            "Content-Disposition": attachment_disposition(title, ext, fallback="lesson_plan"),
        },
    )

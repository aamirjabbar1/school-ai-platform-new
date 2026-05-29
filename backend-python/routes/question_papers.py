from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user, require_roles
from models.models import User, QuestionPaper
from services.ai_service import (
    generate_question_paper,
    predict_important_questions,
    generate_practice_test,
    grade_self_assessment,
)
from services.pdf_service import build_question_paper_pdf

router = APIRouter(prefix="/question-papers", tags=["question-papers"])


class GeneratePaperRequest(BaseModel):
    subject: str
    class_name: str
    paper_type: str
    total_marks: int = 100
    duration_minutes: int = 60
    topics: list[str] = []
    difficulty_distribution: dict = {"easy": 30, "medium": 50, "hard": 20}
    # "standard" builds from the curriculum; "model" mirrors uploaded past papers.
    generation_mode: str = "standard"
    use_past_papers: bool = True


class PredictImportantRequest(BaseModel):
    subject: str
    class_name: str
    paper_type: str | None = None


class GeneratePracticeRequest(BaseModel):
    subject: str
    class_name: str
    topics: list[str] = []
    num_questions: int = 10
    difficulty: str = "mixed"


class GradePracticeRequest(BaseModel):
    questions: list[dict]
    answer_key: list[dict]
    answers: dict


class CreatePaperRequest(BaseModel):
    title: str
    subject: str
    class_name: str
    paper_type: str = "class_test"
    questions: list = []
    answer_key: list = []
    total_marks: int = 100
    duration_minutes: int = 60
    instructions: str | None = None


@router.get("")
async def get_question_papers(
    subject: str = None,
    class_name: str = None,
    paper_type: str = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(QuestionPaper)
    if user.role == "teacher":
        query = query.where(QuestionPaper.teacher_id == user.id)
    if subject:
        query = query.where(QuestionPaper.subject == subject)
    if class_name:
        query = query.where(QuestionPaper.class_name == class_name)
    if paper_type:
        query = query.where(QuestionPaper.paper_type == paper_type)
    query = query.order_by(QuestionPaper.created_at.desc())

    result = await db.execute(query)
    papers = result.scalars().all()

    if user.role == "student":
        return [p.to_dict(hide_answers=True) for p in papers if p.is_published and p.class_name == user.class_name]

    return [p.to_dict() for p in papers]


@router.get("/{paper_id}")
async def get_question_paper(
    paper_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(QuestionPaper).where(QuestionPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Question paper not found")

    if user.role == "student":
        if not paper.is_published:
            raise HTTPException(status_code=403, detail="Paper not published yet")
        if paper.class_name != user.class_name:
            raise HTTPException(status_code=403, detail="This paper is not for your class")
        return paper.to_dict(hide_answers=True)

    return paper.to_dict()


@router.get("/{paper_id}/pdf")
async def download_question_paper_pdf(
    paper_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Render the paper as a printable PDF.

    Teachers/admins get the answer key appended; students get the questions
    only (and only if the paper is published for their class).
    """
    result = await db.execute(select(QuestionPaper).where(QuestionPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Question paper not found")

    include_answers = user.role in ("teacher", "admin")

    if user.role == "student":
        if not paper.is_published:
            raise HTTPException(status_code=403, detail="Paper not published yet")
        if paper.class_name != user.class_name:
            raise HTTPException(status_code=403, detail="This paper is not for your class")

    paper_dict = paper.to_dict()
    pdf_bytes = build_question_paper_pdf(paper_dict, include_answers=include_answers)

    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in (paper.title or "paper"))
    filename = f"{safe_title}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/generate")
async def generate_paper(
    body: GeneratePaperRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await generate_question_paper({
            "subject": body.subject,
            "class_level": body.class_name,
            "paper_type": body.paper_type,
            "total_marks": body.total_marks,
            "duration_minutes": body.duration_minutes,
            "topics": body.topics,
            "difficulty_distribution": body.difficulty_distribution,
            "generation_mode": body.generation_mode,
            "use_past_papers": body.use_past_papers,
        }, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    prefix = "MODEL PAPER" if body.generation_mode == "model" else body.paper_type.replace('_', ' ').upper()
    title = f"{prefix} - {body.subject} ({body.class_name})"
    paper = QuestionPaper(
        title=title, subject=body.subject, class_name=body.class_name,
        teacher_id=user.id, paper_type=body.paper_type,
        questions=result["questions"], answer_key=result["answer_key"],
        total_marks=body.total_marks, duration_minutes=body.duration_minutes,
        is_published=False,
    )
    db.add(paper)
    await db.commit()
    await db.refresh(paper)

    return {
        "paper": paper.to_dict(),
        "formatted_paper": result["paper_data"],
        "sources_used": result["sources"],
    }


# ─── AI exam suite (past-paper-powered) ───────────────────────────────────────

@router.post("/predict-important")
async def predict_important(
    body: PredictImportantRequest,
    user: User = Depends(require_roles("teacher", "admin")),
):
    """Analyse uploaded past papers and predict the most likely exam questions."""
    try:
        return await predict_important_questions(
            subject=body.subject,
            class_level=body.class_name,
            paper_type=body.paper_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/practice/generate")
async def practice_generate(
    body: GeneratePracticeRequest,
    user: User = Depends(get_current_user),
):
    """Generate a self-practice test (books + past papers). Available to students too."""
    # Students always practise content for their own class level.
    class_level = user.class_name if user.role == "student" and user.class_name else body.class_name
    try:
        return await generate_practice_test(
            subject=body.subject,
            class_level=class_level,
            topics=body.topics,
            num_questions=max(1, min(body.num_questions, 30)),
            difficulty=body.difficulty,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/practice/grade")
async def practice_grade(
    body: GradePracticeRequest,
    user: User = Depends(get_current_user),
):
    """Grade a student's practice answers against the model key (self-assessment)."""
    if not body.questions:
        raise HTTPException(status_code=400, detail="No questions to grade")
    try:
        return await grade_self_assessment(
            questions=body.questions,
            answer_key=body.answer_key,
            student_answers=body.answers or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("")
async def create_paper(
    body: CreatePaperRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    paper = QuestionPaper(
        title=body.title, subject=body.subject, class_name=body.class_name,
        teacher_id=user.id, paper_type=body.paper_type,
        questions=body.questions, answer_key=body.answer_key,
        total_marks=body.total_marks, duration_minutes=body.duration_minutes,
        instructions=body.instructions,
    )
    db.add(paper)
    await db.commit()
    await db.refresh(paper)
    return paper.to_dict()


@router.put("/{paper_id}/publish")
async def publish_paper(
    paper_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(QuestionPaper).where(QuestionPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if paper.teacher_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    paper.is_published = not paper.is_published
    await db.commit()
    return {"message": f"Paper {'published' if paper.is_published else 'unpublished'}", "paper": paper.to_dict()}


@router.delete("/{paper_id}")
async def delete_paper(
    paper_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(QuestionPaper).where(QuestionPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if paper.teacher_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    await db.delete(paper)
    await db.commit()
    return {"message": "Paper deleted"}

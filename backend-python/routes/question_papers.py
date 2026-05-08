from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user, require_roles
from models.models import User, QuestionPaper
from services.ai_service import generate_question_paper

router = APIRouter(prefix="/question-papers", tags=["question-papers"])


class GeneratePaperRequest(BaseModel):
    subject: str
    class_name: str
    paper_type: str
    total_marks: int = 100
    duration_minutes: int = 60
    topics: list[str] = []
    difficulty_distribution: dict = {"easy": 30, "medium": 50, "hard": 20}


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
        return paper.to_dict(hide_answers=True)

    return paper.to_dict()


@router.post("/generate")
async def generate_paper(
    body: GeneratePaperRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await generate_question_paper({
        "subject": body.subject,
        "class_level": body.class_name,
        "paper_type": body.paper_type,
        "total_marks": body.total_marks,
        "duration_minutes": body.duration_minutes,
        "topics": body.topics,
        "difficulty_distribution": body.difficulty_distribution,
    }, db)

    title = f"{body.paper_type.replace('_', ' ').upper()} - {body.subject} ({body.class_name})"
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

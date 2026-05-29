from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from config.settings import UPLOAD_DIR
from middleware.auth import get_current_user, require_roles
from models.models import User, Assignment, Submission, Notification
from services.ai_service import generate_assignment_content

router = APIRouter(prefix="/assignments", tags=["assignments"])


def _parse_date(value):
    """Coerce a date input into a datetime.date (or None). Accepts '' / None,
    'YYYY-MM-DD', or an ISO datetime string. Raises 400 on a malformed value."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid due_date '{value}'. Expected YYYY-MM-DD.")


class CreateAssignmentRequest(BaseModel):
    title: str
    description: str
    subject: str
    class_name: str
    due_date: str | None = None
    assignment_type: str = "homework"
    max_marks: int = 100
    instructions: str | None = None


class AIGenerateRequest(BaseModel):
    topic: str
    subject: str
    class_level: str
    assignment_type: str = "homework"


class GradeRequest(BaseModel):
    submission_id: str
    grade: float
    feedback: str | None = None


@router.get("")
async def get_assignments(
    subject: str = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Assignment).where(Assignment.is_active == True)

    if user.role == "teacher":
        query = query.where(Assignment.teacher_id == user.id)
    elif user.role == "student":
        query = query.where(Assignment.class_name == user.class_name)

    if subject:
        query = query.where(Assignment.subject == subject)
    query = query.order_by(Assignment.created_at.desc())

    result = await db.execute(query)
    assignments = result.scalars().all()

    if user.role == "student":
        assignment_ids = [a.id for a in assignments]
        sub_result = await db.execute(
            select(Submission).where(
                Submission.student_id == user.id,
                Submission.assignment_id.in_(assignment_ids),
            )
        )
        subs = sub_result.scalars().all()
        sub_map = {s.assignment_id: s.to_dict() for s in subs}
        return [{**a.to_dict(), "my_submission": sub_map.get(a.id)} for a in assignments]

    # teacher / admin: attach each assignment's submissions (with student names)
    # so the dashboard counts work and the submissions can be reviewed & graded.
    assignment_ids = [a.id for a in assignments]
    by_assignment: dict[str, list[dict]] = {}
    if assignment_ids:
        sub_result = await db.execute(
            select(Submission).where(Submission.assignment_id.in_(assignment_ids))
        )
        subs = sub_result.scalars().all()
        student_ids = {s.student_id for s in subs}
        names: dict[str, str] = {}
        if student_ids:
            st_result = await db.execute(select(User).where(User.id.in_(student_ids)))
            names = {u.id: u.name for u in st_result.scalars().all()}
        for s in subs:
            d = s.to_dict()
            d["student_name"] = names.get(s.student_id, "Student")
            by_assignment.setdefault(s.assignment_id, []).append(d)

    return [{**a.to_dict(), "submissions": by_assignment.get(a.id, [])} for a in assignments]


@router.get("/{assignment_id}")
async def get_assignment(
    assignment_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Assignment).where(Assignment.id == assignment_id))
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")

    sub_result = await db.execute(
        select(Submission).where(Submission.assignment_id == assignment_id)
    )
    subs = sub_result.scalars().all()

    data = assignment.to_dict()

    if user.role == "student":
        my_sub = [s.to_dict() for s in subs if s.student_id == user.id]
        data["submissions"] = my_sub
    else:
        data["submissions"] = [s.to_dict() for s in subs]

    return data


@router.post("")
async def create_assignment(
    body: CreateAssignmentRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    assignment = Assignment(
        title=body.title, description=body.description, subject=body.subject,
        class_name=body.class_name, teacher_id=user.id,
        due_date=_parse_date(body.due_date), assignment_type=body.assignment_type,
        max_marks=body.max_marks, instructions=body.instructions,
    )
    db.add(assignment)
    await db.flush()

    # Notify students
    result = await db.execute(
        select(User).where(User.role == "student", User.class_name == body.class_name, User.is_active == True)
    )
    students = result.scalars().all()
    for s in students:
        db.add(Notification(
            user_id=s.id, title="New Assignment",
            message=f'New {body.assignment_type} assigned: "{body.title}" for {body.subject}',
            type="assignment", action_url=f"/assignments/{assignment.id}",
        ))

    await db.commit()
    await db.refresh(assignment)
    return assignment.to_dict()


@router.put("/{assignment_id}")
async def update_assignment(
    assignment_id: str,
    body: dict,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Assignment).where(Assignment.id == assignment_id))
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if assignment.teacher_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    for key, val in body.items():
        if not hasattr(assignment, key) or key in ("id", "created_at"):
            continue
        if key == "due_date":
            val = _parse_date(val)
        setattr(assignment, key, val)

    await db.commit()
    await db.refresh(assignment)
    return assignment.to_dict()


@router.delete("/{assignment_id}")
async def delete_assignment(
    assignment_id: str,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Assignment).where(Assignment.id == assignment_id))
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if assignment.teacher_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")

    assignment.is_active = False
    await db.commit()
    return {"message": "Assignment deleted"}


@router.post("/ai-generate")
async def generate_with_ai(
    body: AIGenerateRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        # generate_assignment_content already returns {"content": ..., "sources": ...}
        return await generate_assignment_content(
            {"topic": body.topic, "subject": body.subject, "class_level": body.class_level, "assignment_type": body.assignment_type},
            db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI generation failed: {str(e)}")


@router.post("/{assignment_id}/submit")
async def submit_assignment(
    assignment_id: str,
    content: str = Form(None),
    ai_generated: bool = Form(False),
    submission: UploadFile = File(None),
    user: User = Depends(require_roles("student")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Assignment).where(Assignment.id == assignment_id))
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if assignment.class_name != user.class_name:
        raise HTTPException(status_code=403, detail="This assignment is not for your class")

    # Check existing
    sub_result = await db.execute(
        select(Submission).where(
            Submission.assignment_id == assignment_id, Submission.student_id == user.id
        )
    )
    existing = sub_result.scalar_one_or_none()

    sub_data = {"content": content, "status": "submitted", "submitted_at": datetime.utcnow(), "ai_generated": ai_generated}

    if submission:
        import os, time, random
        upload_dir = os.path.join(UPLOAD_DIR, "submissions")
        os.makedirs(upload_dir, exist_ok=True)
        unique = f"{int(time.time())}-{random.randint(0, 999999999)}"
        ext = os.path.splitext(submission.filename)[1]
        file_path = os.path.join(upload_dir, f"sub-{unique}{ext}")
        file_content = await submission.read()
        with open(file_path, "wb") as f:
            f.write(file_content)
        sub_data["file_path"] = file_path
        sub_data["file_name"] = submission.filename

    if existing:
        for k, v in sub_data.items():
            setattr(existing, k, v)
        await db.commit()
        await db.refresh(existing)
        resp = existing
    else:
        new_sub = Submission(assignment_id=assignment_id, student_id=user.id, **sub_data)
        db.add(new_sub)
        await db.commit()
        await db.refresh(new_sub)
        resp = new_sub

    # Notify teacher
    db.add(Notification(
        user_id=assignment.teacher_id, title="Assignment Submitted",
        message=f'{user.name} submitted "{assignment.title}"', type="submission",
    ))
    await db.commit()

    return resp.to_dict()


@router.post("/grade")
async def grade_submission(
    body: GradeRequest,
    user: User = Depends(require_roles("teacher", "admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Submission).where(Submission.id == body.submission_id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Get assignment title for notification
    assign_result = await db.execute(select(Assignment).where(Assignment.id == sub.assignment_id))
    assignment = assign_result.scalar_one_or_none()

    sub.grade = body.grade
    sub.feedback = body.feedback
    sub.status = "graded"

    db.add(Notification(
        user_id=sub.student_id, title="Assignment Graded",
        message=f'Your submission for "{assignment.title}" has been graded: {body.grade}',
        type="grade",
    ))

    await db.commit()
    await db.refresh(sub)
    return sub.to_dict()

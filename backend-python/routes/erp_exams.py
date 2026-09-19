"""
Examinations API (ERP phase 7).

Configure an exam, enter marks, review, publish, print. Every derived number in
every response comes from `services/erp/results.py` — no percentage or grade is
computed here, so a ledger and a report card cannot disagree (§81.F).

Marks entry is authorised the same way classroom access always has been: a
teacher may enter marks for a class and subject they actually teach, checked
against their assignments rather than against a list they can choose from.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user
from models.erp import SchoolClass, Section, Subject, TeacherAssignment
from models.erp_exams import (
    EXAM_MARKS_ENTRY, EXAM_PLANNED, EXAM_PUBLISHED, EXAM_REVIEW, EXAM_TYPES,
    MARKS_APPROVED, MARKS_DRAFT, MARKS_LOCKED_STATES, MARKS_SUBMITTED,
    Exam, ExamSubject, GradeBand, GradeScale, Mark, ReportRemark,
    ResultScheme, SchemeComponent,
)
from models.models import User, utcnow
from routes.erp import erp_available
from services.erp import audit, events, results as results_engine
from services.erp.permissions import permissions_for, require_permission
from services.erp.results import ResultError
from services.erp.setup import current_session

router = APIRouter(prefix="/erp/exams", tags=["erp-exams"])


def _fail(exc: ResultError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ─── Exams ────────────────────────────────────────────────────────────────────

class ExamRequest(BaseModel):
    name: str
    exam_type: str = "monthly"
    sequence: int = 1
    start_date: date | None = None
    end_date: date | None = None


@router.get("")
async def list_exams(
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await current_session(db)
    if session is None:
        return {"exams": []}

    result = await db.execute(
        select(Exam).where(Exam.session_id == session.id)
        .order_by(Exam.sequence, Exam.name)
    )
    return {"session": session.to_dict(),
            "exams": [e.to_dict() for e in result.scalars().all()]}


@router.post("")
async def create_exam(
    body: ExamRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.configure")),
    db: AsyncSession = Depends(get_db),
):
    session = await current_session(db)
    if session is None:
        raise HTTPException(status_code=400, detail="There is no active academic session.")
    if body.exam_type not in EXAM_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown examination type: {body.exam_type}")

    result = await db.execute(
        select(Exam).where(Exam.session_id == session.id, Exam.name == body.name)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"{body.name} already exists this session.")

    exam = Exam(session_id=session.id, **body.model_dump())
    db.add(exam)
    await db.flush()
    audit.record(db, actor=user, entity_type="exam", action="created",
                 entity_id=exam.id, new_value=exam.to_dict())
    await db.commit()
    return exam.to_dict()


class ExamSubjectRequest(BaseModel):
    class_id: str
    subject_id: str
    max_marks: Decimal = Decimal("100")
    passing_marks: Decimal = Decimal("33")
    practical_max: Decimal = Decimal("0")
    practical_passing: Decimal = Decimal("0")
    exam_date: date | None = None
    is_optional: bool = False


@router.get("/{exam_id}/subjects")
async def list_exam_subjects(
    exam_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    class_id: str | None = None,
):
    stmt = (
        select(ExamSubject, Subject, SchoolClass)
        .join(Subject, Subject.id == ExamSubject.subject_id)
        .join(SchoolClass, SchoolClass.id == ExamSubject.class_id)
        .where(ExamSubject.exam_id == exam_id)
        .order_by(SchoolClass.sort_order, Subject.name)
    )
    if class_id:
        stmt = stmt.where(ExamSubject.class_id == class_id)

    result = await db.execute(stmt)
    return {
        "subjects": [
            {**exam_subject.to_dict(), "subject_name": subject.name,
             "class_name": school_class.canonical_name}
            for exam_subject, subject, school_class in result.all()
        ]
    }


@router.post("/{exam_id}/subjects")
async def add_exam_subject(
    exam_id: str,
    body: ExamSubjectRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.configure")),
    db: AsyncSession = Depends(get_db),
):
    if body.passing_marks > body.max_marks:
        raise HTTPException(status_code=400,
                            detail="The passing mark cannot be higher than the maximum.")

    result = await db.execute(
        select(ExamSubject).where(
            ExamSubject.exam_id == exam_id,
            ExamSubject.class_id == body.class_id,
            ExamSubject.subject_id == body.subject_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        for field, value in body.model_dump().items():
            setattr(existing, field, value)
        await db.commit()
        return existing.to_dict()

    exam_subject = ExamSubject(exam_id=exam_id, **body.model_dump())
    db.add(exam_subject)
    await db.flush()
    await db.commit()
    return exam_subject.to_dict()


@router.post("/{exam_id}/auto-subjects/{class_id}")
async def auto_add_subjects(
    exam_id: str,
    class_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.configure")),
    db: AsyncSession = Depends(get_db),
    max_marks: Decimal = Query(Decimal("100")),
    passing_marks: Decimal = Query(Decimal("33")),
):
    """Add every subject this class is taught, at the same marks.

    The specification's §72 in one endpoint: the system already knows which
    subjects a class studies, so it should not ask.
    """
    from models.erp import ClassSubject

    result = await db.execute(
        select(Subject)
        .join(ClassSubject, ClassSubject.subject_id == Subject.id)
        .where(ClassSubject.class_id == class_id)
    )
    subjects = list(result.scalars().all())

    # A class with no subject list yet falls back to what its teachers teach.
    if not subjects:
        session = await current_session(db)
        result = await db.execute(
            select(Subject)
            .join(TeacherAssignment, TeacherAssignment.subject_id == Subject.id)
            .where(
                TeacherAssignment.class_id == class_id,
                TeacherAssignment.session_id == (session.id if session else ""),
            )
            .distinct()
        )
        subjects = list(result.scalars().all())

    if not subjects:
        raise HTTPException(
            status_code=400,
            detail="No subjects are recorded for this class yet. Add them under Classes first.",
        )

    result = await db.execute(
        select(ExamSubject.subject_id).where(
            ExamSubject.exam_id == exam_id, ExamSubject.class_id == class_id,
        )
    )
    already = {row[0] for row in result.all()}

    added = 0
    for subject in subjects:
        if subject.id in already:
            continue
        db.add(ExamSubject(
            exam_id=exam_id, class_id=class_id, subject_id=subject.id,
            max_marks=max_marks, passing_marks=passing_marks,
        ))
        added += 1

    await db.commit()
    return {"added": added, "subjects": [s.name for s in subjects]}


# ─── Marks entry ──────────────────────────────────────────────────────────────

async def _may_enter_marks(db, user, exam_subject: ExamSubject) -> bool:
    held = await permissions_for(db, user)
    if "exam.marks.review" in held or user.role == "admin":
        return True
    if "exam.marks.enter" not in held:
        return False

    session = await current_session(db)
    result = await db.execute(
        select(TeacherAssignment).where(
            TeacherAssignment.session_id == (session.id if session else ""),
            TeacherAssignment.teacher_user_id == user.id,
            TeacherAssignment.class_id == exam_subject.class_id,
        )
    )
    assignments = list(result.scalars().all())
    if not assignments:
        return False
    # An assignment with no subject means the whole class; otherwise the
    # subject has to match.
    return any(a.subject_id in (None, exam_subject.subject_id) for a in assignments)


@router.get("/marks-sheet/{exam_subject_id}")
async def marks_sheet(
    exam_subject_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    section_id: str | None = None,
):
    """The class list with whatever marks are already entered."""
    result = await db.execute(select(ExamSubject).where(ExamSubject.id == exam_subject_id))
    exam_subject = result.scalar_one_or_none()
    if exam_subject is None:
        raise HTTPException(status_code=404, detail="That paper was not found.")
    if not await _may_enter_marks(db, user, exam_subject):
        raise HTTPException(status_code=403, detail="This is not one of your classes or subjects.")

    session = await current_session(db)
    from models.erp import Enrollment, StudentProfile

    stmt = (
        select(User, StudentProfile, Enrollment)
        .join(Enrollment, Enrollment.student_user_id == User.id)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .where(
            Enrollment.session_id == session.id,
            Enrollment.class_id == exam_subject.class_id,
            User.is_active.is_(True),
        )
        .order_by(User.name)
    )
    if section_id:
        stmt = stmt.where(Enrollment.section_id == section_id)

    result = await db.execute(stmt)
    students = result.all()

    result = await db.execute(select(Mark).where(Mark.exam_subject_id == exam_subject_id))
    marks = {m.student_user_id: m for m in result.scalars().all()}

    result = await db.execute(select(Subject).where(Subject.id == exam_subject.subject_id))
    subject = result.scalar_one_or_none()
    result = await db.execute(select(Exam).where(Exam.id == exam_subject.exam_id))
    exam = result.scalar_one_or_none()

    return {
        "exam": exam.to_dict() if exam else None,
        "subject": subject.name if subject else None,
        "max_marks": str(exam_subject.max_marks),
        "passing_marks": str(exam_subject.passing_marks),
        "practical_max": str(exam_subject.practical_max),
        "locked": any(m.status in MARKS_LOCKED_STATES for m in marks.values()),
        "students": [
            {
                "student_id": student.id,
                "name": student.name,
                "roll_no": enrollment.roll_no,
                "gr_no": profile.gr_no if profile else None,
                "obtained": str(marks[student.id].obtained)
                            if student.id in marks and marks[student.id].obtained is not None else "",
                "practical_obtained": str(marks[student.id].practical_obtained)
                            if student.id in marks and marks[student.id].practical_obtained is not None else "",
                "is_absent": bool(marks[student.id].is_absent) if student.id in marks else False,
                "is_exempt": bool(marks[student.id].is_exempt) if student.id in marks else False,
                "status": marks[student.id].status if student.id in marks else MARKS_DRAFT,
            }
            for student, profile, enrollment in students
        ],
    }


class MarkEntry(BaseModel):
    student_id: str
    obtained: Decimal | None = None
    practical_obtained: Decimal | None = None
    is_absent: bool = False
    is_exempt: bool = False


class SaveMarksRequest(BaseModel):
    exam_subject_id: str
    marks: list[MarkEntry]
    submit: bool = False


@router.post("/marks")
async def save_marks(
    body: SaveMarksRequest,
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a marks sheet, and optionally submit it for review.

    Validation is the point of this endpoint (§42): above maximum, negative,
    and a teacher entering marks for a class they do not teach. A wrong mark
    caught here is a correction; caught after publication it is a grievance.
    """
    result = await db.execute(select(ExamSubject).where(ExamSubject.id == body.exam_subject_id))
    exam_subject = result.scalar_one_or_none()
    if exam_subject is None:
        raise HTTPException(status_code=404, detail="That paper was not found.")
    if not await _may_enter_marks(db, user, exam_subject):
        raise HTTPException(status_code=403, detail="This is not one of your classes or subjects.")

    held = await permissions_for(db, user)
    maximum = exam_subject.max_marks
    practical_maximum = exam_subject.practical_max

    problems = []
    for entry in body.marks:
        if entry.is_absent or entry.is_exempt:
            continue
        if entry.obtained is None:
            continue
        if entry.obtained < 0:
            problems.append("Marks cannot be negative.")
        if entry.obtained > maximum:
            problems.append(f"{entry.obtained} is more than the maximum of {maximum}.")
        if entry.practical_obtained is not None and entry.practical_obtained > practical_maximum:
            problems.append(
                f"Practical {entry.practical_obtained} is more than the maximum of {practical_maximum}."
            )
    if problems:
        raise HTTPException(status_code=400, detail=problems[0])

    # §42: a mark must belong to a child who is actually in this class. Without
    # this check a stale browser tab, or a sheet left open while a student was
    # moved, silently writes marks for somebody who never sat the paper — and
    # they surface months later on a ledger nobody can explain.
    from models.erp import Enrollment

    session = await current_session(db)
    result = await db.execute(
        select(Enrollment.student_user_id).where(
            Enrollment.session_id == (session.id if session else ""),
            Enrollment.class_id == exam_subject.class_id,
        )
    )
    enrolled = {row[0] for row in result.all()}
    strangers = [e.student_id for e in body.marks if e.student_id not in enrolled]
    if strangers:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(strangers)} of these students are not in this class. "
                "Reload the marks sheet and try again."
            ),
        )

    result = await db.execute(select(Mark).where(Mark.exam_subject_id == body.exam_subject_id))
    existing = {m.student_user_id: m for m in result.scalars().all()}

    saved = 0
    for entry in body.marks:
        mark = existing.get(entry.student_id)
        if mark and mark.status == MARKS_APPROVED and "exam.marks.review" not in held:
            # Approved marks are not a teacher's to change. A correction goes
            # through review, with a reason.
            continue

        if mark is None:
            mark = Mark(exam_subject_id=body.exam_subject_id, student_user_id=entry.student_id)
            db.add(mark)

        mark.obtained = entry.obtained if not (entry.is_absent or entry.is_exempt) else None
        mark.practical_obtained = entry.practical_obtained \
            if not (entry.is_absent or entry.is_exempt) else None
        mark.is_absent = entry.is_absent
        mark.is_exempt = entry.is_exempt
        mark.entered_by = user.id
        mark.entered_at = utcnow()
        if body.submit:
            mark.status = MARKS_SUBMITTED
        saved += 1

    audit.record(
        db, actor=user, entity_type="marks",
        action="submitted" if body.submit else "saved",
        entity_id=body.exam_subject_id,
        new_value={"count": saved, "submitted": body.submit},
    )
    await db.commit()
    return {"saved": saved, "submitted": body.submit}


@router.post("/marks/{exam_subject_id}/approve")
async def approve_marks(
    exam_subject_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.marks.review")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Mark).where(Mark.exam_subject_id == exam_subject_id))
    marks = list(result.scalars().all())
    if not marks:
        raise HTTPException(status_code=400, detail="There are no marks to approve.")

    for mark in marks:
        mark.status = MARKS_APPROVED
        mark.approved_by = user.id
        mark.approved_at = utcnow()

    audit.record(db, actor=user, entity_type="marks", action="approved",
                 entity_id=exam_subject_id, new_value={"count": len(marks)})
    await db.commit()
    return {"approved": len(marks)}


@router.get("/{exam_id}/entry-status")
async def entry_status(
    exam_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.marks.review")),
    db: AsyncSession = Depends(get_db),
):
    """Which papers are still missing marks — the exceptions view for an exam."""
    result = await db.execute(
        select(ExamSubject, Subject, SchoolClass)
        .join(Subject, Subject.id == ExamSubject.subject_id)
        .join(SchoolClass, SchoolClass.id == ExamSubject.class_id)
        .where(ExamSubject.exam_id == exam_id)
        .order_by(SchoolClass.sort_order, Subject.name)
    )
    papers = result.all()

    result = await db.execute(
        select(Mark.exam_subject_id, Mark.status, func.count())
        .where(Mark.exam_subject_id.in_([p.id for p, _, _ in papers]))
        .group_by(Mark.exam_subject_id, Mark.status)
    ) if papers else None

    tally: dict[str, dict[str, int]] = {}
    if result is not None:
        for exam_subject_id, status, count in result.all():
            tally.setdefault(exam_subject_id, {})[status] = int(count)

    return {
        "papers": [
            {
                "exam_subject_id": exam_subject.id,
                "class_name": school_class.canonical_name,
                "subject": subject.name,
                "entered": sum(tally.get(exam_subject.id, {}).values()),
                "approved": tally.get(exam_subject.id, {}).get(MARKS_APPROVED, 0),
                "submitted": tally.get(exam_subject.id, {}).get(MARKS_SUBMITTED, 0),
            }
            for exam_subject, subject, school_class in papers
        ]
    }


@router.post("/{exam_id}/publish")
async def publish_exam(
    exam_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.publish")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalar_one_or_none()
    if exam is None:
        raise HTTPException(status_code=404, detail="That examination was not found.")

    exam.status = EXAM_PUBLISHED
    exam.published_at = utcnow()
    exam.published_by = user.id

    events.emit(db, events.RESULT_PUBLISHED,
                {"exam_id": exam.id, "name": exam.name},
                dedupe_key=f"result_published:{exam.id}")
    audit.record(db, actor=user, entity_type="exam", action="published",
                 entity_id=exam.id, new_value={"name": exam.name})
    await db.commit()
    return exam.to_dict()


# ─── Schemes ──────────────────────────────────────────────────────────────────

class SchemeRequest(BaseModel):
    name: str
    class_id: str | None = None
    show_position: bool = False
    components: list[dict] = []          # [{exam_id, weight_percent}]


@router.get("/schemes")
async def list_schemes(
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await current_session(db)
    if session is None:
        return {"schemes": []}

    result = await db.execute(
        select(ResultScheme).where(ResultScheme.session_id == session.id)
        .order_by(ResultScheme.name)
    )
    schemes = list(result.scalars().all())

    out = []
    for scheme in schemes:
        result = await db.execute(
            select(SchemeComponent, Exam)
            .join(Exam, Exam.id == SchemeComponent.exam_id)
            .where(SchemeComponent.scheme_id == scheme.id)
            .order_by(Exam.sequence)
        )
        components = result.all()
        out.append({
            **scheme.to_dict(),
            "components": [
                {"exam_id": c.exam_id, "exam": e.name, "weight_percent": str(c.weight_percent)}
                for c, e in components
            ],
            "weights_total": str(results_engine.validate_weights(components)),
        })
    return {"schemes": out}


@router.post("/schemes")
async def create_scheme(
    body: SchemeRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.configure")),
    db: AsyncSession = Depends(get_db),
):
    """Define how exams combine. Weights are checked but not forced here —
    a half-built scheme must still be saveable; the total bites at publication."""
    session = await current_session(db)
    if session is None:
        raise HTTPException(status_code=400, detail="There is no active academic session.")

    scheme = ResultScheme(
        session_id=session.id, name=body.name, class_id=body.class_id,
        show_position=body.show_position,
    )
    db.add(scheme)
    await db.flush()

    for component in body.components:
        db.add(SchemeComponent(
            scheme_id=scheme.id,
            exam_id=component["exam_id"],
            weight_percent=Decimal(str(component.get("weight_percent", 0))),
        ))

    audit.record(db, actor=user, entity_type="result_scheme", action="created",
                 entity_id=scheme.id,
                 new_value={"name": body.name, "components": body.components})
    await db.commit()
    return scheme.to_dict()


@router.put("/schemes/{scheme_id}")
async def update_scheme(
    scheme_id: str,
    body: SchemeRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.configure")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ResultScheme).where(ResultScheme.id == scheme_id))
    scheme = result.scalar_one_or_none()
    if scheme is None:
        raise HTTPException(status_code=404, detail="That scheme was not found.")

    scheme.name = body.name
    scheme.class_id = body.class_id
    scheme.show_position = body.show_position

    await db.execute(SchemeComponent.__table__.delete().where(
        SchemeComponent.scheme_id == scheme_id))
    for component in body.components:
        db.add(SchemeComponent(
            scheme_id=scheme_id,
            exam_id=component["exam_id"],
            weight_percent=Decimal(str(component.get("weight_percent", 0))),
        ))

    audit.record(db, actor=user, entity_type="result_scheme", action="updated",
                 entity_id=scheme_id, new_value={"components": body.components})
    await db.commit()
    return scheme.to_dict()


# ─── Ledgers and report cards ─────────────────────────────────────────────────

@router.get("/ledger/{exam_id}")
async def exam_ledger(
    exam_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.ledger")),
    db: AsyncSession = Depends(get_db),
    class_id: str = Query(...),
    section_id: str | None = None,
):
    try:
        return await results_engine.exam_ledger(
            db, exam_id=exam_id, class_id=class_id, section_id=section_id,
        )
    except ResultError as exc:
        raise _fail(exc)


@router.get("/combined-ledger/{scheme_id}")
async def combined_ledger(
    scheme_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.ledger")),
    db: AsyncSession = Depends(get_db),
    class_id: str = Query(...),
    section_id: str | None = None,
):
    try:
        return await results_engine.combined_ledger(
            db, scheme_id=scheme_id, class_id=class_id, section_id=section_id,
        )
    except ResultError as exc:
        raise _fail(exc)


@router.get("/report-card/{student_user_id}")
async def report_card(
    student_user_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    scheme_id: str | None = None,
    exam_id: str | None = None,
):
    """A report card. A student may read their own, once it is published."""
    held = await permissions_for(db, user)
    own = user.id == student_user_id
    if not own and "exam.ledger" not in held and "exam.publish" not in held:
        raise HTTPException(status_code=403, detail="You may only see your own report card.")

    if own and exam_id:
        result = await db.execute(select(Exam).where(Exam.id == exam_id))
        exam = result.scalar_one_or_none()
        if exam is None or exam.status != EXAM_PUBLISHED:
            raise HTTPException(status_code=404, detail="This result has not been published yet.")

    try:
        return await results_engine.report_card(
            db, student_user_id=student_user_id, scheme_id=scheme_id, exam_id=exam_id,
        )
    except ResultError as exc:
        raise _fail(exc)


class RemarkRequest(BaseModel):
    student_user_id: str
    scheme_id: str | None = None
    exam_id: str | None = None
    teacher_remark: str | None = None
    principal_remark: str | None = None
    promotion_status: str | None = None


@router.post("/remarks")
async def save_remark(
    body: RemarkRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("exam.marks.review")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ReportRemark).where(
            ReportRemark.student_user_id == body.student_user_id,
            ReportRemark.scheme_id == body.scheme_id,
            ReportRemark.exam_id == body.exam_id,
        )
    )
    remark = result.scalar_one_or_none()
    if remark is None:
        remark = ReportRemark(
            student_user_id=body.student_user_id,
            scheme_id=body.scheme_id, exam_id=body.exam_id,
        )
        db.add(remark)

    for field in ("teacher_remark", "principal_remark", "promotion_status"):
        value = getattr(body, field)
        if value is not None:
            setattr(remark, field, value)
    remark.written_by = user.id

    await db.commit()
    return remark.to_dict()


@router.get("/grade-scale")
async def grade_scale(
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bands = await results_engine.grade_bands(db)
    await db.commit()
    return {"bands": [b.to_dict() for b in bands]}

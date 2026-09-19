"""
The results engine (ERP phase 7).

Specification §81.F, stated plainly: there must never be a situation where the
combined ledger calculates one result and the combined report card calculates
another. The only way to guarantee that is for both to call the same function,
so this module is the *only* place in the ERP where a percentage, a grade or a
weighted mark is worked out. Not in a route, not in a PDF template, not in the
browser.

    marks entry → exam result → exam ledger → combined ledger
                → combined report card → academic analytics

Three rules decide the awkward cases, and they are the ones that turn into
complaints if they are wrong:

  * **Absent is not zero for averaging, but it is zero for a total.** A child
    who missed a paper scored nothing in it, and the class average should not
    be dragged down by a child who was in hospital.
  * **Exempt is excluded entirely** — from the total, from the maximum, and
    from the average. A child not taking Islamiat is not failing it.
  * **A subject is passed on its own marks**, and the overall result is failed
    if any non-exempt subject is failed. A 90% average with a 20% in
    mathematics is not a pass.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import Enrollment, SchoolClass, Section, StudentProfile, Subject
from models.erp_exams import (
    EXAM_PUBLISHED, Exam, ExamSubject, GradeBand, GradeScale, Mark,
    ReportRemark, ResultScheme, SchemeComponent,
)
from models.models import User
from services.erp.fees import ZERO, money
from services.erp.setup import current_session

logger = logging.getLogger("agent")

HUNDRED = Decimal("100")


class ResultError(RuntimeError):
    """Something the exam office needs to fix, phrased for them."""


def percent(obtained: Decimal, maximum: Decimal) -> Decimal:
    """A percentage to two places. Zero out of zero is zero, not an error."""
    if maximum is None or money(maximum) <= ZERO:
        return ZERO
    return money(money(obtained) * HUNDRED / money(maximum))


# ─── Grades ───────────────────────────────────────────────────────────────────

DEFAULT_BANDS = [
    ("80", "A+", "5.0", "Outstanding"),
    ("70", "A", "4.0", "Excellent"),
    ("60", "B", "3.5", "Very good"),
    ("50", "C", "3.0", "Good"),
    ("40", "D", "2.0", "Satisfactory"),
    ("33", "E", "1.0", "Pass"),
    ("0", "F", "0.0", "Needs improvement"),
]


async def ensure_grade_scale(db: AsyncSession) -> GradeScale:
    """The default scale, created on first use."""
    result = await db.execute(select(GradeScale).where(GradeScale.is_default.is_(True)))
    scale = result.scalar_one_or_none()
    if scale:
        return scale

    scale = GradeScale(name="LSS Standard", is_default=True)
    db.add(scale)
    await db.flush()
    for min_percent, grade, point, remark in DEFAULT_BANDS:
        db.add(GradeBand(
            scale_id=scale.id, min_percent=Decimal(min_percent),
            grade=grade, grade_point=Decimal(point), remark=remark,
        ))
    return scale


async def grade_bands(db: AsyncSession, scale_id: str | None = None) -> list[GradeBand]:
    if scale_id:
        result = await db.execute(
            select(GradeBand).where(GradeBand.scale_id == scale_id)
            .order_by(GradeBand.min_percent.desc())
        )
        bands = list(result.scalars().all())
        if bands:
            return bands

    scale = await ensure_grade_scale(db)
    result = await db.execute(
        select(GradeBand).where(GradeBand.scale_id == scale.id)
        .order_by(GradeBand.min_percent.desc())
    )
    return list(result.scalars().all())


def grade_for(bands: list[GradeBand], percentage: Decimal) -> dict:
    """The band a percentage falls into. Bands are sorted high to low."""
    for band in bands:
        if money(percentage) >= money(band.min_percent):
            return {"grade": band.grade,
                    "grade_point": str(band.grade_point) if band.grade_point is not None else None,
                    "remark": band.remark}
    return {"grade": "—", "grade_point": None, "remark": None}


# ─── One subject ──────────────────────────────────────────────────────────────

def subject_result(mark: Mark | None, exam_subject: ExamSubject) -> dict:
    """What one child got in one paper.

    Returns `counts` — whether this subject takes part in totals and averages
    at all. An exempt subject does not; an absent one counts as zero towards
    the total but is excluded from the class average.
    """
    maximum = money(exam_subject.max_marks) + money(exam_subject.practical_max)

    if mark is None:
        return {"obtained": None, "maximum": str(maximum), "percent": None,
                "status": "not_entered", "passed": None, "counts": False,
                "counts_in_average": False}

    if mark.is_exempt:
        return {"obtained": None, "maximum": "0.00", "percent": None,
                "status": "exempt", "passed": None, "counts": False,
                "counts_in_average": False}

    if mark.is_absent:
        return {"obtained": "0.00", "maximum": str(maximum), "percent": "0.00",
                "status": "absent", "passed": False, "counts": True,
                "counts_in_average": False}

    obtained = money(mark.obtained or 0) + money(mark.practical_obtained or 0)
    pct = percent(obtained, maximum)

    # A subject with a practical must be passed on both parts where the school
    # sets a practical pass mark — passing theory and failing the lab is a fail.
    passed = obtained >= money(exam_subject.passing_marks)
    if money(exam_subject.practical_max) > ZERO and money(exam_subject.practical_passing) > ZERO:
        passed = passed and money(mark.practical_obtained or 0) >= money(exam_subject.practical_passing)

    return {
        "obtained": str(obtained), "maximum": str(maximum),
        "percent": str(pct), "status": "marked", "passed": passed,
        "counts": True, "counts_in_average": True,
    }


# ─── One exam ─────────────────────────────────────────────────────────────────

async def exam_result(
    db: AsyncSession, *, exam_id: str, student_user_id: str, class_id: str,
    bands: list[GradeBand] | None = None,
) -> dict:
    """One child's whole result in one exam."""
    result = await db.execute(
        select(ExamSubject, Subject)
        .join(Subject, Subject.id == ExamSubject.subject_id)
        .where(ExamSubject.exam_id == exam_id, ExamSubject.class_id == class_id)
        .order_by(Subject.name)
    )
    papers = result.all()
    if not papers:
        return {"subjects": [], "obtained": "0.00", "total": "0.00",
                "percent": "0.00", "passed": None, "grade": "—"}

    result = await db.execute(
        select(Mark).where(
            Mark.exam_subject_id.in_([es.id for es, _ in papers]),
            Mark.student_user_id == student_user_id,
        )
    )
    marks = {m.exam_subject_id: m for m in result.scalars().all()}
    bands = bands if bands is not None else await grade_bands(db)

    subjects = []
    obtained_total = maximum_total = ZERO
    any_failed = False
    any_entered = False

    for exam_subject, subject in papers:
        detail = subject_result(marks.get(exam_subject.id), exam_subject)
        subjects.append({
            "subject_id": subject.id, "subject": subject.name,
            "exam_subject_id": exam_subject.id, **detail,
        })
        if not detail["counts"]:
            continue
        any_entered = True
        obtained_total += money(detail["obtained"] or 0)
        maximum_total += money(detail["maximum"])
        if detail["passed"] is False:
            any_failed = True

    pct = percent(obtained_total, maximum_total)
    return {
        "subjects": subjects,
        "obtained": str(obtained_total),
        "total": str(maximum_total),
        "percent": str(pct),
        # A high average with one failed subject is not a pass.
        "passed": (not any_failed) if any_entered else None,
        **grade_for(bands, pct),
    }


# ─── Combined results ─────────────────────────────────────────────────────────

async def scheme_with_components(db: AsyncSession, scheme_id: str) -> tuple[ResultScheme, list]:
    result = await db.execute(select(ResultScheme).where(ResultScheme.id == scheme_id))
    scheme = result.scalar_one_or_none()
    if scheme is None:
        raise ResultError("That result scheme was not found.")

    result = await db.execute(
        select(SchemeComponent, Exam)
        .join(Exam, Exam.id == SchemeComponent.exam_id)
        .where(SchemeComponent.scheme_id == scheme_id)
        .order_by(Exam.sequence)
    )
    return scheme, result.all()


def validate_weights(components) -> Decimal:
    """Weights must total 100 before a scheme may publish anything.

    Returned rather than raised so a half-built scheme can still be edited —
    the check bites at publication, not while somebody is typing.
    """
    return sum((money(c.weight_percent) for c, _ in components), ZERO)


async def combined_result(
    db: AsyncSession, *, scheme_id: str, student_user_id: str, class_id: str,
) -> dict:
    """One child's weighted result across several exams.

    Raw marks → each exam's percentage → its weight → weighted marks → the
    combined percentage. Every figure below is derived here and nowhere else,
    which is the whole point of §81.F.
    """
    scheme, components = await scheme_with_components(db, scheme_id)
    total_weight = validate_weights(components)
    bands = await grade_bands(db, scheme.grade_scale_id)

    per_exam = []
    weighted_total = ZERO
    subject_totals: dict[str, dict] = {}

    for component, exam in components:
        weight = money(component.weight_percent)
        result = await exam_result(
            db, exam_id=exam.id, student_user_id=student_user_id,
            class_id=class_id, bands=bands,
        )
        exam_percent = money(result["percent"])
        weighted = money(exam_percent * weight / HUNDRED)
        weighted_total += weighted

        per_exam.append({
            "exam_id": exam.id, "exam": exam.name,
            "obtained": result["obtained"], "total": result["total"],
            "percent": result["percent"],
            "weight": str(weight), "weighted": str(weighted),
        })

        # Subject-wise combining, for the ledger layout that shows each subject
        # across every exam.
        for subject in result["subjects"]:
            if not subject["counts"]:
                continue
            entry = subject_totals.setdefault(subject["subject_id"], {
                "subject": subject["subject"], "weighted": ZERO, "exams": {},
            })
            subject_percent = money(subject["percent"] or 0)
            entry["weighted"] += money(subject_percent * weight / HUNDRED)
            entry["exams"][exam.id] = subject["obtained"]

    combined_percent = money(weighted_total)
    return {
        "scheme": scheme.to_dict(),
        "weights_total": str(total_weight),
        "weights_valid": total_weight == HUNDRED,
        "exams": per_exam,
        "subjects": [
            {"subject": v["subject"], "weighted_percent": str(money(v["weighted"])),
             "by_exam": v["exams"]}
            for v in subject_totals.values()
        ],
        "percent": str(combined_percent),
        **grade_for(bands, combined_percent),
    }


# ─── Ledgers ──────────────────────────────────────────────────────────────────

async def _class_students(db, session_id, class_id, section_id):
    stmt = (
        select(User, StudentProfile, Enrollment)
        .join(Enrollment, Enrollment.student_user_id == User.id)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .where(Enrollment.session_id == session_id, Enrollment.class_id == class_id)
        .order_by(User.name)
    )
    if section_id:
        stmt = stmt.where(Enrollment.section_id == section_id)
    result = await db.execute(stmt)
    return result.all()


async def exam_ledger(
    db: AsyncSession, *, exam_id: str, class_id: str, section_id: str | None = None,
) -> dict:
    """The grid: every child down the side, every subject across the top.

    Subjects populate from the exam's configuration rather than a hard-coded
    list (§81.B), so a class that drops a subject simply has one fewer column.
    """
    session = await current_session(db)
    if session is None:
        raise ResultError("There is no active academic session.")

    result = await db.execute(select(Exam).where(Exam.id == exam_id))
    exam = result.scalar_one_or_none()
    if exam is None:
        raise ResultError("That examination was not found.")

    result = await db.execute(
        select(ExamSubject, Subject)
        .join(Subject, Subject.id == ExamSubject.subject_id)
        .where(ExamSubject.exam_id == exam_id, ExamSubject.class_id == class_id)
        .order_by(Subject.name)
    )
    papers = result.all()
    bands = await grade_bands(db)
    students = await _class_students(db, session.id, class_id, section_id)

    rows = []
    class_obtained = ZERO
    counted = 0
    passed_count = 0

    for student, profile, enrollment in students:
        result_row = await exam_result(
            db, exam_id=exam_id, student_user_id=student.id,
            class_id=class_id, bands=bands,
        )
        rows.append({
            "student_id": student.id,
            "gr_no": profile.gr_no if profile else None,
            "admission_no": profile.admission_no if profile else None,
            "roll_no": enrollment.roll_no,
            "name": student.name,
            "father_name": student.father_name,
            "subjects": {s["subject"]: s["obtained"] for s in result_row["subjects"]},
            "subject_status": {s["subject"]: s["status"] for s in result_row["subjects"]},
            "obtained": result_row["obtained"],
            "total": result_row["total"],
            "percent": result_row["percent"],
            "grade": result_row["grade"],
            "passed": result_row["passed"],
        })
        if result_row["passed"] is not None:
            counted += 1
            class_obtained += money(result_row["percent"])
            if result_row["passed"]:
                passed_count += 1

    return {
        "exam": exam.to_dict(),
        "subjects": [subject.name for _, subject in papers],
        "students": rows,
        "class_average": str(money(class_obtained / counted)) if counted else "0.00",
        "pass_percent": str(money(Decimal(passed_count) * HUNDRED / Decimal(counted)))
                        if counted else "0.00",
        "counted": counted,
    }


async def combined_ledger(
    db: AsyncSession, *, scheme_id: str, class_id: str, section_id: str | None = None,
) -> dict:
    """The same grid, weighted across several exams.

    Uses `combined_result` per child — the identical function the combined
    report card calls — so the two cannot disagree.
    """
    session = await current_session(db)
    if session is None:
        raise ResultError("There is no active academic session.")

    scheme, components = await scheme_with_components(db, scheme_id)
    students = await _class_students(db, session.id, class_id, section_id)

    rows = []
    for student, profile, enrollment in students:
        combined = await combined_result(
            db, scheme_id=scheme_id, student_user_id=student.id, class_id=class_id,
        )
        rows.append({
            "student_id": student.id,
            "gr_no": profile.gr_no if profile else None,
            "roll_no": enrollment.roll_no,
            "name": student.name,
            "father_name": student.father_name,
            "exams": combined["exams"],
            "subjects": combined["subjects"],
            "percent": combined["percent"],
            "grade": combined["grade"],
        })

    # Position is computed only when the scheme says to publish it (§81.E).
    if scheme.show_position:
        ordered = sorted(rows, key=lambda r: money(r["percent"]), reverse=True)
        for index, row in enumerate(ordered, start=1):
            row["position"] = index

    return {
        "scheme": scheme.to_dict(),
        "exams": [{"exam_id": c.exam_id, "name": e.name, "weight": str(c.weight_percent)}
                  for c, e in components],
        "weights_total": str(validate_weights(components)),
        "students": rows,
    }


# ─── Report card ──────────────────────────────────────────────────────────────

async def report_card(
    db: AsyncSession, *, student_user_id: str, scheme_id: str | None = None,
    exam_id: str | None = None,
) -> dict:
    """One child's report card — for a single exam, or combined.

    Calls the same engine as the ledger. There is no second calculation here
    and there must never be one.
    """
    session = await current_session(db)
    if session is None:
        raise ResultError("There is no active academic session.")

    result = await db.execute(
        select(Enrollment, SchoolClass, Section)
        .join(SchoolClass, SchoolClass.id == Enrollment.class_id)
        .join(Section, Section.id == Enrollment.section_id, isouter=True)
        .where(
            Enrollment.student_user_id == student_user_id,
            Enrollment.session_id == session.id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise ResultError("That student is not enrolled in the current session.")
    enrollment, school_class, section = row

    result = await db.execute(select(User).where(User.id == student_user_id))
    student = result.scalar_one()
    result = await db.execute(
        select(StudentProfile).where(StudentProfile.user_id == student_user_id)
    )
    profile = result.scalar_one_or_none()

    header = {
        "name": student.name,
        "father_name": student.father_name,
        "gr_no": profile.gr_no if profile else None,
        "admission_no": profile.admission_no if profile else None,
        "class_name": school_class.canonical_name,
        "section_name": section.name if section else None,
        "roll_no": enrollment.roll_no,
        "session": session.name,
    }

    if scheme_id:
        body = await combined_result(
            db, scheme_id=scheme_id, student_user_id=student_user_id,
            class_id=enrollment.class_id,
        )
        return {"student": header, "kind": "combined", **body}

    if exam_id:
        body = await exam_result(
            db, exam_id=exam_id, student_user_id=student_user_id,
            class_id=enrollment.class_id,
        )
        result = await db.execute(select(Exam).where(Exam.id == exam_id))
        exam = result.scalar_one_or_none()
        return {"student": header, "kind": "exam",
                "exam": exam.to_dict() if exam else None, **body}

    raise ResultError("Choose an examination or a combined result scheme.")

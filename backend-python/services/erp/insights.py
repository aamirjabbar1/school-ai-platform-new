"""
Management insights and the AI assistant's tools (ERP phase 8).

The dashboard and the assistant answer the same questions, so they read from
the same functions. Every function here is:

  * **Parameterised, never generated.** The assistant chooses which question to
    ask and with what arguments; it never writes SQL. A model that can compose
    a query against a school's payroll is a model that can compose the wrong
    one.
  * **Permission-checked as the asking user.** A coordinator asking about
    salaries gets exactly the refusal the screen would give them. The assistant
    is a different way in, not a way around.
  * **Honest about time.** Every answer carries what it is as at, because
    "how much did we collect today" means something different at 9am.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import (
    Enrollment, EmployeeProfile, Family, SchoolClass, Section, StudentProfile,
)
from models.erp_attendance import (
    ATT_ABSENT, PRESENT_STATUSES, AttendanceDay, AttendanceRecord,
)
from models.erp_exams import Exam, ExamSubject, Mark
from models.erp_fees import StudentFeeAccount
from models.erp_hr import PayrollRun, SalaryStructure
from models.models import User
from services.erp import attendance as attendance_service, fees as fee_service
from services.erp.fees import ZERO, money
from services.erp.setup import current_session

logger = logging.getLogger("agent")


# ─── The tools ────────────────────────────────────────────────────────────────
# Each entry says which permission it needs. The assistant is offered only the
# tools the asking user may actually use, so a refusal is usually invisible —
# it simply never had the option.

async def students_today(db: AsyncSession) -> dict:
    """How many students are on the roll."""
    session = await current_session(db)
    total = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.role == "student", User.is_active.is_(True))
    )).scalar_one()

    enrolled = 0
    if session:
        enrolled = (await db.execute(
            select(func.count()).select_from(Enrollment)
            .where(Enrollment.session_id == session.id)
        )).scalar_one()

    by_class = []
    if session:
        result = await db.execute(
            select(SchoolClass.canonical_name, func.count())
            .join(Enrollment, Enrollment.class_id == SchoolClass.id)
            .where(Enrollment.session_id == session.id)
            .group_by(SchoolClass.canonical_name, SchoolClass.sort_order)
            .order_by(SchoolClass.sort_order)
        )
        by_class = [{"class": row[0], "students": int(row[1])} for row in result.all()]

    return {"as_at": date.today().isoformat(), "active_students": total,
            "enrolled_this_session": enrolled, "by_class": by_class}


async def attendance_today(db: AsyncSession, *, on_date: date | None = None) -> dict:
    """Who is in school, and which registers are missing."""
    target = on_date or date.today()

    result = await db.execute(
        select(AttendanceRecord.status, func.count())
        .join(AttendanceDay, AttendanceDay.id == AttendanceRecord.day_id)
        .where(AttendanceDay.date == target)
        .group_by(AttendanceRecord.status)
    )
    counts = {row[0]: int(row[1]) for row in result.all()}
    marked = sum(counts.values())
    present = sum(counts.get(s, 0) for s in PRESENT_STATUSES)

    missing = await attendance_service.missing_registers(db, on_date=target)

    return {
        "as_at": target.isoformat(),
        "marked": marked,
        "present": present,
        "absent": counts.get(ATT_ABSENT, 0),
        "percentage": str(money(present * 100 / marked)) if marked else "0.00",
        "registers_not_taken": len(missing),
        "classes_missing": [m["label"] for m in missing[:10]],
    }


async def fee_position(db: AsyncSession, *, on_date: date | None = None) -> dict:
    """Collections and what is still owed."""
    return await fee_service.collection_summary(db, on_date=on_date)


async def defaulter_list(db: AsyncSession, *, limit: int = 20) -> dict:
    """Who owes money, worst first."""
    data = await fee_service.defaulters(db)
    return {
        "as_at": date.today().isoformat(),
        "count": data["total"],
        "total_outstanding": data["total_outstanding"],
        "aging": data.get("aging", {}),
        "students": [
            {"name": s["name"], "class": s["class_name"], "gr_no": s["gr_no"],
             "outstanding": s["outstanding"], "months": s["unpaid_months"]}
            for s in data["students"][:limit]
        ],
    }


async def payroll_position(db: AsyncSession) -> dict:
    """This month's payroll, and whether it has been approved."""
    result = await db.execute(select(PayrollRun).order_by(PayrollRun.month.desc()).limit(1))
    run = result.scalar_one_or_none()

    without_salary = (await db.execute(
        select(func.count()).select_from(User)
        .outerjoin(SalaryStructure, (SalaryStructure.employee_user_id == User.id)
                   & (SalaryStructure.is_active.is_(True)))
        .where(User.role.in_(("teacher", "admin")), User.is_active.is_(True),
               SalaryStructure.id.is_(None))
    )).scalar_one()

    return {
        "as_at": date.today().isoformat(),
        "latest_month": run.month.isoformat() if run else None,
        "status": run.status if run else "not generated",
        "employees": run.employee_count if run else 0,
        "total_net": str(run.total_net) if run else "0.00",
        "staff_without_salary": int(without_salary),
    }


async def exam_progress(db: AsyncSession) -> dict:
    """Which exams are running and how much marks entry is done."""
    session = await current_session(db)
    if session is None:
        return {"exams": []}

    result = await db.execute(
        select(Exam).where(Exam.session_id == session.id).order_by(Exam.sequence)
    )
    exams = list(result.scalars().all())

    out = []
    for exam in exams:
        papers = (await db.execute(
            select(func.count()).select_from(ExamSubject).where(ExamSubject.exam_id == exam.id)
        )).scalar_one()
        marked = (await db.execute(
            select(func.count(func.distinct(Mark.exam_subject_id)))
            .join(ExamSubject, ExamSubject.id == Mark.exam_subject_id)
            .where(ExamSubject.exam_id == exam.id)
        )).scalar_one()
        out.append({
            "exam": exam.name, "status": exam.status,
            "papers": int(papers), "papers_with_marks": int(marked),
        })

    return {"as_at": date.today().isoformat(), "exams": out}


async def staff_summary(db: AsyncSession) -> dict:
    """How many staff, and what is missing from their records."""
    total = (await db.execute(
        select(func.count()).select_from(User)
        .where(User.role.in_(("teacher", "admin")), User.is_active.is_(True))
    )).scalar_one()

    incomplete = (await db.execute(
        select(func.count()).select_from(EmployeeProfile)
        .where((EmployeeProfile.employee_no.is_(None))
               | (EmployeeProfile.cnic.is_(None))
               | (EmployeeProfile.joining_date.is_(None)))
    )).scalar_one()

    return {"as_at": date.today().isoformat(), "active_staff": int(total),
            "records_incomplete": int(incomplete)}


async def family_summary(db: AsyncSession) -> dict:
    """Families, and which have more than one child in the school."""
    total = (await db.execute(select(func.count()).select_from(Family))).scalar_one()

    result = await db.execute(
        select(StudentProfile.family_id, func.count())
        .where(StudentProfile.family_id.isnot(None))
        .group_by(StudentProfile.family_id)
        .having(func.count() > 1)
    )
    multi = result.all()

    return {"as_at": date.today().isoformat(), "families": int(total),
            "families_with_siblings": len(multi)}


# What the assistant may call, and what each needs.
TOOLS: dict[str, dict] = {
    "students_today": {
        "fn": students_today, "permission": "student.view",
        "description": "How many students are on the roll, and how many in each class.",
    },
    "attendance_today": {
        "fn": attendance_today, "permission": "attendance.view",
        "description": "Attendance for a date: present, absent, percentage, and which "
                       "classes have not taken the register. Takes an optional on_date.",
    },
    "fee_position": {
        "fn": fee_position, "permission": "fee.report",
        "description": "Fees collected today and this month, and total outstanding.",
    },
    "defaulter_list": {
        "fn": defaulter_list, "permission": "fee.report",
        "description": "Students who owe money, worst first, with aging.",
    },
    "payroll_position": {
        "fn": payroll_position, "permission": "payroll.report",
        "description": "The latest payroll month, its status and total, and how many "
                       "staff have no salary defined.",
    },
    "exam_progress": {
        "fn": exam_progress, "permission": "exam.ledger",
        "description": "Examinations this session and how much marks entry is done.",
    },
    "staff_summary": {
        "fn": staff_summary, "permission": "employee.view",
        "description": "How many staff are active and how many records are incomplete.",
    },
    "family_summary": {
        "fn": family_summary, "permission": "family.view",
        "description": "How many families, and how many have more than one child here.",
    },
}


def tools_for(held: set[str]) -> list[str]:
    """The tools this user may use. Everything else is simply not offered."""
    return [name for name, spec in TOOLS.items() if spec["permission"] in held]


# ─── The dashboard ────────────────────────────────────────────────────────────

async def management_dashboard(db: AsyncSession, held: set[str]) -> dict:
    """Everything the Owner sees on one screen — and only what they may see.

    Each panel is fetched only if the caller holds its permission, so the
    Preschool Head's dashboard is not the Owner's dashboard with holes in it;
    it is a shorter dashboard.
    """
    panels: dict = {"as_at": date.today().isoformat()}

    if "student.view" in held:
        panels["students"] = await students_today(db)
    if "attendance.view" in held:
        panels["attendance"] = await attendance_today(db)
    if "fee.report" in held:
        panels["fees"] = await fee_position(db)
    if "payroll.report" in held:
        panels["payroll"] = await payroll_position(db)
    if "exam.ledger" in held:
        panels["exams"] = await exam_progress(db)
    if "employee.view" in held:
        panels["staff"] = await staff_summary(db)
    if "family.view" in held:
        panels["families"] = await family_summary(db)

    return panels


# ─── Exceptions ───────────────────────────────────────────────────────────────

async def exceptions(db: AsyncSession, held: set[str]) -> list[dict]:
    """What needs a human today, across every module (§73).

    Ordered by how much it costs to ignore: money and missing registers first,
    incomplete records last.
    """
    items: list[dict] = []

    if "attendance.view" in held:
        missing = await attendance_service.missing_registers(db, on_date=date.today())
        if missing:
            items.append({
                "key": "attendance_missing", "severity": "high",
                "count": len(missing),
                "label": "classes have not taken the register today",
                "detail": ", ".join(m["label"] for m in missing[:6]),
                "link": "/erp/attendance",
            })

    if "fee.report" in held:
        result = await db.execute(
            select(func.count(), func.coalesce(func.sum(StudentFeeAccount.outstanding), 0))
            .select_from(StudentFeeAccount)
            .join(User, User.id == StudentFeeAccount.student_user_id)
            .where(StudentFeeAccount.outstanding > 0, User.is_active.is_(True))
        )
        count, total = result.one()
        if count:
            items.append({
                "key": "fee_defaulters", "severity": "high",
                "count": int(count),
                "label": "students owe fees",
                "detail": f"Rs {money(total):,} outstanding",
                "link": "/erp/defaulters",
            })

    if "payroll.report" in held:
        payroll = await payroll_position(db)
        if payroll["staff_without_salary"]:
            items.append({
                "key": "payroll_no_salary", "severity": "medium",
                "count": payroll["staff_without_salary"],
                "label": "staff have no salary defined",
                "detail": "They are skipped by payroll until one is set.",
                "link": "/erp/payroll",
            })

    if "exam.ledger" in held:
        progress = await exam_progress(db)
        pending = [e for e in progress.get("exams", [])
                   if e["papers"] and e["papers_with_marks"] < e["papers"]]
        if pending:
            items.append({
                "key": "marks_missing", "severity": "medium",
                "count": sum(e["papers"] - e["papers_with_marks"] for e in pending),
                "label": "papers still have no marks",
                "detail": ", ".join(e["exam"] for e in pending[:3]),
                "link": "/erp/results",
            })

    if "student.view" in held:
        no_gr = (await db.execute(
            select(func.count()).select_from(StudentProfile)
            .where(StudentProfile.gr_no.is_(None))
        )).scalar_one()
        if no_gr:
            items.append({
                "key": "gr_numbers", "severity": "low",
                "count": int(no_gr),
                "label": "students have no GR number",
                "detail": "Enter them from the register, or allocate them.",
                "link": "/erp/students",
            })

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(items, key=lambda i: order[i["severity"]])

"""
Daily attendance (ERP phase 3).

The flow the specification asks for is four taps: open, see the class, tap the
absentees, save. Everything here exists to make those four taps possible on a
phone in a corridor with one bar of signal.

Which means the work happens on this side:

  * The roster is built from enrolment, not typed.
  * Everyone starts present, because in a class of twenty-four, three are away.
    Defaulting to absent would mean twenty-one taps instead of three.
  * A register already taken comes back as it was saved, so re-opening it is
    editing rather than starting again.
  * Where an online class ran, presence derived from the media server is
    offered as a *suggestion* the teacher accepts or overrides — never as the
    register itself.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import Enrollment, SchoolClass, Section, StudentProfile, TeacherAssignment
from models.erp_attendance import (
    ATT_ABSENT, ATT_PRESENT, ATT_SOURCE_CORRECTION, ATT_SOURCE_TEACHER,
    ATTENDANCE_STATUSES, DAY_SUBMITTED, PRESENT_STATUSES,
    AttendanceDay, AttendanceRecord,
)
from models.models import User, utcnow
from models.online_classes import (
    ATTEND_LATE, ATTEND_PARTIAL, ATTEND_PRESENT,
    OnlineClassParticipant, OnlineClassSession,
)
from services import class_matching
from services.erp import audit
from services.erp.setup import current_session

logger = logging.getLogger("agent")


class AttendanceError(RuntimeError):
    """Something the teacher needs to know, phrased for the teacher."""


# ─── What a teacher teaches ───────────────────────────────────────────────────

async def classes_for_teacher(db: AsyncSession, teacher: User) -> list[dict]:
    """The classes this teacher may take a register for.

    Reads the ERP's assignment rows first. Falls back to the legacy JSON on
    `users` when a teacher has no assignment rows yet — the same columns
    classroom authorization has always used, so a teacher is never locked out
    of attendance because setup could not map their class.
    """
    session = await current_session(db)
    if session is None:
        return []

    result = await db.execute(
        select(TeacherAssignment.class_id, TeacherAssignment.section_id)
        .where(
            TeacherAssignment.session_id == session.id,
            TeacherAssignment.teacher_user_id == teacher.id,
        )
        .distinct()
    )
    pairs = {(row[0], row[1]) for row in result.all()}

    if not pairs:
        pairs = await _legacy_pairs(db, teacher)

    if not pairs:
        return []

    class_ids = {c for c, _ in pairs}
    result = await db.execute(select(SchoolClass).where(SchoolClass.id.in_(class_ids)))
    classes = {c.id: c for c in result.scalars().all()}

    result = await db.execute(select(Section).where(Section.class_id.in_(class_ids)))
    sections = {s.id: s for s in result.scalars().all()}

    # Roll counts, so the teacher sees "Class 5 — A · 24 children" before tapping.
    result = await db.execute(
        select(Enrollment.class_id, Enrollment.section_id, func.count())
        .where(Enrollment.session_id == session.id)
        .group_by(Enrollment.class_id, Enrollment.section_id)
    )
    counts = {(row[0], row[1]): int(row[2]) for row in result.all()}

    out = []
    for class_id, section_id in sorted(pairs, key=lambda p: (classes[p[0]].sort_order if p[0] in classes else 99)):
        school_class = classes.get(class_id)
        if school_class is None:
            continue
        section = sections.get(section_id) if section_id else None
        out.append({
            "class_id": class_id,
            "class_name": school_class.canonical_name,
            "section_id": section_id,
            "section_name": section.name if section else None,
            "students": counts.get((class_id, section_id), 0),
            "label": f"{school_class.canonical_name}{f' — {section.name}' if section else ''}",
        })
    return out


async def _legacy_pairs(db: AsyncSession, teacher: User) -> set[tuple[str, str | None]]:
    """Class/section pairs from the JSON columns on `users`."""
    result = await db.execute(select(SchoolClass))
    by_key = {class_matching.class_key(c.canonical_name): c for c in result.scalars().all()}

    result = await db.execute(select(Section))
    sections = list(result.scalars().all())

    pairs: set[tuple[str, str | None]] = set()

    for combined in (teacher.assigned_sections or []):
        text = str(combined)
        school_class = by_key.get(class_matching.class_key(text))
        if school_class is None:
            continue
        label = text.split(" - ")[-1] if " - " in text else None
        section = next(
            (s for s in sections
             if s.class_id == school_class.id
             and class_matching.section_key(s.name) == class_matching.section_key(label)),
            None,
        ) if label else None
        pairs.add((school_class.id, section.id if section else None))

    for class_name in (teacher.assigned_classes or []):
        school_class = by_key.get(class_matching.class_key(str(class_name)))
        if school_class and not any(c == school_class.id for c, _ in pairs):
            pairs.add((school_class.id, None))

    return pairs


async def may_take_register(db: AsyncSession, user: User, class_id: str, section_id: str | None) -> bool:
    """Anyone with attendance.view over the school may look; a teacher may only
    take the register for a class they actually teach."""
    if user.role == "admin":
        return True
    for entry in await classes_for_teacher(db, user):
        if entry["class_id"] == class_id:
            # A teacher assigned to the whole class may take any section of it.
            if entry["section_id"] in (None, section_id):
                return True
    return False


# ─── The register ─────────────────────────────────────────────────────────────

async def roster(
    db: AsyncSession,
    *,
    class_id: str,
    section_id: str | None,
    on_date: date,
) -> dict:
    """The children in a class, with whatever has already been marked.

    Returns everything the screen needs in one call — the list, what each child
    is currently marked as, whether the register was already taken, and any
    suggestion from an online class that ran the same day.
    """
    session = await current_session(db)
    if session is None:
        raise AttendanceError("There is no active academic session.")

    stmt = (
        select(User, StudentProfile, Enrollment)
        .join(Enrollment, Enrollment.student_user_id == User.id)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .where(
            Enrollment.session_id == session.id,
            Enrollment.class_id == class_id,
            User.is_active.is_(True),
        )
        .order_by(User.name)
    )
    if section_id:
        stmt = stmt.where(Enrollment.section_id == section_id)

    result = await db.execute(stmt)
    rows = result.all()

    day = await _find_day(db, session.id, class_id, section_id, on_date)
    marked: dict[str, AttendanceRecord] = {}
    if day:
        result = await db.execute(select(AttendanceRecord).where(AttendanceRecord.day_id == day.id))
        marked = {r.student_user_id: r for r in result.scalars().all()}

    suggestions = {} if day else await _online_suggestions(db, class_id, section_id, on_date)

    students = []
    for student, profile, enrollment in rows:
        record = marked.get(student.id)
        students.append({
            "id": student.id,
            "name": student.name,
            "father_name": student.father_name,
            "gr_no": profile.gr_no if profile else None,
            "roll_no": enrollment.roll_no,
            # Already marked → what it was. Never marked → present, because in a
            # class of twenty-four, three are away.
            "status": record.status if record else suggestions.get(student.id, ATT_PRESENT),
            "note": record.note if record else None,
            "suggested": student.id in suggestions and record is None,
        })

    return {
        "date": on_date.isoformat(),
        "class_id": class_id,
        "section_id": section_id,
        "already_taken": day is not None,
        "taken_at": day.marked_at.isoformat() if day and day.marked_at else None,
        "from_online_class": bool(suggestions) and day is None,
        "students": students,
    }


async def _find_day(db, session_id, class_id, section_id, on_date) -> AttendanceDay | None:
    stmt = select(AttendanceDay).where(
        AttendanceDay.session_id == session_id,
        AttendanceDay.class_id == class_id,
        AttendanceDay.date == on_date,
    )
    stmt = stmt.where(AttendanceDay.section_id == section_id) if section_id \
        else stmt.where(AttendanceDay.section_id.is_(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _online_suggestions(db, class_id, section_id, on_date) -> dict[str, str]:
    """Presence the media server already worked out, offered as a suggestion.

    `services/attendance_service.py` derives this from join and leave webhooks
    and has done since Online Classes shipped. Re-deriving it here would be a
    second opinion nobody asked for, so this reads its conclusion.
    """
    result = await db.execute(select(SchoolClass).where(SchoolClass.id == class_id))
    school_class = result.scalar_one_or_none()
    if school_class is None:
        return {}

    result = await db.execute(select(Section).where(Section.id == section_id)) if section_id else None
    section = result.scalar_one_or_none() if result is not None else None

    start = on_date
    end = on_date + timedelta(days=1)
    result = await db.execute(
        select(OnlineClassSession).where(
            OnlineClassSession.actual_start >= start,
            OnlineClassSession.actual_start < end,
        )
    )
    sessions = [
        s for s in result.scalars().all()
        if class_matching.same_class(s.class_name, school_class.canonical_name)
        and (section is None or class_matching.same_section(s.section, section.name))
    ]
    if not sessions:
        return {}

    result = await db.execute(
        select(OnlineClassParticipant)
        .where(OnlineClassParticipant.session_id.in_([s.id for s in sessions]))
    )
    suggestions: dict[str, str] = {}
    for participant in result.scalars().all():
        if participant.role != "student":
            continue
        # A child credited present in any of the day's classes is present.
        status = ATT_PRESENT if participant.status in (
            ATTEND_PRESENT, ATTEND_LATE, ATTEND_PARTIAL,
        ) else ATT_ABSENT
        if suggestions.get(participant.user_id) != ATT_PRESENT:
            suggestions[participant.user_id] = status
    return suggestions


async def save_register(
    db: AsyncSession,
    *,
    class_id: str,
    section_id: str | None,
    on_date: date,
    marks: list[dict],
    actor: User,
) -> dict:
    """Write the register. Re-saving the same day is an edit, not a duplicate."""
    session = await current_session(db)
    if session is None:
        raise AttendanceError("There is no active academic session.")

    if on_date > date.today():
        raise AttendanceError("You cannot take attendance for a day that has not happened yet.")

    unknown = {m.get("status") for m in marks} - set(ATTENDANCE_STATUSES)
    if unknown:
        raise AttendanceError(f"Unknown attendance status: {', '.join(sorted(str(u) for u in unknown))}")

    day = await _find_day(db, session.id, class_id, section_id, on_date)
    is_correction = day is not None

    if day is None:
        day = AttendanceDay(
            session_id=session.id, class_id=class_id, section_id=section_id,
            date=on_date, status=DAY_SUBMITTED,
        )
        db.add(day)
        await db.flush()

    day.marked_by = actor.id
    day.marked_at = utcnow()

    result = await db.execute(select(AttendanceRecord).where(AttendanceRecord.day_id == day.id))
    existing = {r.student_user_id: r for r in result.scalars().all()}

    changed = []
    for mark in marks:
        student_id = mark.get("student_id")
        status = mark.get("status")
        if not student_id or not status:
            continue

        record = existing.get(student_id)
        if record is None:
            db.add(AttendanceRecord(
                day_id=day.id, student_user_id=student_id, status=status,
                note=mark.get("note"), marked_by=actor.id,
                source=ATT_SOURCE_TEACHER,
            ))
        elif record.status != status or record.note != mark.get("note"):
            changed.append({"student_id": student_id, "from": record.status, "to": status})
            record.status = status
            record.note = mark.get("note")
            record.marked_by = actor.id
            record.source = ATT_SOURCE_CORRECTION if is_correction else ATT_SOURCE_TEACHER

    present = sum(1 for m in marks if m.get("status") in PRESENT_STATUSES)
    audit.record(
        db, actor=actor, entity_type="attendance",
        action="corrected" if is_correction else "marked",
        entity_id=day.id,
        new_value={
            "date": on_date.isoformat(), "class_id": class_id, "section_id": section_id,
            "present": present, "absent": len(marks) - present,
            "changes": changed[:50] or None,
        },
    )

    return {
        "day_id": day.id,
        "date": on_date.isoformat(),
        "present": present,
        "absent": len(marks) - present,
        "total": len(marks),
        "corrected": is_correction,
    }


# ─── Reports ──────────────────────────────────────────────────────────────────

async def missing_registers(db: AsyncSession, *, on_date: date) -> list[dict]:
    """Which classes have not taken the register today.

    The one report that makes this module enforce itself: it is short, it is
    actionable, and it is empty on a good day.
    """
    session = await current_session(db)
    if session is None:
        return []

    result = await db.execute(
        select(Enrollment.class_id, Enrollment.section_id, func.count())
        .where(Enrollment.session_id == session.id)
        .group_by(Enrollment.class_id, Enrollment.section_id)
    )
    expected = {(row[0], row[1]): int(row[2]) for row in result.all()}

    result = await db.execute(
        select(AttendanceDay.class_id, AttendanceDay.section_id)
        .where(AttendanceDay.session_id == session.id, AttendanceDay.date == on_date)
    )
    taken = {(row[0], row[1]) for row in result.all()}

    missing_keys = [k for k in expected if k not in taken]
    if not missing_keys:
        return []

    result = await db.execute(select(SchoolClass))
    classes = {c.id: c for c in result.scalars().all()}
    result = await db.execute(select(Section))
    sections = {s.id: s for s in result.scalars().all()}

    out = []
    for (class_id, section_id) in missing_keys:
        school_class = classes.get(class_id)
        if school_class is None:
            continue
        section = sections.get(section_id) if section_id else None
        out.append({
            "class_id": class_id, "section_id": section_id,
            "label": f"{school_class.canonical_name}{f' — {section.name}' if section else ''}",
            "students": expected[(class_id, section_id)],
            "sort": school_class.sort_order,
        })
    return sorted(out, key=lambda r: r["sort"])


async def student_summary(
    db: AsyncSession, *, student_user_id: str, from_date: date, to_date: date,
) -> dict:
    """One child's attendance over a period, with the percentage report cards use."""
    result = await db.execute(
        select(AttendanceRecord.status, func.count())
        .join(AttendanceDay, AttendanceDay.id == AttendanceRecord.day_id)
        .where(
            AttendanceRecord.student_user_id == student_user_id,
            AttendanceDay.date >= from_date,
            AttendanceDay.date <= to_date,
        )
        .group_by(AttendanceRecord.status)
    )
    counts = {row[0]: int(row[1]) for row in result.all()}
    total = sum(counts.values())
    present = sum(counts.get(s, 0) for s in PRESENT_STATUSES)

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "days_marked": total,
        "present": present,
        "absent": counts.get(ATT_ABSENT, 0),
        "leave": counts.get("leave", 0),
        "late": counts.get("late", 0),
        # Zero days marked is 0%, not 100%. A child with no register taken has
        # no attendance record, and saying otherwise would put a fictional
        # figure on a report card.
        "percentage": round(present * 100 / total, 1) if total else 0.0,
        "by_status": counts,
    }


async def class_summary(
    db: AsyncSession, *, class_id: str, section_id: str | None,
    from_date: date, to_date: date,
) -> list[dict]:
    """Every child in a class, with their percentage — the class-wise report."""
    session = await current_session(db)
    if session is None:
        return []

    stmt = (
        select(User, StudentProfile)
        .join(Enrollment, Enrollment.student_user_id == User.id)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .where(Enrollment.session_id == session.id, Enrollment.class_id == class_id)
        .order_by(User.name)
    )
    if section_id:
        stmt = stmt.where(Enrollment.section_id == section_id)
    result = await db.execute(stmt)
    students = result.all()
    if not students:
        return []

    # One aggregate for the whole class rather than one query per child.
    result = await db.execute(
        select(AttendanceRecord.student_user_id, AttendanceRecord.status, func.count())
        .join(AttendanceDay, AttendanceDay.id == AttendanceRecord.day_id)
        .where(
            AttendanceRecord.student_user_id.in_([s.id for s, _ in students]),
            AttendanceDay.date >= from_date,
            AttendanceDay.date <= to_date,
        )
        .group_by(AttendanceRecord.student_user_id, AttendanceRecord.status)
    )
    tally: dict[str, dict[str, int]] = {}
    for student_id, status, count in result.all():
        tally.setdefault(student_id, {})[status] = int(count)

    out = []
    for student, profile in students:
        counts = tally.get(student.id, {})
        total = sum(counts.values())
        present = sum(counts.get(s, 0) for s in PRESENT_STATUSES)
        out.append({
            "id": student.id,
            "name": student.name,
            "gr_no": profile.gr_no if profile else None,
            "days_marked": total,
            "present": present,
            "absent": counts.get(ATT_ABSENT, 0),
            "percentage": round(present * 100 / total, 1) if total else 0.0,
        })
    return out

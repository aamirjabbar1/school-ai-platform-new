"""
School setup: turning the existing LSS Bot into an ERP without re-entry.

This is the module that honours specification §3 and §4 — existing students
*become* ERP students, existing teachers *become* ERP employees, and nobody
retypes anything the platform already knows.

It works in two beats, because a school should never be asked to approve
something it cannot see first:

    analyze()  →  "here is exactly what I will create, and what I cannot work out"
    run()      →  do it

Both are idempotent. Running setup twice creates nothing the second time,
which matters because the office *will* press the button twice.

Nothing here writes to `users`, and nothing deletes. Every legacy column — the
free-text `class_name`, the `assigned_classes` JSON that classroom
authorization depends on — is left exactly as it is and keeps working.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import (
    SOURCE_LEGACY, STUDENT_ACTIVE, SESSION_ACTIVE, ENROLL_ENROLLED,
    AcademicSession, ClassAlias, ClassSubject, Enrollment, EmployeeProfile,
    FeatureFlag, NumberSeries, Role, RolePermission, SchoolClass, Section,
    StudentProfile, Subject, TeacherAssignment, UserRole,
)
from models.models import User
from services import class_matching
from services.erp import audit, numbering
from services.erp.permissions import PERMISSIONS, ROLE_DEFINITIONS
from services.student_excel_import_service import (
    CANONICAL_CLASSES, normalize_class, normalize_section,
)

logger = logging.getLogger("agent")


# Every table that stores a class as free text. Gathering the spellings from
# all of them is what makes the alias table complete enough to be trusted.
_CLASS_SOURCES = [
    ("users", "class_name"),
    ("assignments", "class_name"),
    ("question_papers", "class_name"),
    ("lesson_plans", "class_name"),
    ("documents", "class_level"),
    ("online_class_schedules", "class_name"),
    ("online_class_sessions", "class_name"),
    ("online_class_participants", "class_name"),
    ("ai_usage_events", "class_name"),
]

FLAG_ERP = "erp"


def _level_for(canonical: str) -> str:
    if canonical in ("Pre-Nursery", "Nursery", "KG"):
        return "pre_primary"
    try:
        n = int(canonical.replace("Class ", ""))
    except ValueError:
        return "other"
    if n <= 5:
        return "primary"
    if n <= 8:
        return "middle"
    return "secondary"


def _sort_order_for(canonical: str) -> int:
    try:
        return CANONICAL_CLASSES.index(canonical)
    except ValueError:
        return 99


# ─── Bootstrap: static data the ERP cannot run without ────────────────────────

async def bootstrap(db: AsyncSession) -> dict:
    """Seed roles, permissions, number series and the module flag.

    Idempotent and safe to run on every boot: it adds what is missing and
    leaves everything else alone. Permissions for system roles are re-synced,
    so adding a permission to the catalogue reaches existing roles without a
    migration.
    """
    created = {"roles": 0, "permissions": 0, "series": 0, "flags": 0}

    # Roles + their permissions
    for definition in ROLE_DEFINITIONS:
        result = await db.execute(select(Role).where(Role.key == definition["key"]))
        role = result.scalar_one_or_none()
        if role is None:
            role = Role(
                key=definition["key"], name=definition["name"],
                description=definition["description"], rank=definition["rank"],
                is_system=definition["is_system"],
            )
            db.add(role)
            await db.flush()
            created["roles"] += 1

        wanted = {p for p in definition["permissions"] if p in PERMISSIONS}
        result = await db.execute(
            select(RolePermission.permission_key).where(RolePermission.role_id == role.id)
        )
        held = {row[0] for row in result.all()}

        for key in wanted - held:
            db.add(RolePermission(role_id=role.id, permission_key=key))
            created["permissions"] += 1
        # A permission removed from the catalogue is removed from the role too,
        # so the code stays the single source of truth for a system role.
        for key in held - wanted:
            await db.execute(
                text("DELETE FROM role_permissions WHERE role_id = :r AND permission_key = :k"),
                {"r": role.id, "k": key},
            )

    # Number series
    for scope, label, pattern, start in numbering.DEFAULT_SERIES:
        result = await db.execute(select(NumberSeries).where(NumberSeries.scope == scope))
        if result.scalar_one_or_none() is None:
            db.add(NumberSeries(scope=scope, label=label, pattern=pattern, next_value=start))
            created["series"] += 1

    # The module flag. Off by default: the ERP must not appear for 755 students
    # on the day it deploys.
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.key == FLAG_ERP))
    if result.scalar_one_or_none() is None:
        db.add(FeatureFlag(
            key=FLAG_ERP, enabled=False, roles=[],
            note="School ERP. While off, only accounts that can manage flags see it.",
        ))
        created["flags"] += 1

    await db.commit()
    return created


async def grant_owner_to_existing_admins(db: AsyncSession) -> int:
    """Give every existing `admin` account the Owner role, once.

    Without this nobody can open the ERP on the day it deploys — the Owner
    account described in the specification does not exist yet, and seeding a
    password from source is exactly the practice this project is trying to
    stop. The people who administer LSS Bot today administer the ERP today.
    """
    result = await db.execute(select(Role).where(Role.key == "owner"))
    owner_role = result.scalar_one_or_none()
    if owner_role is None:
        return 0

    result = await db.execute(select(User).where(User.role == "admin", User.is_active.is_(True)))
    admins = list(result.scalars().all())

    granted = 0
    for admin in admins:
        result = await db.execute(
            select(UserRole).where(UserRole.user_id == admin.id, UserRole.role_id == owner_role.id)
        )
        if result.scalar_one_or_none() is None:
            db.add(UserRole(user_id=admin.id, role_id=owner_role.id))
            granted += 1

    if granted:
        await db.commit()
    return granted


# ─── Analysis: what setup would do ────────────────────────────────────────────

async def _distinct_class_strings(db: AsyncSession) -> dict[str, int]:
    """Every spelling of a class anywhere in the platform, with row counts."""
    found: dict[str, int] = {}
    for table, column in _CLASS_SOURCES:
        try:
            result = await db.execute(text(
                f"SELECT {column} AS v, count(*) AS n FROM {table} "
                f"WHERE {column} IS NOT NULL AND {column} <> '' GROUP BY 1"
            ))
        except Exception:
            # A table that does not exist yet (or a column renamed later) must
            # not stop setup. The rest of the scan is still worth having.
            await db.rollback()
            continue
        for value, count in result.all():
            found[value] = found.get(value, 0) + int(count)
    return found


async def analyze(db: AsyncSession) -> dict:
    """A dry run. Nothing is written.

    The shape of the answer is deliberately the shape of the screen: counts the
    office recognises, plus an explicit list of what could not be worked out.
    """
    class_strings = await _distinct_class_strings(db)

    resolved: dict[str, list[str]] = {}
    unresolved: list[dict] = []
    for raw, count in sorted(class_strings.items(), key=lambda kv: -kv[1]):
        canonical = normalize_class(raw)
        if canonical:
            resolved.setdefault(canonical, []).append(raw)
        else:
            unresolved.append({"value": raw, "rows": count})

    students = (await db.execute(
        select(func.count()).select_from(User).where(User.role == "student")
    )).scalar_one()
    staff = (await db.execute(
        select(func.count()).select_from(User).where(User.role.in_(("teacher", "admin")))
    )).scalar_one()

    already_students = (await db.execute(select(func.count()).select_from(StudentProfile))).scalar_one()
    already_staff = (await db.execute(select(func.count()).select_from(EmployeeProfile))).scalar_one()
    existing_classes = (await db.execute(select(func.count()).select_from(SchoolClass))).scalar_one()
    existing_sections = (await db.execute(select(func.count()).select_from(Section))).scalar_one()

    # Sections, per resolved class, from the students actually in them.
    result = await db.execute(text(
        "SELECT class_name, section, count(*) FROM users "
        "WHERE role = 'student' AND class_name IS NOT NULL GROUP BY 1, 2"
    ))
    section_rows = result.all()
    sections: dict[str, set[str]] = {}
    students_without_class = 0
    for class_name, section, count in section_rows:
        canonical = normalize_class(class_name)
        if not canonical:
            students_without_class += int(count)
            continue
        label = normalize_section(section) if section else None
        if label:
            sections.setdefault(canonical, set()).add(label)

    session = await current_session(db)

    return {
        "session": session.to_dict() if session else None,
        "students": {
            "total": students,
            "already_linked": already_students,
            "to_link": max(students - already_students, 0),
            "without_recognisable_class": students_without_class,
        },
        "staff": {
            "total": staff,
            "already_linked": already_staff,
            "to_link": max(staff - already_staff, 0),
        },
        "classes": {
            "existing": existing_classes,
            "to_create": len([c for c in resolved if True]),
            "names": sorted(resolved.keys(), key=_sort_order_for),
            "spellings_found": sum(len(v) for v in resolved.values()),
        },
        "sections": {
            "existing": existing_sections,
            "to_create": sum(len(v) for v in sections.values()),
            "by_class": {k: sorted(v) for k, v in sorted(sections.items(), key=lambda kv: _sort_order_for(kv[0]))},
        },
        "needs_attention": unresolved,
    }


# ─── Sessions ─────────────────────────────────────────────────────────────────

async def current_session(db: AsyncSession) -> AcademicSession | None:
    result = await db.execute(
        select(AcademicSession).where(AcademicSession.is_current.is_(True))
    )
    return result.scalar_one_or_none()


def _default_session_name(today: date | None = None) -> str:
    """A Pakistani school year runs April–March, so the session a date belongs
    to is not simply its calendar year."""
    today = today or date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    return f"{start_year}-{start_year + 1}"


async def ensure_session(db: AsyncSession, name: str | None = None) -> AcademicSession:
    session = await current_session(db)
    if session:
        return session

    name = name or _default_session_name()
    result = await db.execute(select(AcademicSession).where(AcademicSession.name == name))
    session = result.scalar_one_or_none()
    if session is None:
        start_year = int(name.split("-")[0])
        session = AcademicSession(
            name=name,
            start_date=date(start_year, 4, 1),
            end_date=date(start_year + 1, 3, 31),
            status=SESSION_ACTIVE,
            is_current=True,
        )
        db.add(session)
        await db.flush()
    else:
        session.is_current = True
        session.status = SESSION_ACTIVE
    return session


# ─── The run ──────────────────────────────────────────────────────────────────

async def run(db: AsyncSession, *, actor: User | None = None, session_name: str | None = None) -> dict:
    """Link everything. Idempotent: what already exists is left alone."""
    report = {
        "session": None,
        "classes_created": 0, "aliases_created": 0, "sections_created": 0,
        "subjects_created": 0,
        "students_linked": 0, "staff_linked": 0,
        "enrollments_created": 0, "teacher_assignments_created": 0,
        "unresolved_classes": [],
    }

    session = await ensure_session(db, session_name)
    await db.flush()
    report["session"] = session.name

    # ── Classes and aliases ──
    class_strings = await _distinct_class_strings(db)
    class_by_canonical: dict[str, SchoolClass] = {}

    result = await db.execute(select(SchoolClass))
    for row in result.scalars().all():
        class_by_canonical[row.canonical_name] = row

    result = await db.execute(select(ClassAlias.alias_key))
    known_aliases = {row[0] for row in result.all()}

    for raw in sorted(class_strings):
        canonical = normalize_class(raw)
        if not canonical:
            report["unresolved_classes"].append(raw)
            continue

        school_class = class_by_canonical.get(canonical)
        if school_class is None:
            school_class = SchoolClass(
                canonical_name=canonical,
                level=_level_for(canonical),
                sort_order=_sort_order_for(canonical),
            )
            db.add(school_class)
            await db.flush()
            class_by_canonical[canonical] = school_class
            report["classes_created"] += 1

        alias_key = (raw or "").strip().lower()
        if alias_key and alias_key not in known_aliases:
            db.add(ClassAlias(class_id=school_class.id, alias_key=alias_key, alias_label=raw))
            known_aliases.add(alias_key)
            report["aliases_created"] += 1

    # ── Sections, from where students actually are ──
    result = await db.execute(text(
        "SELECT DISTINCT class_name, section FROM users "
        "WHERE role = 'student' AND class_name IS NOT NULL AND section IS NOT NULL AND section <> ''"
    ))
    section_by_key: dict[tuple[str, str], Section] = {}
    existing = await db.execute(select(Section))
    for row in existing.scalars().all():
        section_by_key[(row.class_id, row.name.lower())] = row

    for class_name, raw_section in result.all():
        canonical = normalize_class(class_name)
        label = normalize_section(raw_section)
        if not canonical or not label:
            continue
        school_class = class_by_canonical.get(canonical)
        if school_class is None:
            continue
        if (school_class.id, label.lower()) in section_by_key:
            continue
        section = Section(class_id=school_class.id, name=label)
        db.add(section)
        await db.flush()
        section_by_key[(school_class.id, label.lower())] = section
        report["sections_created"] += 1

    # ── Subjects, from what teachers already teach ──
    result = await db.execute(select(User.subjects).where(User.role == "teacher"))
    subject_names: set[str] = set()
    for (subjects,) in result.all():
        for name in (subjects or []):
            cleaned = str(name).strip()
            if cleaned:
                subject_names.add(cleaned.title())

    existing_subjects = await db.execute(select(Subject))
    subject_by_name = {s.name.lower(): s for s in existing_subjects.scalars().all()}
    for name in sorted(subject_names):
        if name.lower() not in subject_by_name:
            subject = Subject(name=name, short_name=name[:12])
            db.add(subject)
            await db.flush()
            subject_by_name[name.lower()] = subject
            report["subjects_created"] += 1

    await db.commit()

    # ── People ──
    report.update(await _link_students(db, session, class_by_canonical, section_by_key))
    report.update(await _link_staff(db, session, class_by_canonical, section_by_key, subject_by_name))

    audit.record(
        db, actor=actor, entity_type=audit.SETUP, action="run",
        new_value=report,
        reason="School setup linked existing LSS Bot records into the ERP",
    )
    await db.commit()
    return report


async def _link_students(db, session, class_by_canonical, section_by_key) -> dict:
    """One `student_profiles` row and one enrollment per existing student.

    The registration number they already log in with is preserved as
    `registration_no`. GR numbers are deliberately *not* invented here — LSS
    keeps a paper GR register, and a generated number that contradicts it would
    be worse than a blank field. The office allocates them explicitly.
    """
    created_profiles = enrollments = 0

    result = await db.execute(select(User).where(User.role == "student"))
    students = list(result.scalars().all())

    existing = await db.execute(select(StudentProfile.user_id))
    have_profile = {row[0] for row in existing.all()}

    existing = await db.execute(
        select(Enrollment.student_user_id).where(Enrollment.session_id == session.id)
    )
    have_enrollment = {row[0] for row in existing.all()}

    for student in students:
        if student.id not in have_profile:
            db.add(StudentProfile(
                user_id=student.id,
                registration_no=student.login_id,
                status=STUDENT_ACTIVE if student.is_active else "inactive",
                source=SOURCE_LEGACY,
            ))
            created_profiles += 1

        if student.id in have_enrollment:
            continue

        canonical = normalize_class(student.class_name) if student.class_name else None
        school_class = class_by_canonical.get(canonical) if canonical else None
        if school_class is None:
            # No recognisable class: the student keeps working exactly as
            # before, and appears on the "needs attention" list instead of
            # being guessed into a class they may not be in.
            continue

        label = normalize_section(student.section) if student.section else None
        section = section_by_key.get((school_class.id, label.lower())) if label else None

        db.add(Enrollment(
            student_user_id=student.id,
            session_id=session.id,
            class_id=school_class.id,
            section_id=section.id if section else None,
            status=ENROLL_ENROLLED,
            enrolled_on=session.start_date,
            source=SOURCE_LEGACY,
        ))
        enrollments += 1

    await db.commit()
    return {"students_linked": created_profiles, "enrollments_created": enrollments}


async def _link_staff(db, session, class_by_canonical, section_by_key, subject_by_name) -> dict:
    """One `employee_profiles` row per teacher/admin, plus their assignments.

    The JSON columns on `users` are read, never written: classroom
    authorization depends on them and must keep behaving identically.
    """
    created_profiles = assignments = 0

    result = await db.execute(select(User).where(User.role.in_(("teacher", "admin"))))
    staff = list(result.scalars().all())

    existing = await db.execute(select(EmployeeProfile.user_id))
    have_profile = {row[0] for row in existing.all()}

    existing = await db.execute(
        select(
            TeacherAssignment.teacher_user_id, TeacherAssignment.class_id,
            TeacherAssignment.section_id, TeacherAssignment.subject_id,
        ).where(TeacherAssignment.session_id == session.id)
    )
    have_assignment = {tuple(row) for row in existing.all()}

    for person in staff:
        if person.id not in have_profile:
            db.add(EmployeeProfile(
                user_id=person.id,
                registration_no=person.login_id,
                designation="Teacher" if person.role == "teacher" else "Administrator",
                employment_status="active" if person.is_active else "resigned",
                source=SOURCE_LEGACY,
            ))
            created_profiles += 1

        if person.role != "teacher":
            continue

        subjects = [s for s in (person.subjects or []) if str(s).strip()]
        subject_ids = [
            subject_by_name[str(s).strip().title().lower()].id
            for s in subjects
            if str(s).strip().title().lower() in subject_by_name
        ] or [None]

        # A teacher's sections are stored as combined strings ("Grade 5 - A"),
        # so the class comes from the same string the section does.
        targets: list[tuple[str, str | None]] = []
        for combined in (person.assigned_sections or []):
            canonical = normalize_class(str(combined).split(" - ")[0])
            label = normalize_section(str(combined).split(" - ")[-1]) if " - " in str(combined) else None
            if canonical:
                targets.append((canonical, label))
        for class_name in (person.assigned_classes or []):
            canonical = normalize_class(class_name)
            if canonical and not any(t[0] == canonical for t in targets):
                targets.append((canonical, None))

        for canonical, label in targets:
            school_class = class_by_canonical.get(canonical)
            if school_class is None:
                continue
            section = section_by_key.get((school_class.id, label.lower())) if label else None
            for subject_id in subject_ids:
                key = (person.id, school_class.id, section.id if section else None, subject_id)
                if key in have_assignment:
                    continue
                db.add(TeacherAssignment(
                    session_id=session.id,
                    teacher_user_id=person.id,
                    class_id=school_class.id,
                    section_id=section.id if section else None,
                    subject_id=subject_id,
                    source=SOURCE_LEGACY,
                ))
                have_assignment.add(key)
                assignments += 1

    await db.commit()
    return {"staff_linked": created_profiles, "teacher_assignments_created": assignments}


# ─── Explicit number allocation ───────────────────────────────────────────────

async def allocate_missing_gr_numbers(db: AsyncSession, *, actor: User | None = None) -> dict:
    """Give a GR number to every student who has none.

    Separate from setup and separately confirmed, because a GR number is an
    institutional fact. If LSS already keeps a paper register, these should be
    typed in rather than generated — so this is a button the office presses
    knowingly, not something that happens to them.
    """
    result = await db.execute(
        select(StudentProfile).where(StudentProfile.gr_no.is_(None)).order_by(StudentProfile.user_id)
    )
    profiles = list(result.scalars().all())
    if not profiles:
        return {"allocated": 0}

    numbers = await numbering.allocate(db, numbering.SCOPE_GR, count=len(profiles))
    for profile, number in zip(profiles, numbers):
        profile.gr_no = number

    audit.record(
        db, actor=actor, entity_type=audit.STUDENT, action="gr_numbers_allocated",
        new_value={"count": len(profiles), "first": numbers[0], "last": numbers[-1]},
    )
    await db.commit()
    return {"allocated": len(profiles), "first": numbers[0], "last": numbers[-1]}


async def allocate_missing_employee_numbers(db: AsyncSession, *, actor: User | None = None) -> dict:
    result = await db.execute(
        select(EmployeeProfile).where(EmployeeProfile.employee_no.is_(None)).order_by(EmployeeProfile.user_id)
    )
    profiles = list(result.scalars().all())
    if not profiles:
        return {"allocated": 0}

    numbers = await numbering.allocate(db, numbering.SCOPE_EMPLOYEE, count=len(profiles))
    for profile, number in zip(profiles, numbers):
        profile.employee_no = number

    audit.record(
        db, actor=actor, entity_type=audit.EMPLOYEE, action="employee_numbers_allocated",
        new_value={"count": len(profiles), "first": numbers[0], "last": numbers[-1]},
    )
    await db.commit()
    return {"allocated": len(profiles), "first": numbers[0], "last": numbers[-1]}

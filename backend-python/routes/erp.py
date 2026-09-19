"""
ERP API (phase 1 — foundations).

Every route here is new. Nothing in this module reads or writes an existing
endpoint's data in a way an existing screen would notice, which is the
condition the whole programme is built on.

Two conventions run through it:

  * **The screen asks one question at a time.** Endpoints return the shape the
    UI needs — counts, names, and an explicit list of what needs a human —
    rather than raw rows the browser must then assemble. The complexity belongs
    here, not in front of the accountant.

  * **Nothing is guessed.** Anything the system cannot work out with certainty
    comes back under `needs_attention` instead of being filled in.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user
from models.erp import (
    AcademicSession, AuditLog, ClassSubject, Enrollment, EmployeeProfile,
    FeatureFlag, Family, NumberSeries, Role, RolePermission, SchoolClass,
    Section, StudentProfile, Subject, TeacherAssignment, UserRole,
)
from models.models import User
from services.erp import audit, numbering, setup as setup_service
from services.erp.permissions import (
    OWNER_ONLY, PERMISSIONS, permissions_for, require_permission, role_keys_for,
)

router = APIRouter(prefix="/erp", tags=["erp"])


# ─── Availability ─────────────────────────────────────────────────────────────

async def erp_available(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Gate every ERP route behind the module flag.

    While the flag is off the ERP exists but is invisible: only accounts that
    can manage flags (the Owner, and today's admins) can reach it. That is what
    lets this deploy to a live school on a Tuesday without 755 students seeing
    a half-built module.
    """
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.key == setup_service.FLAG_ERP))
    flag = result.scalar_one_or_none()

    if flag is not None and flag.enabled:
        allowed_roles = flag.roles or []
        if not allowed_roles:
            return user
        if set(allowed_roles) & set(await role_keys_for(db, user) + [user.role]):
            return user

    held = await permissions_for(db, user)
    if "owner.flags" in held:
        return user

    raise HTTPException(status_code=404, detail="Not found")


@router.get("/status")
async def status(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What this user may see. Safe to call for anyone — it never 404s.

    The frontend uses it to decide whether to show the ERP at all, so it must
    answer for a student too.
    """
    held = await permissions_for(db, user)
    roles = await role_keys_for(db, user)

    result = await db.execute(select(FeatureFlag).where(FeatureFlag.key == setup_service.FLAG_ERP))
    flag = result.scalar_one_or_none()
    enabled = bool(flag and flag.enabled)
    can_preview = "owner.flags" in held

    session = await setup_service.current_session(db)
    students_linked = (await db.execute(select(func.count()).select_from(StudentProfile))).scalar_one()

    return {
        "available": enabled or can_preview,
        "enabled": enabled,
        "preview_only": can_preview and not enabled,
        "roles": roles,
        "permissions": sorted(held),
        "is_owner": "owner" in roles,
        "session": session.to_dict() if session else None,
        "setup_done": bool(session and students_linked),
    }


# ─── Setup ────────────────────────────────────────────────────────────────────

@router.get("/setup/analyze")
async def setup_analyze(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("setup.view")),
    db: AsyncSession = Depends(get_db),
):
    """A dry run: exactly what setup will create. Writes nothing."""
    return await setup_service.analyze(db)


@router.post("/setup/run")
async def setup_run(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("setup.run")),
    db: AsyncSession = Depends(get_db),
):
    await setup_service.bootstrap(db)
    return await setup_service.run(db, actor=user)


@router.post("/setup/allocate-gr-numbers")
async def allocate_gr(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("student.edit")),
    db: AsyncSession = Depends(get_db),
):
    return await setup_service.allocate_missing_gr_numbers(db, actor=user)


@router.post("/setup/allocate-employee-numbers")
async def allocate_emp(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("employee.edit")),
    db: AsyncSession = Depends(get_db),
):
    return await setup_service.allocate_missing_employee_numbers(db, actor=user)


# ─── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def dashboard(
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The numbers a head teacher would ask for, and nothing else."""
    session = await setup_service.current_session(db)

    students = (await db.execute(
        select(func.count()).select_from(User).where(User.role == "student", User.is_active.is_(True))
    )).scalar_one()
    staff = (await db.execute(
        select(func.count()).select_from(User).where(User.role == "teacher", User.is_active.is_(True))
    )).scalar_one()
    classes = (await db.execute(select(func.count()).select_from(SchoolClass))).scalar_one()
    sections = (await db.execute(select(func.count()).select_from(Section))).scalar_one()
    families = (await db.execute(select(func.count()).select_from(Family))).scalar_one()

    enrolled = 0
    if session:
        enrolled = (await db.execute(
            select(func.count()).select_from(Enrollment).where(Enrollment.session_id == session.id)
        )).scalar_one()

    # Exception-based management (spec §73): what needs a human, counted.
    no_gr = (await db.execute(
        select(func.count()).select_from(StudentProfile).where(StudentProfile.gr_no.is_(None))
    )).scalar_one()
    no_emp_no = (await db.execute(
        select(func.count()).select_from(EmployeeProfile).where(EmployeeProfile.employee_no.is_(None))
    )).scalar_one()
    unenrolled = max(students - enrolled, 0)

    return {
        "session": session.to_dict() if session else None,
        "totals": {
            "students": students, "staff": staff, "classes": classes,
            "sections": sections, "families": families, "enrolled": enrolled,
        },
        "needs_attention": [
            item for item in [
                {"key": "gr_numbers", "count": no_gr,
                 "label": "students without a GR number",
                 "action": "allocate_gr", "action_label": "Allocate GR numbers"} if no_gr else None,
                {"key": "employee_numbers", "count": no_emp_no,
                 "label": "staff without an employee number",
                 "action": "allocate_employee_no", "action_label": "Allocate employee numbers"} if no_emp_no else None,
                {"key": "unenrolled", "count": unenrolled,
                 "label": "students not yet placed in a class this session",
                 "action": "open_students", "action_label": "Review students"} if unenrolled else None,
            ] if item
        ],
    }


# ─── Sessions ─────────────────────────────────────────────────────────────────

class SessionRequest(BaseModel):
    name: str
    start_date: date | None = None
    end_date: date | None = None
    make_current: bool = False


@router.get("/sessions")
async def list_sessions(
    _: User = Depends(erp_available),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AcademicSession).order_by(AcademicSession.name.desc()))
    return [s.to_dict() for s in result.scalars().all()]


@router.post("/sessions")
async def create_session(
    body: SessionRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("session.manage")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AcademicSession).where(AcademicSession.name == body.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Session {body.name} already exists")

    session = AcademicSession(
        name=body.name, start_date=body.start_date, end_date=body.end_date,
        status="planning",
    )
    db.add(session)
    await db.flush()

    if body.make_current:
        await _make_current(db, session)

    audit.record(db, actor=user, entity_type=audit.SESSION, action="created",
                 entity_id=session.id, new_value=session.to_dict())
    await db.commit()
    return session.to_dict()


async def _make_current(db: AsyncSession, session: AcademicSession) -> None:
    result = await db.execute(select(AcademicSession).where(AcademicSession.is_current.is_(True)))
    for other in result.scalars().all():
        other.is_current = False
    session.is_current = True
    session.status = "active"


@router.post("/sessions/{session_id}/make-current")
async def make_current(
    session_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("session.manage")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AcademicSession).where(AcademicSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await _make_current(db, session)
    audit.record(db, actor=user, entity_type=audit.SESSION, action="made_current",
                 entity_id=session.id, new_value={"name": session.name})
    await db.commit()
    return session.to_dict()


# ─── Classes ──────────────────────────────────────────────────────────────────

@router.get("/classes")
async def list_classes(
    _: User = Depends(erp_available),
    db: AsyncSession = Depends(get_db),
):
    """Classes, their sections, and how many students are in each.

    One call, because a screen that shows a class list always shows the counts
    too, and three round trips to render one table is how a page starts feeling
    slow on a phone.
    """
    session = await setup_service.current_session(db)

    result = await db.execute(select(SchoolClass).order_by(SchoolClass.sort_order))
    classes = list(result.scalars().all())

    result = await db.execute(select(Section))
    sections = list(result.scalars().all())

    counts: dict[tuple[str, str | None], int] = {}
    if session:
        result = await db.execute(
            select(Enrollment.class_id, Enrollment.section_id, func.count())
            .where(Enrollment.session_id == session.id)
            .group_by(Enrollment.class_id, Enrollment.section_id)
        )
        for class_id, section_id, count in result.all():
            counts[(class_id, section_id)] = int(count)

    out = []
    for school_class in classes:
        class_sections = [s for s in sections if s.class_id == school_class.id]
        out.append({
            **school_class.to_dict(),
            "students": sum(v for (c, _s), v in counts.items() if c == school_class.id),
            "sections": [
                {**s.to_dict(), "students": counts.get((school_class.id, s.id), 0)}
                for s in sorted(class_sections, key=lambda s: s.name)
            ],
        })
    return out


@router.get("/subjects")
async def list_subjects(
    _: User = Depends(erp_available),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Subject).order_by(Subject.name))
    return [s.to_dict() for s in result.scalars().all()]


# ─── Students ─────────────────────────────────────────────────────────────────

@router.get("/students")
async def list_students(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("student.view")),
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, description="GR No., admission no., registration no., name or father name"),
    class_id: str | None = None,
    section_id: str | None = None,
    needs_attention: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    """One search box answers every way a school refers to a student."""
    session = await setup_service.current_session(db)

    stmt = (
        select(User, StudentProfile, Enrollment)
        .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)
        .join(
            Enrollment,
            (Enrollment.student_user_id == User.id)
            & (Enrollment.session_id == (session.id if session else "")),
            isouter=True,
        )
        .where(User.role == "student")
    )

    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            User.name.ilike(pattern),
            User.father_name.ilike(pattern),
            User.login_id.ilike(pattern),
            StudentProfile.gr_no.ilike(pattern),
            StudentProfile.admission_no.ilike(pattern),
            StudentProfile.registration_no.ilike(pattern),
        ))
    if class_id:
        stmt = stmt.where(Enrollment.class_id == class_id)
    if section_id:
        stmt = stmt.where(Enrollment.section_id == section_id)
    if needs_attention:
        stmt = stmt.where(or_(StudentProfile.gr_no.is_(None), Enrollment.id.is_(None)))

    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()

    result = await db.execute(stmt.order_by(User.name).limit(limit).offset(offset))
    rows = result.all()

    class_names, section_names = await _label_maps(db)

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "students": [
            {
                "id": user_row.id,
                "name": user_row.name,
                "father_name": user_row.father_name,
                "login_id": user_row.login_id,
                "is_active": bool(user_row.is_active),
                "gr_no": profile.gr_no if profile else None,
                "admission_no": profile.admission_no if profile else None,
                "registration_no": (profile.registration_no if profile else None) or user_row.login_id,
                "class_name": class_names.get(enrollment.class_id) if enrollment else user_row.class_name,
                "section_name": section_names.get(enrollment.section_id) if enrollment else user_row.section,
                "enrolled": bool(enrollment),
                "missing": profile.missing_fields() if profile else ["profile"],
            }
            for user_row, profile, enrollment in rows
        ],
    }


async def _label_maps(db: AsyncSession) -> tuple[dict, dict]:
    result = await db.execute(select(SchoolClass.id, SchoolClass.canonical_name))
    class_names = {row[0]: row[1] for row in result.all()}
    result = await db.execute(select(Section.id, Section.name))
    section_names = {row[0]: row[1] for row in result.all()}
    return class_names, section_names


class StudentUpdate(BaseModel):
    gr_no: str | None = None
    admission_no: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    b_form: str | None = None
    phone: str | None = None
    address: str | None = None
    admission_date: date | None = None
    previous_school: str | None = None
    emergency_contact: str | None = None
    emergency_phone: str | None = None
    remarks: str | None = None


@router.get("/students/{user_id}")
async def get_student(
    user_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("student.view")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id, User.role == "student"))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    result = await db.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    profile = result.scalar_one_or_none()

    session = await setup_service.current_session(db)
    enrollment = None
    if session:
        result = await db.execute(
            select(Enrollment).where(
                Enrollment.student_user_id == user_id,
                Enrollment.session_id == session.id,
            )
        )
        enrollment = result.scalar_one_or_none()

    class_names, section_names = await _label_maps(db)

    return {
        "id": student.id,
        "name": student.name,
        "father_name": student.father_name,
        "login_id": student.login_id,
        "email": student.email,
        "is_active": bool(student.is_active),
        "legacy_class": student.class_name,
        "legacy_section": student.section,
        "profile": profile.to_dict() if profile else None,
        "enrollment": {
            "class_id": enrollment.class_id,
            "class_name": class_names.get(enrollment.class_id),
            "section_id": enrollment.section_id,
            "section_name": section_names.get(enrollment.section_id),
            "roll_no": enrollment.roll_no,
            "status": enrollment.status,
        } if enrollment else None,
    }


@router.put("/students/{user_id}")
async def update_student(
    user_id: str,
    body: StudentUpdate,
    request: Request,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("student.edit")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile is None:
        result = await db.execute(select(User).where(User.id == user_id, User.role == "student"))
        student = result.scalar_one_or_none()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")
        profile = StudentProfile(user_id=user_id, registration_no=student.login_id)
        db.add(profile)
        await db.flush()

    before = profile.to_dict()
    changes = body.model_dump(exclude_unset=True)

    # A GR number is unique school-wide; a clash is a data error worth naming
    # rather than a constraint violation worth a 500.
    if changes.get("gr_no"):
        clash = await db.execute(
            select(StudentProfile.user_id).where(
                StudentProfile.gr_no == changes["gr_no"],
                StudentProfile.user_id != user_id,
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"GR No. {changes['gr_no']} already belongs to another student")

    for field, value in changes.items():
        setattr(profile, field, value)

    old, new = audit.diff(before, profile.to_dict())
    if new:
        audit.record(
            db, actor=user, entity_type=audit.STUDENT, action="updated",
            entity_id=user_id, old_value=old, new_value=new,
            ip=request.client.host if request.client else None,
        )
    await db.commit()
    return profile.to_dict()


# ─── Staff ────────────────────────────────────────────────────────────────────

@router.get("/staff")
async def list_staff(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("employee.view")),
    db: AsyncSession = Depends(get_db),
    q: str | None = None,
    needs_attention: bool = False,
    limit: int = Query(100, le=300),
    offset: int = 0,
):
    held = await permissions_for(db, user)
    may_see_sensitive = "employee.sensitive" in held

    stmt = (
        select(User, EmployeeProfile)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id, isouter=True)
        .where(User.role.in_(("teacher", "admin")))
    )
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            User.name.ilike(pattern),
            User.login_id.ilike(pattern),
            EmployeeProfile.employee_no.ilike(pattern),
            EmployeeProfile.designation.ilike(pattern),
        ))
    if needs_attention:
        stmt = stmt.where(or_(
            EmployeeProfile.employee_no.is_(None),
            EmployeeProfile.cnic.is_(None),
            EmployeeProfile.joining_date.is_(None),
        ))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    result = await db.execute(stmt.order_by(User.name).limit(limit).offset(offset))

    staff = []
    for user_row, profile in result.all():
        entry = {
            "id": user_row.id,
            "name": user_row.name,
            "login_id": user_row.login_id,
            "role": user_row.role,
            "is_active": bool(user_row.is_active),
            "employee_no": profile.employee_no if profile else None,
            "designation": profile.designation if profile else None,
            "department": profile.department if profile else None,
            "joining_date": profile.joining_date.isoformat() if profile and profile.joining_date else None,
            "subjects": user_row.subjects or [],
            "missing": profile.missing_fields() if profile else ["profile"],
        }
        # CNIC and bank details are only ever sent to someone entitled to see
        # them — field-level, not screen-level (blueprint §4.1).
        if may_see_sensitive and profile:
            entry["cnic"] = profile.cnic
            entry["bank_name"] = profile.bank_name
            entry["bank_iban"] = profile.bank_iban
        staff.append(entry)

    return {"total": total, "limit": limit, "offset": offset,
            "sensitive_visible": may_see_sensitive, "staff": staff}


class StaffUpdate(BaseModel):
    employee_no: str | None = None
    cnic: str | None = None
    designation: str | None = None
    department: str | None = None
    joining_date: date | None = None
    employment_type: str | None = None
    qualification: str | None = None
    phone: str | None = None
    address: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    father_or_husband_name: str | None = None
    emergency_contact: str | None = None
    emergency_phone: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    bank_iban: str | None = None
    remarks: str | None = None


@router.put("/staff/{user_id}")
async def update_staff(
    user_id: str,
    body: StaffUpdate,
    request: Request,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("employee.edit")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(EmployeeProfile).where(EmployeeProfile.user_id == user_id))
    profile = result.scalar_one_or_none()
    if profile is None:
        result = await db.execute(select(User).where(User.id == user_id))
        person = result.scalar_one_or_none()
        if not person or person.role not in ("teacher", "admin"):
            raise HTTPException(status_code=404, detail="Staff member not found")
        profile = EmployeeProfile(user_id=user_id, registration_no=person.login_id)
        db.add(profile)
        await db.flush()

    changes = body.model_dump(exclude_unset=True)
    sensitive = {"cnic", "bank_name", "bank_account", "bank_iban"}
    if sensitive & set(changes):
        held = await permissions_for(db, user)
        if "employee.sensitive" not in held:
            raise HTTPException(status_code=403, detail="You may not edit CNIC or bank details.")

    if changes.get("employee_no"):
        clash = await db.execute(
            select(EmployeeProfile.user_id).where(
                EmployeeProfile.employee_no == changes["employee_no"],
                EmployeeProfile.user_id != user_id,
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Employee No. {changes['employee_no']} is already in use")

    before = profile.to_dict()
    for field, value in changes.items():
        setattr(profile, field, value)

    old, new = audit.diff(before, profile.to_dict())
    if new:
        audit.record(
            db, actor=user, entity_type=audit.EMPLOYEE, action="updated",
            entity_id=user_id, old_value=old, new_value=new,
            ip=request.client.host if request.client else None,
        )
    await db.commit()
    return profile.to_dict()


# ─── Roles and access ─────────────────────────────────────────────────────────

@router.get("/access/roles")
async def list_roles(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("owner.roles")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Role).order_by(Role.rank))
    roles = list(result.scalars().all())

    result = await db.execute(select(RolePermission.role_id, RolePermission.permission_key))
    by_role: dict[str, list[str]] = {}
    for role_id, key in result.all():
        by_role.setdefault(role_id, []).append(key)

    result = await db.execute(
        select(UserRole.role_id, func.count()).group_by(UserRole.role_id)
    )
    counts = {row[0]: int(row[1]) for row in result.all()}

    return {
        "catalogue": [{"key": k, "description": v} for k, v in sorted(PERMISSIONS.items())],
        "roles": [
            {**role.to_dict(),
             "permissions": sorted(by_role.get(role.id, [])),
             "people": counts.get(role.id, 0)}
            for role in roles
        ],
    }


class RoleAssignment(BaseModel):
    user_id: str
    role_key: str


@router.post("/access/grant")
async def grant_role(
    body: RoleAssignment,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("owner.users")),
    db: AsyncSession = Depends(get_db),
):
    """Give someone a role. The Owner role is protected (blueprint §1.5)."""
    result = await db.execute(select(Role).where(Role.key == body.role_key))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if role.key == "owner" and "owner" not in await role_keys_for(db, user):
        raise HTTPException(status_code=403, detail="Only an Owner may create another Owner.")

    result = await db.execute(select(User).where(User.id == body.user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(UserRole).where(UserRole.user_id == target.id, UserRole.role_id == role.id)
    )
    if result.scalar_one_or_none():
        return {"message": f"{target.name} already has the {role.name} role"}

    db.add(UserRole(user_id=target.id, role_id=role.id, granted_by=user.id))
    audit.record(db, actor=user, entity_type=audit.USER_ROLE, action="granted",
                 entity_id=target.id, new_value={"role": role.key, "to": target.name})
    await db.commit()
    return {"message": f"{target.name} is now {role.name}"}


@router.post("/access/revoke")
async def revoke_role(
    body: RoleAssignment,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("owner.users")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Role).where(Role.key == body.role_key))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # The last Owner cannot be removed — not by anyone, including themselves.
    # A system with no Owner cannot grant the role back.
    if role.key == "owner":
        remaining = (await db.execute(
            select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
        )).scalar_one()
        if remaining <= 1:
            raise HTTPException(status_code=400, detail="The last Owner cannot be removed.")

    await db.execute(
        text("DELETE FROM user_roles WHERE user_id = :u AND role_id = :r"),
        {"u": body.user_id, "r": role.id},
    )
    audit.record(db, actor=user, entity_type=audit.USER_ROLE, action="revoked",
                 entity_id=body.user_id, old_value={"role": role.key})
    await db.commit()
    return {"message": "Role removed"}


@router.get("/access/people")
async def list_people_with_roles(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("owner.users")),
    db: AsyncSession = Depends(get_db),
):
    """Everyone who holds an ERP role, plus every staff account that could."""
    result = await db.execute(
        select(User, Role)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .order_by(Role.rank, User.name)
    )
    assigned: dict[str, dict] = {}
    for user_row, role in result.all():
        entry = assigned.setdefault(user_row.id, {
            "id": user_row.id, "name": user_row.name, "login_id": user_row.login_id,
            "legacy_role": user_row.role, "is_active": bool(user_row.is_active),
            "roles": [],
        })
        entry["roles"].append({"key": role.key, "name": role.name})

    result = await db.execute(
        select(User).where(User.role.in_(("admin", "teacher")), User.is_active.is_(True)).order_by(User.name)
    )
    candidates = [
        {"id": u.id, "name": u.name, "login_id": u.login_id, "legacy_role": u.role}
        for u in result.scalars().all() if u.id not in assigned
    ]

    return {"people": list(assigned.values()), "candidates": candidates}


# ─── Settings: numbering and flags ────────────────────────────────────────────

@router.get("/settings/numbering")
async def get_numbering(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("owner.settings")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NumberSeries).order_by(NumberSeries.scope))
    return [s.to_dict() for s in result.scalars().all()]


class NumberingUpdate(BaseModel):
    pattern: str | None = None
    next_value: int | None = None


@router.put("/settings/numbering/{scope}")
async def update_numbering(
    scope: str,
    body: NumberingUpdate,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("owner.settings")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NumberSeries).where(NumberSeries.scope == scope))
    series = result.scalar_one_or_none()
    if not series:
        raise HTTPException(status_code=404, detail="Number series not found")

    before = series.to_dict()
    if body.pattern is not None:
        try:
            body.pattern.format(seq=1, session="2026-2027")
        except (KeyError, ValueError, IndexError):
            raise HTTPException(
                status_code=400,
                detail="That pattern is not valid. Use {seq} for the number, e.g. LSS-{seq:05d}",
            )
        series.pattern = body.pattern
    if body.next_value is not None:
        if body.next_value < 1:
            raise HTTPException(status_code=400, detail="The next number must be at least 1")
        series.next_value = body.next_value

    old, new = audit.diff(before, series.to_dict())
    audit.record(db, actor=user, entity_type=audit.NUMBER_SERIES, action="updated",
                 entity_id=series.id, old_value=old, new_value=new)
    await db.commit()
    return series.to_dict()


@router.get("/settings/flags")
async def list_flags(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("owner.flags")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(FeatureFlag).order_by(FeatureFlag.key))
    return [f.to_dict() for f in result.scalars().all()]


class FlagUpdate(BaseModel):
    enabled: bool
    roles: list[str] | None = None


@router.put("/settings/flags/{key}")
async def update_flag(
    key: str,
    body: FlagUpdate,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("owner.flags")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(FeatureFlag).where(FeatureFlag.key == key))
    flag = result.scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=404, detail="Unknown module")

    before = flag.to_dict()
    flag.enabled = body.enabled
    if body.roles is not None:
        flag.roles = body.roles
    flag.updated_by = user.id

    old, new = audit.diff(before, flag.to_dict())
    audit.record(db, actor=user, entity_type=audit.FEATURE_FLAG, action="updated",
                 entity_id=key, old_value=old, new_value=new)
    await db.commit()
    return flag.to_dict()


# ─── Audit ────────────────────────────────────────────────────────────────────

@router.get("/audit")
async def list_audit(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("audit.view")),
    db: AsyncSession = Depends(get_db),
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    stmt = select(AuditLog).order_by(AuditLog.occurred_at.desc())
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    result = await db.execute(stmt.limit(limit).offset(offset))
    return {"total": total, "entries": [e.to_dict() for e in result.scalars().all()]}

"""
Admissions and family linking (ERP phase 2).

The specification's promise for this module is the strongest one it makes:
*admission once, and the whole of LSS Bot knows.* Everything below exists to
make that true without a clerk having to understand any of it.

Two rules shape the code.

**Confirmation is one transaction.** GR number, admission number, family link,
login account, enrolment and the event that tells the rest of the system all
land together or not at all. A child who has a GR number but no account, or an
account but no class, is a support call and a lost afternoon — so that state is
made unreachable rather than handled.

**A family is suggested, never assumed.** Matching on father's name and phone
finds the right household most of the time, and quietly merging two families
that merely share a common name is not a mistake anyone would catch until a fee
concession lands on the wrong child. The clerk confirms; the computer only ever
proposes.
"""
from __future__ import annotations

import logging
import secrets
import string
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import (
    ADMISSION_CONFIRMED, ADMISSION_INQUIRY, ENROLL_ENROLLED, SOURCE_MANUAL,
    STUDENT_ACTIVE, Admission, Campus, Enrollment, Family, Guardian,
    SchoolClass, Section, StudentProfile,
)
from models.models import User, utcnow
from services.erp import audit, events, numbering
from services.erp.setup import current_session
from utils.password import hash_password

logger = logging.getLogger("agent")


class AdmissionError(RuntimeError):
    """Something the clerk needs to fix, phrased for the clerk."""


# ─── Campus ───────────────────────────────────────────────────────────────────

async def default_campus(db: AsyncSession) -> Campus:
    """The campus new records belong to.

    Created on first use rather than in a migration, so the name comes from the
    school rather than from a developer's guess, and so a fresh database does
    not carry a row nobody asked for.
    """
    result = await db.execute(select(Campus).where(Campus.is_default.is_(True)))
    campus = result.scalar_one_or_none()
    if campus:
        return campus

    result = await db.execute(select(Campus).order_by(Campus.created_at).limit(1))
    campus = result.scalar_one_or_none()
    if campus:
        campus.is_default = True
        await db.flush()
        return campus

    campus = Campus(name="LSS Islamabad", code="ISB", city="Islamabad", is_default=True)
    db.add(campus)
    await db.flush()
    return campus


# ─── Family matching ──────────────────────────────────────────────────────────

def _normalise_phone(value: str | None) -> str:
    """Pakistani numbers are written every way imaginable — 0300-1234567,
    +92 300 1234567, 03001234567. Compare the digits that identify the line."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("92"):
        digits = "0" + digits[2:]
    return digits[-10:] if len(digits) >= 10 else digits


def _normalise_name(value: str | None) -> str:
    return " ".join(str(value or "").lower().split())


async def suggest_families(
    db: AsyncSession,
    *,
    father_name: str | None = None,
    phone: str | None = None,
    cnic: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Families this child might belong to, strongest evidence first.

    CNIC is a strong key: one man, one number. A name plus a phone is weaker —
    plenty of fathers are called Muhammad Aslam — so it is offered as a
    suggestion with its reason attached, and the clerk decides.
    """
    candidates: dict[str, dict] = {}

    async def add(family: Family, confidence: str, reason: str) -> None:
        if family.id in candidates:
            return
        children = (await db.execute(
            select(func.count()).select_from(StudentProfile)
            .where(StudentProfile.family_id == family.id)
        )).scalar_one()
        candidates[family.id] = {
            **family.to_dict(),
            "children": children,
            "confidence": confidence,
            "reason": reason,
        }

    clean_cnic = "".join(ch for ch in str(cnic or "") if ch.isdigit())
    if clean_cnic:
        result = await db.execute(
            select(Family).join(Guardian, Guardian.family_id == Family.id, isouter=True)
            .where(or_(Family.cnic.ilike(f"%{clean_cnic}%"), Guardian.cnic.ilike(f"%{clean_cnic}%")))
            .limit(limit)
        )
        for family in result.scalars().unique().all():
            await add(family, "high", "Same CNIC")

    wanted_phone = _normalise_phone(phone)
    if wanted_phone and len(wanted_phone) >= 7:
        result = await db.execute(
            select(Family).join(Guardian, Guardian.family_id == Family.id, isouter=True)
            .where(or_(
                Family.phone.ilike(f"%{wanted_phone[-7:]}%"),
                Family.alt_phone.ilike(f"%{wanted_phone[-7:]}%"),
                Guardian.phone.ilike(f"%{wanted_phone[-7:]}%"),
            ))
            .limit(limit)
        )
        for family in result.scalars().unique().all():
            await add(family, "high", "Same phone number")

    wanted_father = _normalise_name(father_name)
    if wanted_father and len(wanted_father) >= 4:
        result = await db.execute(
            select(Family).where(Family.father_name.ilike(f"%{father_name.strip()}%")).limit(limit)
        )
        for family in result.scalars().all():
            await add(family, "medium", "Same father's name")

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(candidates.values(), key=lambda c: (order[c["confidence"]], -c["children"]))[:limit]


async def create_family(
    db: AsyncSession,
    *,
    father_name: str | None,
    mother_name: str | None = None,
    phone: str | None = None,
    cnic: str | None = None,
    address: str | None = None,
    email: str | None = None,
    actor: User | None = None,
) -> Family:
    """A new household. The caller commits."""
    campus = await default_campus(db)
    code = await numbering.allocate_one(db, numbering.SCOPE_FAMILY)
    family = Family(
        family_code=code,
        campus_id=campus.id,
        father_name=(father_name or "").strip() or None,
        mother_name=(mother_name or "").strip() or None,
        phone=(phone or "").strip() or None,
        cnic=(cnic or "").strip() or None,
        email=(email or "").strip() or None,
        address=address,
        source=SOURCE_MANUAL,
    )
    db.add(family)
    await db.flush()

    if family.father_name:
        db.add(Guardian(
            family_id=family.id, name=family.father_name, relation="father",
            cnic=family.cnic, phone=family.phone, email=family.email, is_primary=True,
        ))
    if family.mother_name:
        db.add(Guardian(family_id=family.id, name=family.mother_name, relation="mother"))

    audit.record(db, actor=actor, entity_type=audit.FAMILY, action="created",
                 entity_id=family.id, new_value=family.to_dict())
    return family


# ─── Credentials ──────────────────────────────────────────────────────────────

_PASSWORD_ALPHABET = string.ascii_letters.replace("l", "").replace("O", "") + string.digits.replace("0", "").replace("1", "")


def generate_password(length: int = 8) -> str:
    """A password a parent can read off a slip and type without a support call.

    Ambiguous characters are removed — l against 1, O against 0 — because the
    cost of a confusing password here is a phone call to the office, not a
    security incident: it is temporary and must be changed at first login.
    """
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


async def _unique_login_id(db: AsyncSession, preferred: str) -> str:
    """The admission number, unless something already holds it."""
    candidate = preferred
    suffix = 1
    while True:
        result = await db.execute(select(User.id).where(User.login_id == candidate))
        if result.scalar_one_or_none() is None:
            return candidate
        suffix += 1
        candidate = f"{preferred}-{suffix}"


# ─── The admission ────────────────────────────────────────────────────────────

async def create_admission(db: AsyncSession, *, data: dict, actor: User | None = None) -> Admission:
    """Record an enquiry or application. No account is created here."""
    if not (data.get("student_name") or "").strip():
        raise AdmissionError("The student's name is required.")

    session = await current_session(db)
    campus = await default_campus(db)
    application_no = await numbering.allocate_one(
        db, numbering.SCOPE_ADMISSION_APPLICATION,
        session_name=session.name if session else "",
    )

    admission = Admission(
        campus_id=campus.id,
        application_no=application_no,
        status=data.get("status") or ADMISSION_INQUIRY,
        session_id=session.id if session else None,
        created_by=actor.id if actor else None,
        **{k: v for k, v in data.items() if k in {
            "student_name", "father_name", "mother_name", "date_of_birth", "gender",
            "b_form", "phone", "address", "previous_school", "previous_class",
            "class_applied_id", "section_id", "family_id", "guardian_name",
            "guardian_phone", "emergency_contact", "emergency_phone", "remarks",
            "inquiry_source",
        }},
    )
    db.add(admission)
    await db.flush()

    audit.record(db, actor=actor, entity_type="admission", action="created",
                 entity_id=admission.id, new_value={"application_no": application_no,
                                                    "student_name": admission.student_name})
    return admission


async def confirm_admission(
    db: AsyncSession,
    admission: Admission,
    *,
    actor: User | None = None,
    create_family_if_missing: bool = True,
) -> dict:
    """Turn an approved admission into a student who can log in.

    One transaction. The caller commits, and if anything raises, nothing at all
    happened — no orphan GR number, no account without a class.
    """
    if admission.status == ADMISSION_CONFIRMED:
        raise AdmissionError(f"{admission.student_name} has already been admitted.")
    if not admission.class_applied_id:
        raise AdmissionError("Choose which class this student is joining first.")

    session = await current_session(db)
    if session is None:
        raise AdmissionError("There is no active academic session. Create one first.")

    result = await db.execute(select(SchoolClass).where(SchoolClass.id == admission.class_applied_id))
    school_class = result.scalar_one_or_none()
    if school_class is None:
        raise AdmissionError("That class no longer exists. Choose another one.")

    campus = await default_campus(db)

    # ── Family ──
    if admission.family_id is None and create_family_if_missing:
        family = await create_family(
            db,
            father_name=admission.father_name,
            mother_name=admission.mother_name,
            phone=admission.phone or admission.guardian_phone,
            address=admission.address,
            actor=actor,
        )
        admission.family_id = family.id

    # ── Numbers ──
    gr_no = admission.gr_no or await numbering.allocate_one(db, numbering.SCOPE_GR)
    admission_no = admission.admission_no or await numbering.allocate_one(db, numbering.SCOPE_ADMISSION)

    # ── Account ──
    login_id = await _unique_login_id(db, admission_no)
    password = generate_password()
    student = User(
        name=admission.student_name.strip(),
        login_id=login_id,
        password_hash=hash_password(password),
        role="student",
        # The legacy free-text columns are populated too. Every existing screen
        # in LSS Bot — the classroom, the chatbot, assignments — reads these,
        # and a new student who is invisible to them is not a student.
        class_name=school_class.canonical_name,
        section=None,
        father_name=admission.father_name,
        is_active=True,
        must_change_password=True,
    )

    if admission.section_id:
        result = await db.execute(select(Section).where(Section.id == admission.section_id))
        section = result.scalar_one_or_none()
        if section is not None:
            student.section = section.name

    db.add(student)
    await db.flush()

    # ── Profile ──
    db.add(StudentProfile(
        user_id=student.id,
        campus_id=campus.id,
        gr_no=gr_no,
        admission_no=admission_no,
        registration_no=login_id,
        family_id=admission.family_id,
        date_of_birth=admission.date_of_birth,
        gender=admission.gender,
        b_form=admission.b_form,
        phone=admission.phone,
        address=admission.address,
        admission_date=date.today(),
        previous_school=admission.previous_school,
        previous_class=admission.previous_class,
        emergency_contact=admission.emergency_contact,
        emergency_phone=admission.emergency_phone,
        status=STUDENT_ACTIVE,
        source=SOURCE_MANUAL,
    ))

    # ── Enrolment ──
    db.add(Enrollment(
        student_user_id=student.id,
        session_id=session.id,
        class_id=school_class.id,
        section_id=admission.section_id,
        status=ENROLL_ENROLLED,
        enrolled_on=date.today(),
        source=SOURCE_MANUAL,
    ))

    # ── Close the admission ──
    admission.status = ADMISSION_CONFIRMED
    admission.student_user_id = student.id
    admission.gr_no = gr_no
    admission.admission_no = admission_no
    admission.admission_date = date.today()
    admission.confirmed_by = actor.id if actor else None
    admission.confirmed_at = utcnow()

    # ── Tell the rest of the system ──
    events.emit(
        db, events.STUDENT_ADMISSION_CONFIRMED,
        {
            "student_user_id": student.id,
            "admission_id": admission.id,
            "gr_no": gr_no,
            "class_id": school_class.id,
            "section_id": admission.section_id,
            "session_id": session.id,
            "family_id": admission.family_id,
        },
        dedupe_key=f"admission_confirmed:{admission.id}",
    )

    audit.record(
        db, actor=actor, entity_type="admission", action="confirmed",
        entity_id=admission.id,
        new_value={"student_user_id": student.id, "gr_no": gr_no,
                   "admission_no": admission_no, "class": school_class.canonical_name,
                   "login_id": login_id},
    )

    # The password is returned, never stored and never logged. It exists for
    # exactly as long as it takes to print the slip.
    return {
        "student_user_id": student.id,
        "name": student.name,
        "gr_no": gr_no,
        "admission_no": admission_no,
        "login_id": login_id,
        "password": password,
        "class_name": school_class.canonical_name,
        "section": student.section,
        "family_id": admission.family_id,
    }

"""
ERP foundations (blueprint Part 1).

Everything here is *additive*. `users` is untouched and remains the single
authentication record; ERP detail hangs off it through profile tables keyed by
`user_id`. Nothing in this module changes what an existing dashboard, query or
serializer sees, which is what makes the ERP safe to deploy against a live
school.

Three ideas carry the whole module:

  * **A class is a row, not a string.** The rest of LSS Bot stores "Class 5",
    "Grade 5" and "Grade 5 - A" as free text and reconciles them at comparison
    time through `services.class_matching`. That is fine for a classroom and
    hopeless for a fee ledger, so the ERP gets real `school_classes`,
    `sections` and `enrollments` rows — and `class_aliases` keeps the old
    spellings resolvable, so both worlds stay true at once.

  * **A number is allocated, never guessed.** GR No., Admission No. and
    Employee No. come from `number_series` under a row lock, so two admissions
    recorded in the same second cannot collide.

  * **An identity is permanent.** `users.id` stays the internal identity
    forever. GR No. and Employee No. are institutional labels carried by a
    profile — never a primary key, never a foreign key target.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, Numeric,
    String, Text, UniqueConstraint, Index,
)

from config.database import Base
from models.models import gen_uuid, utcnow


# ─── Status vocabularies ──────────────────────────────────────────────────────
# Kept as module constants rather than database enums: a school changes its
# vocabulary more often than it changes its schema.

SESSION_PLANNING = "planning"
SESSION_ACTIVE = "active"
SESSION_CLOSED = "closed"

ENROLL_ENROLLED = "enrolled"
ENROLL_PROMOTED = "promoted"
ENROLL_RETAINED = "retained"
ENROLL_WITHDRAWN = "withdrawn"
ENROLL_GRADUATED = "graduated"

STUDENT_ACTIVE = "active"
STUDENT_WITHDRAWN = "withdrawn"
STUDENT_GRADUATED = "graduated"

EMP_ACTIVE = "active"
EMP_PROBATION = "probation"
EMP_RESIGNED = "resigned"
EMP_TERMINATED = "terminated"

# Where a record came from. `legacy` means the backfill derived it from data
# that already existed in LSS Bot, which is worth being able to ask about
# later — those rows carry assumptions that a hand-entered row does not.
SOURCE_LEGACY = "legacy"
SOURCE_MANUAL = "manual"
SOURCE_IMPORT = "import"


# ─── Academic structure ───────────────────────────────────────────────────────

class AcademicSession(Base):
    """One school year. Everything dated hangs off a session."""
    __tablename__ = "academic_sessions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(40), nullable=False, unique=True)      # "2026-2027"
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(String(20), nullable=False, default=SESSION_PLANNING)
    # Exactly one session is current; the API enforces it so no screen ever has
    # to ask "which session?" when there is an obvious answer.
    is_current = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "status": self.status,
            "is_current": bool(self.is_current),
        }


class SchoolClass(Base):
    """A class the school teaches — "Class 5", "Nursery", "Pre-Board"."""
    __tablename__ = "school_classes"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    canonical_name = Column(String(50), nullable=False, unique=True)
    # pre_primary | primary | middle | secondary — drives report card formats
    # and fee bands later; set by the backfill from the canonical name.
    level = Column(String(20), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "canonical_name": self.canonical_name,
            "level": self.level,
            "sort_order": self.sort_order,
            "is_active": bool(self.is_active),
        }


class ClassAlias(Base):
    """A spelling of a class that exists somewhere in the legacy data.

    "Grade 5", "V", "5-A" and "Class 5 Boys" all point at one class row. This
    is what lets the ERP read records written by the old free-text world
    without anyone having to clean them up first.
    """
    __tablename__ = "class_aliases"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    class_id = Column(String(36), ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    # Stored already normalised (lower-cased canonical key), so lookup is exact.
    alias_key = Column(String(80), nullable=False, unique=True)
    alias_label = Column(String(80), nullable=True)   # as originally written
    created_at = Column(DateTime, default=utcnow)


class Section(Base):
    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("class_id", "name", name="uq_section_class_name"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    class_id = Column(String(36), ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(30), nullable=False)          # "A"
    capacity = Column(Integer, nullable=True)
    class_teacher_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "class_id": self.class_id, "name": self.name,
            "capacity": self.capacity, "class_teacher_id": self.class_teacher_id,
            "is_active": bool(self.is_active),
        }


class Subject(Base):
    __tablename__ = "subjects"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(100), nullable=False, unique=True)
    short_name = Column(String(20), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "short_name": self.short_name,
                "is_active": bool(self.is_active)}


class ClassSubject(Base):
    """Which subjects a class studies. Populates exam configuration and
    report cards without anyone re-typing a subject list per exam."""
    __tablename__ = "class_subjects"
    __table_args__ = (
        UniqueConstraint("class_id", "subject_id", name="uq_class_subject"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    class_id = Column(String(36), ForeignKey("school_classes.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = Column(String(36), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    is_optional = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)


class Enrollment(Base):
    """A student in a class, in a section, for one session.

    This is the keystone of the ERP. "Which class is this student in" stops
    being a string on `users` and becomes a row per session — which is the only
    reason promotion, last year's report card and last year's defaulters are
    answerable at all.
    """
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_user_id", "session_id", name="uq_enrollment_student_session"),
        Index("ix_enrollment_session_class_section", "session_id", "class_id", "section_id"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("academic_sessions.id"), nullable=False, index=True)
    class_id = Column(String(36), ForeignKey("school_classes.id"), nullable=False, index=True)
    section_id = Column(String(36), ForeignKey("sections.id"), nullable=True, index=True)
    roll_no = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, default=ENROLL_ENROLLED)
    enrolled_on = Column(Date, nullable=True)
    left_on = Column(Date, nullable=True)
    source = Column(String(20), nullable=False, default=SOURCE_MANUAL)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class TeacherAssignment(Base):
    """What a teacher teaches, as rows.

    The legacy JSON columns on `users` (`assigned_classes`, `assigned_sections`,
    `subjects`) stay exactly where they are and keep being written — classroom
    authorization reads them, and breaking that would lock teachers out of live
    lessons. These rows are the ERP's view of the same facts.
    """
    __tablename__ = "teacher_assignments"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "teacher_user_id", "class_id", "section_id", "subject_id",
            name="uq_teacher_assignment",
        ),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("academic_sessions.id"), nullable=False, index=True)
    teacher_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    class_id = Column(String(36), ForeignKey("school_classes.id"), nullable=False, index=True)
    section_id = Column(String(36), ForeignKey("sections.id"), nullable=True)
    subject_id = Column(String(36), ForeignKey("subjects.id"), nullable=True)
    is_class_teacher = Column(Boolean, nullable=False, default=False)
    source = Column(String(20), nullable=False, default=SOURCE_MANUAL)
    created_at = Column(DateTime, default=utcnow)


# ─── People ───────────────────────────────────────────────────────────────────

class Family(Base):
    """One household. Siblings link here, and so do family-level concessions."""
    __tablename__ = "families"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    family_code = Column(String(30), nullable=False, unique=True)
    father_name = Column(String(150), nullable=True, index=True)
    mother_name = Column(String(150), nullable=True)
    guardian_name = Column(String(150), nullable=True)
    guardian_relation = Column(String(40), nullable=True)
    cnic = Column(String(20), nullable=True, index=True)
    phone = Column(String(30), nullable=True, index=True)
    alt_phone = Column(String(30), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    source = Column(String(20), nullable=False, default=SOURCE_MANUAL)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "family_code": self.family_code,
            "father_name": self.father_name, "mother_name": self.mother_name,
            "guardian_name": self.guardian_name, "cnic": self.cnic,
            "phone": self.phone, "email": self.email, "address": self.address,
        }


class StudentProfile(Base):
    """ERP detail for a student. One row per student `users` record.

    `registration_no` is a copy of the login id the student already uses, so
    nobody loses the number they know. GR No. and Admission No. are separate
    fields with separate series — the specification is emphatic that they are
    not the same identifier, and the schema enforces it.
    """
    __tablename__ = "student_profiles"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    gr_no = Column(String(30), nullable=True, unique=True, index=True)
    admission_no = Column(String(30), nullable=True, unique=True, index=True)
    registration_no = Column(String(50), nullable=True, index=True)
    family_id = Column(String(36), ForeignKey("families.id"), nullable=True, index=True)

    date_of_birth = Column(Date, nullable=True)
    gender = Column(String(10), nullable=True)
    b_form = Column(String(20), nullable=True)
    phone = Column(String(30), nullable=True)
    address = Column(Text, nullable=True)
    photo_key = Column(String(300), nullable=True)      # MinIO object key

    admission_date = Column(Date, nullable=True)
    previous_school = Column(String(200), nullable=True)
    previous_class = Column(String(50), nullable=True)
    emergency_contact = Column(String(100), nullable=True)
    emergency_phone = Column(String(30), nullable=True)

    status = Column(String(20), nullable=False, default=STUDENT_ACTIVE)
    left_on = Column(Date, nullable=True)
    leaving_reason = Column(String(200), nullable=True)
    remarks = Column(Text, nullable=True)
    source = Column(String(20), nullable=False, default=SOURCE_MANUAL)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Fields payroll/admissions will need that nobody has entered yet. Kept as
    # data rather than computed on the fly so "what is missing" is one indexed
    # query instead of a scan of every profile.
    MANDATORY_FIELDS = ("gr_no", "date_of_birth", "gender", "phone")

    def missing_fields(self) -> list[str]:
        return [f for f in self.MANDATORY_FIELDS if not getattr(self, f, None)]

    def to_dict(self):
        return {
            "user_id": self.user_id, "gr_no": self.gr_no,
            "admission_no": self.admission_no, "registration_no": self.registration_no,
            "family_id": self.family_id,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "gender": self.gender, "b_form": self.b_form, "phone": self.phone,
            "address": self.address,
            "admission_date": self.admission_date.isoformat() if self.admission_date else None,
            "previous_school": self.previous_school,
            "status": self.status,
            "missing_fields": self.missing_fields(),
        }


class EmployeeProfile(Base):
    """ERP detail for a teacher or staff member. One row per `users` record.

    Salary lives in its own table in a later phase — never here, and never only
    inside an appointment letter.
    """
    __tablename__ = "employee_profiles"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    employee_no = Column(String(30), nullable=True, unique=True, index=True)
    registration_no = Column(String(50), nullable=True, index=True)

    cnic = Column(String(20), nullable=True, index=True)
    father_or_husband_name = Column(String(150), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String(10), nullable=True)
    phone = Column(String(30), nullable=True)
    address = Column(Text, nullable=True)
    photo_key = Column(String(300), nullable=True)
    emergency_contact = Column(String(100), nullable=True)
    emergency_phone = Column(String(30), nullable=True)

    designation = Column(String(100), nullable=True)
    department = Column(String(100), nullable=True)
    joining_date = Column(Date, nullable=True)
    employment_type = Column(String(30), nullable=True)      # permanent | contract | visiting
    employment_status = Column(String(20), nullable=False, default=EMP_ACTIVE)
    qualification = Column(String(200), nullable=True)
    experience_years = Column(Numeric(4, 1), nullable=True)

    bank_name = Column(String(100), nullable=True)
    bank_account = Column(String(40), nullable=True)
    bank_iban = Column(String(40), nullable=True)

    left_on = Column(Date, nullable=True)
    leaving_reason = Column(String(200), nullable=True)
    remarks = Column(Text, nullable=True)
    source = Column(String(20), nullable=False, default=SOURCE_MANUAL)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # What payroll cannot run without. Shown to the office as a short list of
    # gaps per employee rather than as one intimidating form (spec §4).
    MANDATORY_FIELDS = ("employee_no", "cnic", "joining_date", "designation")

    def missing_fields(self) -> list[str]:
        return [f for f in self.MANDATORY_FIELDS if not getattr(self, f, None)]

    def to_dict(self):
        return {
            "user_id": self.user_id, "employee_no": self.employee_no,
            "cnic": self.cnic, "designation": self.designation,
            "department": self.department,
            "joining_date": self.joining_date.isoformat() if self.joining_date else None,
            "employment_type": self.employment_type,
            "employment_status": self.employment_status,
            "qualification": self.qualification, "phone": self.phone,
            "bank_name": self.bank_name, "bank_iban": self.bank_iban,
            "missing_fields": self.missing_fields(),
        }


# ─── Institutional numbering ──────────────────────────────────────────────────

class NumberSeries(Base):
    """Configurable number generation for GR No., Admission No., Employee No.,
    vouchers, receipts and journals.

    Allocation happens inside the caller's transaction under a row lock, so two
    admissions saved in the same second cannot receive the same GR No.
    """
    __tablename__ = "number_series"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    scope = Column(String(40), nullable=False, unique=True)   # "gr_no", "employee_no", …
    label = Column(String(80), nullable=True)
    # Python format string over {seq} and {session}: "LSS-{seq:05d}"
    pattern = Column(String(80), nullable=False, default="{seq:05d}")
    next_value = Column(Integer, nullable=False, default=1)
    reset_policy = Column(String(20), nullable=False, default="never")   # never | per_session
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def preview(self) -> str:
        try:
            return self.pattern.format(seq=self.next_value, session="")
        except Exception:
            return str(self.next_value)

    def to_dict(self):
        return {
            "id": self.id, "scope": self.scope, "label": self.label,
            "pattern": self.pattern, "next_value": self.next_value,
            "preview": self.preview(), "is_active": bool(self.is_active),
        }


# ─── Access control ───────────────────────────────────────────────────────────

class Role(Base):
    """An ERP role. `users.role` keeps its existing values and its existing
    meaning; these sit beside it and carry permissions."""
    __tablename__ = "roles"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    key = Column(String(40), nullable=False, unique=True)     # "erp_accounts_manager"
    name = Column(String(80), nullable=False)
    description = Column(Text, nullable=True)
    # System roles cannot be deleted or have their key changed.
    is_system = Column(Boolean, nullable=False, default=False)
    # Lower rank = more authority. The Owner is 0 and is protected everywhere.
    rank = Column(Integer, nullable=False, default=100)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {"id": self.id, "key": self.key, "name": self.name,
                "description": self.description, "rank": self.rank,
                "is_system": bool(self.is_system)}


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_key", name="uq_role_permission"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    role_id = Column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)
    permission_key = Column(String(60), nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)


class UserRole(Base):
    """A user may hold several roles; permissions are the union."""
    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(String(36), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    granted_at = Column(DateTime, default=utcnow)


# ─── Audit ────────────────────────────────────────────────────────────────────

class AuditLog(Base):
    """Append-only. Written in the same transaction as the change it records,
    so an audited change cannot commit without its audit row.

    This deliberately differs from `services.audit_service`, which swallows
    failures — correct for a lesson plan, wrong for a salary revision.
    """
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_occurred", "occurred_at"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    occurred_at = Column(DateTime, nullable=False, default=utcnow)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    actor_name = Column(String(100), nullable=True)
    actor_role = Column(String(40), nullable=True)
    ip = Column(String(60), nullable=True)

    entity_type = Column(String(40), nullable=False)
    entity_id = Column(String(36), nullable=True)
    action = Column(String(40), nullable=False)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    reason = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "actor_name": self.actor_name, "actor_role": self.actor_role,
            "entity_type": self.entity_type, "entity_id": self.entity_id,
            "action": self.action, "old_value": self.old_value,
            "new_value": self.new_value, "reason": self.reason,
        }


# ─── Events ───────────────────────────────────────────────────────────────────

EVENT_PENDING = "pending"
EVENT_DONE = "done"
EVENT_FAILED = "failed"


class DomainEvent(Base):
    """Transactional outbox.

    The business change and its event row commit together, and a worker drains
    them afterwards. That is what makes "enter once, everything knows" reliable
    without adding a message broker to a stack that already runs Celery.

    `dedupe_key` is unique: a retry cannot post a fee twice or issue a second
    voucher.
    """
    __tablename__ = "domain_events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    event_type = Column(String(60), nullable=False, index=True)
    payload = Column(JSON, nullable=True)
    dedupe_key = Column(String(120), nullable=True, unique=True)
    status = Column(String(20), nullable=False, default=EVENT_PENDING, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    occurred_at = Column(DateTime, nullable=False, default=utcnow)
    processed_at = Column(DateTime, nullable=True)


# ─── Feature flags ────────────────────────────────────────────────────────────

class FeatureFlag(Base):
    """Every ERP module ships behind one of these, defaulting off.

    A module can be switched off mid-morning without a deployment, which is
    what makes a bad Monday recoverable.
    """
    __tablename__ = "feature_flags"

    key = Column(String(60), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    # Empty list = everyone (once enabled). Otherwise only these role keys see it.
    roles = Column(JSON, nullable=True, default=list)
    note = Column(Text, nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {"key": self.key, "enabled": bool(self.enabled),
                "roles": self.roles or [], "note": self.note}

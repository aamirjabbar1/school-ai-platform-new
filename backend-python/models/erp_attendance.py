"""
Daily attendance (ERP phase 3).

This is the first module a teacher touches every single morning, so the schema
is shaped by the screen rather than the other way round: one row per class per
day that says *who took the register and when*, and one row per child that says
what they were.

Two decisions worth keeping:

  * **Absence is recorded, not inferred.** A day with no `attendance_days` row
    is a register nobody took — which is a question for the office, not an
    empty class. Inferring "everyone present" from silence would make missing
    attendance invisible, and missing attendance is the single most useful
    thing this module can surface.

  * **A correction is a new fact, not an overwrite.** `source` and the audit
    trail together answer "who changed this child from absent to present, and
    when" — the question that actually gets asked, usually a month later.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Index, String, Text,
    UniqueConstraint,
)

from config.database import Base
from models.models import gen_uuid, utcnow


# What a child can be on a given day. Configurable in the sense that adding one
# is a constant here plus a button — no migration.
ATT_PRESENT = "present"
ATT_ABSENT = "absent"
ATT_LEAVE = "leave"
ATT_LATE = "late"
ATT_HALF_DAY = "half_day"

ATTENDANCE_STATUSES = (ATT_PRESENT, ATT_ABSENT, ATT_LEAVE, ATT_LATE, ATT_HALF_DAY)

# Statuses that count as "in school" when a percentage is computed. Late and
# half-day count as present because a school that marks a late child absent
# ends up with two arguments instead of one.
PRESENT_STATUSES = (ATT_PRESENT, ATT_LATE, ATT_HALF_DAY)

# Where the mark came from.
ATT_SOURCE_TEACHER = "teacher"
ATT_SOURCE_ONLINE = "online_class"
ATT_SOURCE_CORRECTION = "correction"

DAY_DRAFT = "draft"
DAY_SUBMITTED = "submitted"


class AttendanceDay(Base):
    """One class's register for one date."""
    __tablename__ = "attendance_days"
    __table_args__ = (
        UniqueConstraint("session_id", "class_id", "section_id", "date",
                         name="uq_attendance_day"),
        Index("ix_attendance_day_date", "date"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("academic_sessions.id"), nullable=False, index=True)
    class_id = Column(String(36), ForeignKey("school_classes.id"), nullable=False, index=True)
    # Null means the whole class was taken as one register — which is right for
    # a class that has no sections.
    section_id = Column(String(36), ForeignKey("sections.id"), nullable=True, index=True)
    date = Column(Date, nullable=False)

    status = Column(String(20), nullable=False, default=DAY_SUBMITTED)
    marked_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    marked_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "class_id": self.class_id,
            "section_id": self.section_id,
            "date": self.date.isoformat() if self.date else None,
            "status": self.status,
            "marked_by": self.marked_by,
            "marked_at": self.marked_at.isoformat() if self.marked_at else None,
        }


class AttendanceRecord(Base):
    """One child, one day."""
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("day_id", "student_user_id", name="uq_attendance_record"),
        Index("ix_attendance_student", "student_user_id"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    day_id = Column(String(36), ForeignKey("attendance_days.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    student_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    status = Column(String(20), nullable=False, default=ATT_PRESENT)
    source = Column(String(20), nullable=False, default=ATT_SOURCE_TEACHER)
    note = Column(String(200), nullable=True)
    marked_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class LeaveRequest(Base):
    """Staff leave.

    Here rather than in the payroll phase on purpose: §24 of the specification
    wants salary prorated for unpaid leave, and payroll cannot prorate against
    data that does not exist. This is the smallest thing that makes that
    possible — a dated range, a type, and an approval.
    """
    __tablename__ = "leave_requests"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    employee_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    # casual | sick | annual | unpaid | maternity — unpaid is the one payroll cares about
    leave_type = Column(String(30), nullable=False, default="casual")
    from_date = Column(Date, nullable=False)
    to_date = Column(Date, nullable=False)
    days = Column(String(10), nullable=True)          # "1", "0.5" — half days happen
    reason = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pending")   # pending|approved|rejected
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    is_paid = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "employee_user_id": self.employee_user_id,
            "leave_type": self.leave_type,
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "days": self.days, "reason": self.reason, "status": self.status,
            "is_paid": bool(self.is_paid),
        }

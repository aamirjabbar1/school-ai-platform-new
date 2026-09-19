"""
Examinations (ERP phase 7).

The specification's hardest requirement in this module is §81.F: the combined
ledger and the combined report card must never disagree. That is a schema
problem before it is a code problem — if weightage lives in two places, two
answers eventually exist. So:

  * A weightage scheme is **data** (`result_schemes` + `scheme_components`),
    configurable per session and per class, validated to total 100 before it
    can publish. Never a constant, never a formula in a template.
  * Marks are stored raw. Every percentage, grade and weighted total is derived
    by one service at read time, so there is nothing stored that can drift.

Absent, exempt and zero are three different things and are stored as three
different things. A child who missed an exam has not scored nothing; averaging
them as zero is how a grade becomes a grievance.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint,
)

from config.database import Base
from models.models import gen_uuid, utcnow


# The structure LSS runs today (§37). Configurable: adding one is a row.
EXAM_MONTHLY = "monthly"
EXAM_MID = "mid_term"
EXAM_FINAL = "final_term"
EXAM_TYPES = (EXAM_MONTHLY, EXAM_MID, EXAM_FINAL)

EXAM_PLANNED = "planned"
EXAM_MARKS_ENTRY = "marks_entry"
EXAM_REVIEW = "review"
EXAM_PUBLISHED = "published"

MARKS_DRAFT = "draft"
MARKS_SUBMITTED = "submitted"
MARKS_APPROVED = "approved"

# Once marks are submitted the teacher's edit is closed; after approval only a
# reason-carrying correction reopens it.
MARKS_LOCKED_STATES = (MARKS_SUBMITTED, MARKS_APPROVED)


class Exam(Base):
    """One examination in one session."""
    __tablename__ = "exams"
    __table_args__ = (
        UniqueConstraint("session_id", "name", name="uq_exam_session_name"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("academic_sessions.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)        # "First Monthly Test"
    exam_type = Column(String(20), nullable=False, default=EXAM_MONTHLY)
    sequence = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default=EXAM_PLANNED, index=True)

    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "name": self.name,
            "exam_type": self.exam_type, "sequence": self.sequence,
            "status": self.status,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


class ExamSubject(Base):
    """One subject of one exam for one class — the paper, and what it is worth."""
    __tablename__ = "exam_subjects"
    __table_args__ = (
        UniqueConstraint("exam_id", "class_id", "subject_id", name="uq_exam_subject"),
        Index("ix_exam_subject_class", "exam_id", "class_id"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    exam_id = Column(String(36), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    class_id = Column(String(36), ForeignKey("school_classes.id"), nullable=False, index=True)
    subject_id = Column(String(36), ForeignKey("subjects.id"), nullable=False, index=True)

    max_marks = Column(Numeric(6, 2), nullable=False, default=100)
    passing_marks = Column(Numeric(6, 2), nullable=False, default=33)
    # A practical paper sits beside the theory one rather than in a second
    # subject, so the report card shows one line for Science.
    practical_max = Column(Numeric(6, 2), nullable=False, default=0)
    practical_passing = Column(Numeric(6, 2), nullable=False, default=0)

    exam_date = Column(Date, nullable=True)
    start_time = Column(String(10), nullable=True)
    room = Column(String(60), nullable=True)
    is_optional = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "exam_id": self.exam_id, "class_id": self.class_id,
            "subject_id": self.subject_id,
            "max_marks": str(self.max_marks), "passing_marks": str(self.passing_marks),
            "practical_max": str(self.practical_max),
            "exam_date": self.exam_date.isoformat() if self.exam_date else None,
            "start_time": self.start_time, "room": self.room,
            "is_optional": bool(self.is_optional),
        }


class Mark(Base):
    """What one child scored in one paper. Raw — nothing derived is stored."""
    __tablename__ = "marks"
    __table_args__ = (
        UniqueConstraint("exam_subject_id", "student_user_id", name="uq_mark"),
        Index("ix_mark_student", "student_user_id"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    exam_subject_id = Column(String(36), ForeignKey("exam_subjects.id", ondelete="CASCADE"),
                             nullable=False, index=True)
    student_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)

    obtained = Column(Numeric(6, 2), nullable=True)
    practical_obtained = Column(Numeric(6, 2), nullable=True)

    # Three different facts, stored as three different things. A child who
    # missed the paper has not scored nothing, and a child excused from it
    # should not be averaged at all.
    is_absent = Column(Boolean, nullable=False, default=False)
    is_exempt = Column(Boolean, nullable=False, default=False)

    status = Column(String(20), nullable=False, default=MARKS_DRAFT)
    entered_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    entered_at = Column(DateTime, nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    remark = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "exam_subject_id": self.exam_subject_id,
            "student_user_id": self.student_user_id,
            "obtained": str(self.obtained) if self.obtained is not None else None,
            "practical_obtained": str(self.practical_obtained)
                                  if self.practical_obtained is not None else None,
            "is_absent": bool(self.is_absent), "is_exempt": bool(self.is_exempt),
            "status": self.status, "remark": self.remark,
        }


class GradeScale(Base):
    """A named grading scale. A school usually has one; preschools often have
    their own, which is why it is a row rather than a constant."""
    __tablename__ = "grade_scales"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(80), nullable=False, unique=True)
    is_default = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "is_default": bool(self.is_default)}


class GradeBand(Base):
    """One band of a scale: 80 and above is an A+."""
    __tablename__ = "grade_bands"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    scale_id = Column(String(36), ForeignKey("grade_scales.id", ondelete="CASCADE"),
                      nullable=False, index=True)
    min_percent = Column(Numeric(5, 2), nullable=False)
    grade = Column(String(10), nullable=False)
    grade_point = Column(Numeric(4, 2), nullable=True)
    remark = Column(String(60), nullable=True)

    def to_dict(self):
        return {"min_percent": str(self.min_percent), "grade": self.grade,
                "grade_point": str(self.grade_point) if self.grade_point is not None else None,
                "remark": self.remark}


class ResultScheme(Base):
    """How exams combine into one result (§45, §46, §81.C).

    Weightage is configurable per session and per class, and a scheme cannot
    publish until its components total 100. The same scheme drives the combined
    ledger and the combined report card — one scheme, one engine, one answer.
    """
    __tablename__ = "result_schemes"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("academic_sessions.id"), nullable=False, index=True)
    # Null means every class in the session.
    class_id = Column(String(36), ForeignKey("school_classes.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    grade_scale_id = Column(String(36), ForeignKey("grade_scales.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    # Position is published only if LSS policy says so (§81.E).
    show_position = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {"id": self.id, "session_id": self.session_id, "class_id": self.class_id,
                "name": self.name, "is_active": bool(self.is_active),
                "show_position": bool(self.show_position)}


class SchemeComponent(Base):
    """One exam's share of a combined result."""
    __tablename__ = "scheme_components"
    __table_args__ = (
        UniqueConstraint("scheme_id", "exam_id", name="uq_scheme_component"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    scheme_id = Column(String(36), ForeignKey("result_schemes.id", ondelete="CASCADE"),
                       nullable=False, index=True)
    exam_id = Column(String(36), ForeignKey("exams.id"), nullable=False)
    weight_percent = Column(Numeric(5, 2), nullable=False, default=0)

    def to_dict(self):
        return {"exam_id": self.exam_id, "weight_percent": str(self.weight_percent)}


class ReportRemark(Base):
    """The sentence a teacher or the principal writes on a report card."""
    __tablename__ = "report_remarks"
    __table_args__ = (
        UniqueConstraint("student_user_id", "scheme_id", "exam_id", name="uq_report_remark"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    scheme_id = Column(String(36), ForeignKey("result_schemes.id"), nullable=True)
    exam_id = Column(String(36), ForeignKey("exams.id"), nullable=True)
    teacher_remark = Column(Text, nullable=True)
    principal_remark = Column(Text, nullable=True)
    promotion_status = Column(String(30), nullable=True)   # promoted|retained|conditional
    written_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {"teacher_remark": self.teacher_remark,
                "principal_remark": self.principal_remark,
                "promotion_status": self.promotion_status}

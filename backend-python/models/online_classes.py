"""
Online Classes — database models.

Kept in its own module (rather than models/models.py) so the classroom can be
maintained independently of the rest of LSS Bot. Nothing here modifies an
existing table; `users`, `documents` and `lesson_plans` are referenced by
foreign key only.

Layering (see docs/ONLINE_CLASSES_ARCHITECTURE.md):

  1. Live classroom state      OnlineClassSession, OnlineClassParticipant
  2. Structured academic data  OnlineClassEvent, OnlineClassResource,
                               OnlineClassWhiteboard, OnlineClassLessonRecord
  3. AI enhancement layer      OnlineClassAIOutput, OnlineClassAIQuestion,
                               AIUsageEvent

Layer 3 reads layer 2. Layer 2 is written by ordinary application logic during
the class — never by an AI model, and never from classroom audio: no
Speech-to-Text exists anywhere in this system.
"""
from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, DateTime, Date, Time,
    ForeignKey, JSON, Index,
)

from models.models import Base, gen_uuid, utcnow


# ─── Status vocabularies ──────────────────────────────────────────────────────

SESSION_SCHEDULED = "scheduled"
SESSION_LIVE = "live"
SESSION_ENDED = "ended"
SESSION_CANCELLED = "cancelled"

ATTEND_PRESENT = "present"
ATTEND_LATE = "late"
ATTEND_PARTIAL = "partial"
ATTEND_ABSENT = "absent"

# Stage = what the students' main content area is showing. The teacher owns it;
# students follow automatically (spec §11).
STAGE_CAMERA = "camera"
STAGE_BOOK = "book"
STAGE_WHITEBOARD = "whiteboard"
STAGE_SCREEN = "screen"
STAGE_MODES = (STAGE_CAMERA, STAGE_BOOK, STAGE_WHITEBOARD, STAGE_SCREEN)


# ─── SCHEDULE ─────────────────────────────────────────────────────────────────

class OnlineClassSchedule(Base):
    """A recurring weekly slot or a one-off planned class (spec §20)."""
    __tablename__ = "online_class_schedules"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    teacher_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    subject = Column(String(100), nullable=False)
    class_name = Column(String(50), nullable=False)
    section = Column(String(50), nullable=True)
    title = Column(String(200), nullable=True)

    # "weekly" | "once"
    recurrence = Column(String(20), nullable=False, default="weekly")
    # 0 = Monday … 6 = Sunday (weekly only)
    weekday = Column(Integer, nullable=True)
    # Calendar date (once only)
    class_date = Column(Date, nullable=True)
    start_time = Column(Time, nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=40)

    # Validity window for a weekly slot (term dates)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    recording_enabled = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "teacher_id": self.teacher_id, "subject": self.subject,
            "class_name": self.class_name, "section": self.section, "title": self.title,
            "recurrence": self.recurrence, "weekday": self.weekday,
            "class_date": self.class_date.isoformat() if self.class_date else None,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "duration_minutes": self.duration_minutes,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "recording_enabled": bool(self.recording_enabled),
            "is_active": bool(self.is_active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── SESSION ──────────────────────────────────────────────────────────────────

class OnlineClassSession(Base):
    """One classroom: scheduled, live, or finished.

    `room_name` is a UUID-derived string, so a classroom URL can never be
    guessed and no meeting ID or password is ever shown to a user (spec §1).
    """
    __tablename__ = "online_class_sessions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    schedule_id = Column(String(36), ForeignKey("online_class_schedules.id"), nullable=True)
    teacher_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    # Denormalised so history survives a teacher record changing.
    teacher_name = Column(String(100), nullable=True)

    subject = Column(String(100), nullable=False)
    class_name = Column(String(50), nullable=False)
    section = Column(String(50), nullable=True)
    title = Column(String(200), nullable=True)

    status = Column(String(20), nullable=False, default=SESSION_SCHEDULED, index=True)
    room_name = Column(String(80), nullable=False, unique=True)

    scheduled_start = Column(DateTime, nullable=True)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    planned_duration_minutes = Column(Integer, nullable=False, default=40)

    # Teaching state — students' main area follows this (spec §8, §11).
    stage_mode = Column(String(20), nullable=False, default=STAGE_CAMERA)
    # Per-mode state, e.g. {"book": {"document_id": …, "page": 42, "zoom": 1.2},
    #                       "whiteboard": {"page": 0}}
    stage_state = Column(JSON, nullable=True, default=dict)

    # Classroom policy for this session
    young_mode = Column(Boolean, nullable=False, default=False)
    mic_locked = Column(Boolean, nullable=False, default=True)
    cameras_locked = Column(Boolean, nullable=False, default=False)
    is_locked = Column(Boolean, nullable=False, default=False)
    low_bandwidth_default = Column(Boolean, nullable=False, default=False)

    recording_enabled = Column(Boolean, nullable=False, default=False)
    # off | starting | recording | stopping | done | failed
    recording_status = Column(String(20), nullable=False, default="off")

    lesson_plan_id = Column(String(36), ForeignKey("lesson_plans.id"), nullable=True)
    # Which lesson inside plan_data["lessons"] the teacher picked
    lesson_plan_ref = Column(String(120), nullable=True)

    # Set while the teacher is disconnected; the room survives a grace period
    # before auto-ending (spec §22).
    teacher_disconnected_at = Column(DateTime, nullable=True)
    end_reason = Column(String(40), nullable=True)   # teacher | admin | grace_timeout

    academic_session = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_ocs_class_section_status", "class_name", "section", "status"),
        Index("ix_ocs_teacher_status", "teacher_id", "status"),
    )

    @property
    def duration_seconds(self) -> int:
        """Elapsed class length, or the planned length if it never started."""
        if not self.actual_start:
            return (self.planned_duration_minutes or 0) * 60
        end = self.actual_end or utcnow()
        return max(0, int((end - self.actual_start).total_seconds()))

    def to_dict(self, include_state: bool = False):
        d = {
            "id": self.id, "schedule_id": self.schedule_id,
            "teacher_id": self.teacher_id, "teacher_name": self.teacher_name,
            "subject": self.subject, "class_name": self.class_name,
            "section": self.section, "title": self.title,
            "status": self.status,
            "scheduled_start": self.scheduled_start.isoformat() if self.scheduled_start else None,
            "actual_start": self.actual_start.isoformat() if self.actual_start else None,
            "actual_end": self.actual_end.isoformat() if self.actual_end else None,
            "planned_duration_minutes": self.planned_duration_minutes,
            "duration_seconds": self.duration_seconds,
            "young_mode": bool(self.young_mode),
            "recording_enabled": bool(self.recording_enabled),
            "recording_status": self.recording_status,
            "lesson_plan_id": self.lesson_plan_id,
            "academic_session": self.academic_session,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_state:
            d.update({
                "stage_mode": self.stage_mode,
                "stage_state": self.stage_state or {},
                "mic_locked": bool(self.mic_locked),
                "cameras_locked": bool(self.cameras_locked),
                "is_locked": bool(self.is_locked),
                "low_bandwidth_default": bool(self.low_bandwidth_default),
                "teacher_disconnected_at": (
                    self.teacher_disconnected_at.isoformat()
                    if self.teacher_disconnected_at else None
                ),
            })
        # room_name is deliberately never serialised to a client.
        return d


# ─── ATTENDANCE ───────────────────────────────────────────────────────────────

class OnlineClassParticipant(Base):
    """Per-user attendance summary for one session (spec §13).

    Built entirely from LiveKit webhook events by application logic. No AI is
    involved at any point.
    """
    __tablename__ = "online_class_participants"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="student")  # student | teacher | observer

    # Denormalised so an attendance register stays readable years later.
    user_name = Column(String(100), nullable=True)
    class_name = Column(String(50), nullable=True)
    section = Column(String(50), nullable=True)

    first_join_at = Column(DateTime, nullable=True)
    last_join_at = Column(DateTime, nullable=True)
    last_leave_at = Column(DateTime, nullable=True)
    total_seconds = Column(Integer, nullable=False, default=0)
    rejoin_count = Column(Integer, nullable=False, default=0)
    is_connected = Column(Boolean, nullable=False, default=False)

    attendance_percent = Column(Float, nullable=False, default=0.0)
    status = Column(String(20), nullable=False, default=ATTEND_ABSENT)
    finalized = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("ix_ocp_session_user", "session_id", "user_id", unique=True),
    )

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "user_id": self.user_id,
            "role": self.role, "user_name": self.user_name,
            "class_name": self.class_name, "section": self.section,
            "first_join_at": self.first_join_at.isoformat() if self.first_join_at else None,
            "last_leave_at": self.last_leave_at.isoformat() if self.last_leave_at else None,
            "total_seconds": self.total_seconds or 0,
            "total_minutes": round((self.total_seconds or 0) / 60, 1),
            "rejoin_count": self.rejoin_count or 0,
            "is_connected": bool(self.is_connected),
            "attendance_percent": round(self.attendance_percent or 0.0, 1),
            "status": self.status,
            "finalized": bool(self.finalized),
        }


class OnlineClassAttendanceEvent(Base):
    """Append-only join/leave ledger — the evidence behind the summary above."""
    __tablename__ = "online_class_attendance_events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    # join | leave | rejoin | reconciled
    event = Column(String(20), nullable=False)
    at = Column(DateTime, nullable=False, default=utcnow)
    participant_sid = Column(String(80), nullable=True)
    reason = Column(String(80), nullable=True)

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "user_id": self.user_id,
            "event": self.event, "at": self.at.isoformat() if self.at else None,
            "reason": self.reason,
        }


# ─── STRUCTURED CLASSROOM EVENTS ──────────────────────────────────────────────

class OnlineClassEvent(Base):
    """Everything meaningful that happened, recorded as it happened (spec §19E).

    This table is the *only* factual source the AI layer is allowed to reason
    over, together with the Knowledge Base and teacher-confirmed records. It
    exists so the AI never has to rediscover what the application already knows
    — and so nothing has to be inferred from speech.
    """
    __tablename__ = "online_class_events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    actor_role = Column(String(20), nullable=True)
    # class_started | class_ended | book_opened | page_presented | whiteboard_saved |
    # stage_changed | resource_opened | screen_share_started | screen_share_stopped |
    # hand_raised | hand_lowered | mic_granted | mic_revoked | mute_all |
    # student_removed | class_locked | recording_started | recording_stopped |
    # admin_observed | token_issued | join_denied
    type = Column(String(40), nullable=False, index=True)
    payload = Column(JSON, nullable=True, default=dict)
    at = Column(DateTime, nullable=False, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "actor_id": self.actor_id,
            "actor_role": self.actor_role, "type": self.type,
            "payload": self.payload or {},
            "at": self.at.isoformat() if self.at else None,
        }


class OnlineClassResource(Base):
    """A Knowledge Base document actually presented in a class, and its pages."""
    __tablename__ = "online_class_resources"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=True)
    title = Column(String(255), nullable=True)
    resource_type = Column(String(40), nullable=True)   # book | worksheet | exam | notes | upload
    pages_presented = Column(JSON, nullable=True, default=list)
    first_shown_at = Column(DateTime, nullable=True)
    last_shown_at = Column(DateTime, nullable=True)
    total_seconds = Column(Integer, nullable=False, default=0)

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "document_id": self.document_id,
            "title": self.title, "resource_type": self.resource_type,
            "pages_presented": self.pages_presented or [],
            "first_shown_at": self.first_shown_at.isoformat() if self.first_shown_at else None,
            "last_shown_at": self.last_shown_at.isoformat() if self.last_shown_at else None,
        }


class OnlineClassWhiteboard(Base):
    """A saved whiteboard page (spec §6). Strokes are kept as JSON so the board
    can be replayed or re-rendered; a PNG snapshot lives in MinIO."""
    __tablename__ = "online_class_whiteboards"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    page_index = Column(Integer, nullable=False, default=0)
    strokes = Column(JSON, nullable=True, default=list)
    image_object = Column(String(500), nullable=True)   # MinIO object name
    saved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    include_in_lesson_record = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "page_index": self.page_index,
            "has_image": bool(self.image_object),
            "include_in_lesson_record": bool(self.include_in_lesson_record),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OnlineClassLessonRecord(Base):
    """The official record of what was taught (spec §16, §18).

    Nothing here becomes official until a teacher confirms it. AI may propose
    `ai_suggestion`, but a proposal is not a record: displaying a page is not
    proof it was taught, and no audio is ever analysed to find out.
    """
    __tablename__ = "online_class_lesson_records"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="CASCADE"),
                        nullable=False, unique=True)
    lesson_plan_id = Column(String(36), ForeignKey("lesson_plans.id"), nullable=True)

    topics_covered = Column(JSON, nullable=True, default=list)
    pages_covered = Column(JSON, nullable=True, default=list)
    homework = Column(Text, nullable=True)
    teacher_notes = Column(Text, nullable=True)
    # AI proposal, kept separate from the confirmed fields above.
    ai_suggestion = Column(JSON, nullable=True)

    is_confirmed = Column(Boolean, nullable=False, default=False)
    confirmed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id,
            "lesson_plan_id": self.lesson_plan_id,
            "topics_covered": self.topics_covered or [],
            "pages_covered": self.pages_covered or [],
            "homework": self.homework, "teacher_notes": self.teacher_notes,
            "ai_suggestion": self.ai_suggestion,
            "is_confirmed": bool(self.is_confirmed),
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
        }


# ─── DOCUMENT CONVERSION ──────────────────────────────────────────────────────

class DocumentConversion(Base):
    """PowerPoint/Word turned into a PDF the classroom can present.

    Conversion is done once by a LibreOffice worker and the result is kept in
    object storage: a teacher who opens the same slide deck in every period of
    the week pays for it once, not five times. One row per source document.
    """
    __tablename__ = "document_conversions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"),
                         nullable=False, unique=True)
    # pending | processing | ready | failed | unsupported
    status = Column(String(20), nullable=False, default="pending")
    source_type = Column(String(20), nullable=True)
    object_name = Column(String(500), nullable=True)   # converted PDF in MinIO
    page_count = Column(Integer, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "document_id": self.document_id, "status": self.status,
            "page_count": self.page_count, "error": self.error,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── RECORDING (schema now, feature in Phase 3) ───────────────────────────────

class OnlineClassRecording(Base):
    """A standard audio/video recording of a class (spec §15).

    Recordings are media files only. They are never transcribed and never sent
    to any AI provider — there is no code path from this table to the AI layer.
    """
    __tablename__ = "online_class_recordings"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    egress_id = Column(String(80), nullable=True)
    bucket = Column(String(100), nullable=True)
    object_name = Column(String(500), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    # starting | recording | processing | ready | failed | deleted
    status = Column(String(20), nullable=False, default="starting")
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    retention_days = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    deleted_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "status": self.status,
            "duration_seconds": self.duration_seconds, "size_bytes": self.size_bytes,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


# ─── AI ENHANCEMENT LAYER (schema now, feature in Phase 4) ────────────────────

class OnlineClassAIOutput(Base):
    """Cached AI output for a class — generated once, read by everyone (§19E).

    Thirty students opening the summary must produce zero additional API calls.
    """
    __tablename__ = "online_class_ai_outputs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    # summary | revision_notes | coverage_analysis | homework_draft
    kind = Column(String(30), nullable=False)
    content = Column(JSON, nullable=True)
    # Traceable list of the approved sources used.
    sources = Column(JSON, nullable=True, default=list)
    provider = Column(String(30), nullable=True)
    model = Column(String(80), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    is_stale = Column(Boolean, nullable=False, default=False)
    generated_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        Index("ix_ocaio_session_kind", "session_id", "kind", unique=True),
    )

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "kind": self.kind,
            "content": self.content, "sources": self.sources or [],
            "model": self.model, "is_stale": bool(self.is_stale),
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }


class OnlineClassAIQuestion(Base):
    """"Ask LSS AI about this class" — a typed question and its written answer.

    Text-to-text only. The student types; the system never listens.
    """
    __tablename__ = "online_class_ai_questions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="CASCADE"),
                        nullable=True, index=True)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    sources = Column(JSON, nullable=True, default=list)
    provider = Column(String(30), nullable=True)
    model = Column(String(80), nullable=True)
    status = Column(String(20), nullable=False, default="answered")  # answered | failed | blocked
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "student_id": self.student_id,
            "question": self.question, "answer": self.answer,
            "sources": self.sources or [], "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AIUsageEvent(Base):
    """One row per AI call — the basis of admin cost monitoring (spec §19G).

    Core classroom operations never write here, because they never call an AI.
    """
    __tablename__ = "ai_usage_events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    # class_summary | coverage_analysis | revision_notes | ask_ai | teacher_assistant
    feature = Column(String(40), nullable=False, index=True)
    provider = Column(String(30), nullable=True)
    model = Column(String(80), nullable=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    user_role = Column(String(20), nullable=True)
    session_id = Column(String(36), ForeignKey("online_class_sessions.id", ondelete="SET NULL"),
                        nullable=True, index=True)
    class_name = Column(String(50), nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    est_cost_usd = Column(Float, nullable=False, default=0.0)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="ok")  # ok | failed | blocked_budget | disabled
    created_at = Column(DateTime, default=utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id, "feature": self.feature, "provider": self.provider,
            "model": self.model, "user_id": self.user_id, "user_role": self.user_role,
            "session_id": self.session_id, "class_name": self.class_name,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "est_cost_usd": round(self.est_cost_usd or 0.0, 6),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── SETTINGS ─────────────────────────────────────────────────────────────────

class OnlineClassSettings(Base):
    """Single-row admin configuration for the whole module (spec §19F).

    Stored as columns + JSON bags so an administrator can retune classroom
    policy, retention and AI budgets without a migration or a deploy.
    """
    __tablename__ = "online_class_settings"

    id = Column(String(36), primary_key=True, default=gen_uuid)

    # ── Classroom policy ──
    # Minutes the room survives while the teacher is disconnected (spec §22).
    teacher_grace_minutes = Column(Integer, nullable=False, default=5)
    join_early_minutes = Column(Integer, nullable=False, default=10)
    # Classes treated as young learners → simplified UI + stricter defaults.
    young_classes = Column(JSON, nullable=True,
                           default=lambda: ["Pre-Nursery", "Nursery", "KG", "Class 1", "Class 2"])

    # ── Attendance rules (spec §13) ──
    present_min_percent = Column(Float, nullable=False, default=75.0)
    partial_min_percent = Column(Float, nullable=False, default=25.0)
    late_after_minutes = Column(Integer, nullable=False, default=10)

    # ── Recording (spec §15; feature lands in Phase 3) ──
    recording_enabled_globally = Column(Boolean, nullable=False, default=False)
    recording_default_on = Column(Boolean, nullable=False, default=False)
    recording_retention_days = Column(Integer, nullable=False, default=30)
    max_concurrent_recordings = Column(Integer, nullable=False, default=2)

    # ── Admin observation (spec §14, §24) ──
    allow_admin_observe = Column(Boolean, nullable=False, default=True)
    # Students and teacher always see an indicator when an admin is watching.
    announce_admin_observe = Column(Boolean, nullable=False, default=True)

    # ── AI feature switches (spec §19F). Speech-to-Text is not listed because
    #    it is not implemented — it is not a switch that exists. ──
    ai_class_summary_enabled = Column(Boolean, nullable=False, default=True)
    ai_coverage_analysis_enabled = Column(Boolean, nullable=False, default=True)
    ai_revision_notes_enabled = Column(Boolean, nullable=False, default=True)
    ai_ask_enabled = Column(Boolean, nullable=False, default=True)
    ai_teacher_assistant_enabled = Column(Boolean, nullable=False, default=True)

    # ── AI budgets / routing (spec §19D, §19F) ──
    ai_daily_budget_usd = Column(Float, nullable=False, default=10.0)
    ai_monthly_budget_usd = Column(Float, nullable=False, default=150.0)
    ai_max_questions_per_student_per_day = Column(Integer, nullable=False, default=10)
    ai_max_calls_per_session = Column(Integer, nullable=False, default=50)
    # {"class_summary": "<cheap model>", "ask_ai": "<capable model>", …}
    ai_model_routing = Column(JSON, nullable=True, default=dict)

    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "teacher_grace_minutes": self.teacher_grace_minutes,
            "join_early_minutes": self.join_early_minutes,
            "young_classes": self.young_classes or [],
            "present_min_percent": self.present_min_percent,
            "partial_min_percent": self.partial_min_percent,
            "late_after_minutes": self.late_after_minutes,
            "recording_enabled_globally": bool(self.recording_enabled_globally),
            "recording_default_on": bool(self.recording_default_on),
            "recording_retention_days": self.recording_retention_days,
            "max_concurrent_recordings": self.max_concurrent_recordings,
            "allow_admin_observe": bool(self.allow_admin_observe),
            "announce_admin_observe": bool(self.announce_admin_observe),
            "ai_class_summary_enabled": bool(self.ai_class_summary_enabled),
            "ai_coverage_analysis_enabled": bool(self.ai_coverage_analysis_enabled),
            "ai_revision_notes_enabled": bool(self.ai_revision_notes_enabled),
            "ai_ask_enabled": bool(self.ai_ask_enabled),
            "ai_teacher_assistant_enabled": bool(self.ai_teacher_assistant_enabled),
            "ai_daily_budget_usd": self.ai_daily_budget_usd,
            "ai_monthly_budget_usd": self.ai_monthly_budget_usd,
            "ai_max_questions_per_student_per_day": self.ai_max_questions_per_student_per_day,
            "ai_max_calls_per_session": self.ai_max_calls_per_session,
            "ai_model_routing": self.ai_model_routing or {},
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

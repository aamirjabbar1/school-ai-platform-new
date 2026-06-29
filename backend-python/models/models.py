import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, Float, Boolean, DateTime, Date, ForeignKey, JSON
from sqlalchemy.orm import relationship
from config.database import Base


def gen_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ─── USER ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(100), nullable=False)
    login_id = Column(String(50), nullable=False, unique=True)
    email = Column(String(150), nullable=True, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="student")
    class_name = Column(String(50), nullable=True)
    # Student's section within their class (e.g. "A"). Optional.
    section = Column(String(50), nullable=True)
    # Father's name (collected for students, e.g. via bulk import). Optional.
    father_name = Column(String(150), nullable=True)
    subjects = Column(JSON, nullable=True, default=list)
    # Classes assigned to a teacher (list of class names). Unused for other roles.
    assigned_classes = Column(JSON, nullable=True, default=list)
    # Class+section combinations assigned to a teacher (e.g. "Grade 5 - A").
    assigned_sections = Column(JSON, nullable=True, default=list)
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False, nullable=False)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    created_assignments = relationship("Assignment", back_populates="teacher", foreign_keys="Assignment.teacher_id")
    submissions = relationship("Submission", back_populates="student", foreign_keys="Submission.student_id")
    documents = relationship("Document", back_populates="uploader", foreign_keys="Document.uploaded_by")
    question_papers = relationship("QuestionPaper", back_populates="teacher", foreign_keys="QuestionPaper.teacher_id")
    lesson_plans = relationship("LessonPlan", back_populates="teacher", foreign_keys="LessonPlan.teacher_id")
    chat_history = relationship("ChatHistory", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self, exclude_password=True):
        d = {
            "id": self.id, "name": self.name, "login_id": self.login_id,
            "email": self.email, "role": self.role, "class_name": self.class_name,
            "section": self.section, "father_name": self.father_name,
            "subjects": self.subjects or [], "assigned_classes": self.assigned_classes or [],
            "assigned_sections": self.assigned_sections or [],
            "is_active": self.is_active,
            "must_change_password": self.must_change_password,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if not exclude_password:
            d["password_hash"] = self.password_hash
        return d


# ─── CURRICULUM MAPPING ───────────────────────────────────────────────────────
#
# Pre-Board structure: a student's enrolled class can differ from the curriculum
# they actually study. e.g. Grade 8 ("Pre-9th") students use the Grade 9
# curriculum, but all Grade 9 knowledge-base content is stored under Grade 9.
# A mapping row says "when a student is in `source_class`, search the knowledge
# base under `target_class` instead". One row per source class.

class CurriculumMapping(Base):
    __tablename__ = "curriculum_mappings"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    # The student's enrolled / assigned class (e.g. "Class 8").
    source_class = Column(String(50), nullable=False, unique=True)
    # The knowledge-base class to search instead (e.g. "Class 9").
    target_class = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "source_class": self.source_class,
            "target_class": self.target_class,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── STUDENT IMPORT BATCH ─────────────────────────────────────────────────────
#
# Tracks a single bulk student import (Excel upload). Processing runs in a Celery
# task; the row holds the live status, the summary counts, the detailed error log
# and the ids of accounts created by this batch (so the import can be rolled back
# without touching pre-existing or updated records).

class StudentImportBatch(Base):
    __tablename__ = "student_import_batches"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    filename = Column(String(255), nullable=True)
    # pending | processing | completed | failed | rolled_back
    status = Column(String(20), nullable=False, default="pending")
    # skip | update | create_new  — how to treat existing registration numbers
    duplicate_mode = Column(String(20), nullable=False, default="skip")
    # registration | custom | random  — how default passwords are generated
    password_mode = Column(String(20), nullable=False, default="registration")
    # create | strict  — auto-create unknown sections, or skip them with an error
    section_mode = Column(String(20), nullable=False, default="create")

    total = Column(Integer, default=0)
    created_count = Column(Integer, default=0)
    updated_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)

    # list of {row, reg_no, name, reason}
    error_log = Column(JSON, nullable=True, default=list)
    # ids of users CREATED by this batch (drives rollback)
    created_user_ids = Column(JSON, nullable=True, default=list)

    has_credentials = Column(Boolean, default=False)
    is_rolled_back = Column(Boolean, default=False, nullable=False)
    # fatal task-level error message (parsing failure etc.)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    finished_at = Column(DateTime, nullable=True)

    def to_dict(self, include_details: bool = False):
        d = {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "duplicate_mode": self.duplicate_mode,
            "password_mode": self.password_mode,
            "section_mode": self.section_mode,
            "total": self.total or 0,
            "created_count": self.created_count or 0,
            "updated_count": self.updated_count or 0,
            "skipped_count": self.skipped_count or 0,
            "failed_count": self.failed_count or 0,
            "has_credentials": self.has_credentials,
            "is_rolled_back": self.is_rolled_back,
            "error_message": self.error_message,
            "created_count_remaining": len(self.created_user_ids or []),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
        if include_details:
            d["error_log"] = self.error_log or []
        return d


# ─── ASSIGNMENT ───────────────────────────────────────────────────────────────

class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    subject = Column(String(100), nullable=False)
    class_name = Column(String(50), nullable=False)
    # Target section within the class (e.g. "A"). Null = whole class.
    section = Column(String(50), nullable=True)
    teacher_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    due_date = Column(Date, nullable=True)
    assignment_type = Column(String(20), default="homework")
    max_marks = Column(Integer, default=100)
    instructions = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    teacher = relationship("User", back_populates="created_assignments", foreign_keys=[teacher_id])
    submissions = relationship("Submission", back_populates="assignment")

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "description": self.description,
            "subject": self.subject, "class_name": self.class_name, "section": self.section,
            "teacher_id": self.teacher_id, "due_date": str(self.due_date) if self.due_date else None,
            "assignment_type": self.assignment_type, "max_marks": self.max_marks,
            "instructions": self.instructions, "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── SUBMISSION ───────────────────────────────────────────────────────────────

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    assignment_id = Column(String(36), ForeignKey("assignments.id"), nullable=False)
    student_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=True)
    file_name = Column(String(255), nullable=True)
    status = Column(String(20), default="draft")
    grade = Column(Float, nullable=True)
    feedback = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    ai_generated = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    assignment = relationship("Assignment", back_populates="submissions")
    student = relationship("User", back_populates="submissions", foreign_keys=[student_id])

    def to_dict(self):
        return {
            "id": self.id, "assignment_id": self.assignment_id,
            "student_id": self.student_id, "content": self.content,
            "file_path": self.file_path, "file_name": self.file_name,
            "status": self.status, "grade": self.grade, "feedback": self.feedback,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "ai_generated": self.ai_generated,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── DOCUMENT ─────────────────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    title = Column(String(255), nullable=False)
    subject = Column(String(100), nullable=False)
    class_level = Column(String(50), nullable=False)
    # document_type: "book" | "exam" | "assignment" | "notes" | "worksheet"
    document_type = Column(String(50), nullable=False, default="book")
    # language: "English" | "Urdu" | "Bilingual"
    language = Column(String(20), nullable=False, default="English")
    # academic_year e.g. "2024-2025" (for question papers this holds the exam Year)
    academic_year = Column(String(20), nullable=True)
    # term: "Term 1" | "Term 2" | "Term 3" | "Annual" | None
    term = Column(String(30), nullable=True)
    # paper_type (question papers only): past_paper | test | midterm | final | mcqs
    paper_type = Column(String(40), nullable=True)
    # chapter / topic the paper or material covers (free text)
    chapter = Column(String(300), nullable=True)
    description = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size = Column(Integer, nullable=True)
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    is_ingested = Column(Boolean, default=False)
    total_chunks = Column(Integer, default=0)
    ingestion_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    uploader = relationship("User", back_populates="documents", foreign_keys=[uploaded_by])
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    def to_dict(self, exclude_path=True):
        d = {
            "id": self.id, "title": self.title, "subject": self.subject,
            "class_level": self.class_level, "document_type": self.document_type,
            "language": self.language, "academic_year": self.academic_year,
            "term": self.term, "paper_type": self.paper_type, "chapter": self.chapter,
            "description": self.description,
            "file_name": self.file_name, "file_type": self.file_type,
            "file_size": self.file_size, "uploaded_by": self.uploaded_by,
            "is_ingested": self.is_ingested, "total_chunks": self.total_chunks,
            "ingestion_error": self.ingestion_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if not exclude_path:
            d["file_path"] = self.file_path
        return d


# ─── DOCUMENT CHUNK ───────────────────────────────────────────────────────────

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    word_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    document = relationship("Document", back_populates="chunks")


# ─── QUESTION PAPER ───────────────────────────────────────────────────────────

class QuestionPaper(Base):
    __tablename__ = "question_papers"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    title = Column(String(255), nullable=False)
    subject = Column(String(100), nullable=False)
    class_name = Column(String(50), nullable=False)
    # Target section within the class (e.g. "A"). Null = whole class.
    section = Column(String(50), nullable=True)
    teacher_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    paper_type = Column(String(20), default="class_test")
    questions = Column(JSON, nullable=False, default=list)
    answer_key = Column(JSON, nullable=False, default=list)
    total_marks = Column(Integer, default=100)
    duration_minutes = Column(Integer, default=60)
    instructions = Column(Text, nullable=True)
    is_published = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    teacher = relationship("User", back_populates="question_papers", foreign_keys=[teacher_id])

    def to_dict(self, hide_answers=False):
        d = {
            "id": self.id, "title": self.title, "subject": self.subject,
            "class_name": self.class_name, "section": self.section,
            "teacher_id": self.teacher_id,
            "paper_type": self.paper_type, "questions": self.questions,
            "total_marks": self.total_marks, "duration_minutes": self.duration_minutes,
            "instructions": self.instructions, "is_published": self.is_published,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if not hide_answers:
            d["answer_key"] = self.answer_key
        return d


# ─── LESSON PLAN ──────────────────────────────────────────────────────────────

class LessonPlan(Base):
    __tablename__ = "lesson_plans"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    title = Column(String(255), nullable=False)
    subject = Column(String(100), nullable=False)
    class_name = Column(String(50), nullable=False)
    # Target section within the class (e.g. "A"). Null = whole class.
    section = Column(String(50), nullable=True)
    teacher_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    # plan_type: weekly | monthly | unit | chapter | term | annual | revision | exam_prep | practical
    plan_type = Column(String(30), nullable=False, default="weekly")
    board = Column(String(100), nullable=True)            # Federal Board, Cambridge, …
    book_name = Column(String(255), nullable=True)
    academic_session = Column(String(40), nullable=True)  # e.g. "2025-2026"
    start_date = Column(String(40), nullable=True)        # free-text; plan rows carry their own dates
    end_date = Column(String(40), nullable=True)
    # The structured generated plan: {"lessons": [...], "summary": {...}}.
    plan_data = Column(JSON, nullable=False, default=dict)
    # The generation inputs, kept so a plan can be duplicated / regenerated.
    inputs = Column(JSON, nullable=True, default=dict)
    is_published = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    teacher = relationship("User", back_populates="lesson_plans", foreign_keys=[teacher_id])

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "subject": self.subject,
            "class_name": self.class_name, "section": self.section,
            "teacher_id": self.teacher_id, "plan_type": self.plan_type,
            "board": self.board, "book_name": self.book_name,
            "academic_session": self.academic_session,
            "start_date": self.start_date, "end_date": self.end_date,
            "plan_data": self.plan_data or {}, "inputs": self.inputs or {},
            "is_published": self.is_published,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── CHAT HISTORY ─────────────────────────────────────────────────────────────

class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(100), nullable=False)
    role = Column(String(10), nullable=False)
    content = Column(Text, nullable=False)
    subject_context = Column(String(100), nullable=True)
    sources_used = Column(JSON, nullable=True, default=list)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="chat_history")

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "session_id": self.session_id,
            "role": self.role, "content": self.content,
            "subject_context": self.subject_context, "sources_used": self.sources_used,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── NOTIFICATION ─────────────────────────────────────────────────────────────

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(20), default="system")
    is_read = Column(Boolean, default=False)
    action_url = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="notifications")

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "title": self.title,
            "message": self.message, "type": self.type, "is_read": self.is_read,
            "action_url": self.action_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

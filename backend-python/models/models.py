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
    subjects = Column(JSON, nullable=True, default=list)
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    created_assignments = relationship("Assignment", back_populates="teacher", foreign_keys="Assignment.teacher_id")
    submissions = relationship("Submission", back_populates="student", foreign_keys="Submission.student_id")
    documents = relationship("Document", back_populates="uploader", foreign_keys="Document.uploaded_by")
    question_papers = relationship("QuestionPaper", back_populates="teacher", foreign_keys="QuestionPaper.teacher_id")
    chat_history = relationship("ChatHistory", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")

    def to_dict(self, exclude_password=True):
        d = {
            "id": self.id, "name": self.name, "login_id": self.login_id,
            "email": self.email, "role": self.role, "class_name": self.class_name,
            "subjects": self.subjects or [], "is_active": self.is_active,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if not exclude_password:
            d["password_hash"] = self.password_hash
        return d


# ─── ASSIGNMENT ───────────────────────────────────────────────────────────────

class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    subject = Column(String(100), nullable=False)
    class_name = Column(String(50), nullable=False)
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
            "subject": self.subject, "class_name": self.class_name,
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
    # academic_year e.g. "2024-2025"
    academic_year = Column(String(20), nullable=True)
    # term: "Term 1" | "Term 2" | "Term 3" | "Annual" | None
    term = Column(String(30), nullable=True)
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
            "term": self.term, "description": self.description,
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
            "class_name": self.class_name, "teacher_id": self.teacher_id,
            "paper_type": self.paper_type, "questions": self.questions,
            "total_marks": self.total_marks, "duration_minutes": self.duration_minutes,
            "instructions": self.instructions, "is_published": self.is_published,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if not hide_answers:
            d["answer_key"] = self.answer_key
        return d


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

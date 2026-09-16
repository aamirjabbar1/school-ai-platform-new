"""
Classroom access checks, shared by every online-class route.

One place decides who may look at a classroom and who may control it, because
the alternative — each route module re-deriving the rule — is how a student
ends up in another section's lesson.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import User
from models.online_classes import OnlineClassSession
from services import class_matching


async def get_session(db: AsyncSession, session_id: str) -> OnlineClassSession:
    result = await db.execute(
        select(OnlineClassSession).where(OnlineClassSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Class not found")
    return session


def is_host(session: OnlineClassSession, user: User) -> bool:
    return user.role == "admin" or session.teacher_id == user.id


def require_host(session: OnlineClassSession, user: User) -> None:
    """Only the teacher running the class (or an administrator) may change it."""
    if not is_host(session, user):
        raise HTTPException(status_code=403, detail="This is not your class.")


def require_member(session: OnlineClassSession, user: User) -> str:
    """Anyone entitled to see this classroom. Returns their classroom role."""
    if user.role == "admin":
        return "admin"
    if session.teacher_id == user.id:
        return "teacher"

    allowed, reason = class_matching.student_may_join(user, session)
    if not allowed:
        raise HTTPException(status_code=403, detail=reason)
    return "student"

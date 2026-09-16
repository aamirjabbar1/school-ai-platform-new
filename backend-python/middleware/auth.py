from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from config.settings import JWT_SECRET, JWT_EXPIRES_DAYS
from models.models import User

security = HTTPBearer()


def create_token(user_id: str) -> str:
    payload = {
        "id": user_id,
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRES_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        user_id = payload.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive account")

    return user


# ─── Scoped, short-lived tokens ───────────────────────────────────────────────
#
# Some resources are fetched by the browser itself rather than by our code —
# a PDF viewer loading a textbook, a video element playing a recording — and
# those requests cannot carry an Authorization header. They get a separate
# token instead of the session token: short-lived, tied to one classroom and
# one purpose, so a URL that leaks into a log or a chat message is worth almost
# nothing and expires within minutes.

def create_scoped_token(
    user_id: str,
    *,
    scope: str,
    session_id: str,
    minutes: int = 15,
) -> str:
    payload = {
        "id": user_id,
        "scope": scope,
        "sid": session_id,
        "exp": datetime.utcnow() + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_scoped_token(token: str, *, scope: str, session_id: str) -> str:
    """Return the user id carried by a valid scoped token, else raise 401."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired link")

    if payload.get("scope") != scope or payload.get("sid") != session_id:
        raise HTTPException(status_code=403, detail="This link is not valid here")

    user_id = payload.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid link")
    return user_id


async def user_from_request(request: Request, db: AsyncSession, *, session_id: str) -> User:
    """Authenticate a browser-issued media request.

    Prefers the normal bearer token; falls back to a scoped `?rt=` token for
    requests a PDF viewer or video element makes on its own.
    """
    token: str | None = None
    scoped = False

    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1]
    else:
        token = request.query_params.get("rt")
        scoped = True

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if scoped:
        user_id = decode_scoped_token(token, scope="resource", session_id=session_id)
    else:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user_id = payload.get("id")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive account")
    return user


def require_roles(*roles: str):
    async def role_checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role: {' or '.join(roles)}",
            )
        return user
    return role_checker

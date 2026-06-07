from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from utils.password import hash_password, verify_password
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import create_token, get_current_user
from models.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login_id: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForceChangePasswordRequest(BaseModel):
    new_password: str


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.login_id == body.login_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials or account is inactive")

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user.last_login = datetime.utcnow()
    await db.commit()

    token = create_token(user.id)
    return {
        "token": token,
        "user": {
            "id": user.id, "name": user.name, "login_id": user.login_id,
            "email": user.email, "role": user.role, "class_name": user.class_name,
            "subjects": user.subjects or [],
            "must_change_password": user.must_change_password,
        },
    }


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id, "name": user.name, "login_id": user.login_id,
        "email": user.email, "role": user.role, "class_name": user.class_name,
        "subjects": user.subjects or [], "last_login": user.last_login,
        "must_change_password": user.must_change_password,
    }


@router.put("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await db.commit()
    return {"message": "Password changed successfully"}


@router.put("/force-change-password")
async def force_change_password(
    body: ForceChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Used on first login when must_change_password is True. No old password required."""
    if not user.must_change_password:
        raise HTTPException(status_code=403, detail="Password change not required")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    await db.commit()
    return {"message": "Password updated successfully"}

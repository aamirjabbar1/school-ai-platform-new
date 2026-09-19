"""
Master student list reconciliation (ERP).

Upload the school's updated list, see exactly what would happen, then apply it.
Two endpoints, and the preview is the only sane way to reach the apply — a
migration that writes 755 children's records before anyone has looked is not a
migration, it is an accident with a progress bar.

Nothing here can change a login, a password or an account. The importer fills
blanks on the ERP profile and admits children who are genuinely new.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from models.models import User
from routes.erp import erp_available
from services.erp import student_reconcile
from services.erp.permissions import require_permission
from services.erp.student_reconcile import ReconcileError

logger = logging.getLogger("agent")

router = APIRouter(prefix="/erp/students/reconcile", tags=["erp-reconcile"])

MAX_BYTES = 10 * 1024 * 1024


async def _read(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="Please upload an Excel (.xlsx) file.")
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="That file is larger than 10 MB.")
    if not content:
        raise HTTPException(status_code=400, detail="That file is empty.")
    return content


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("student.edit")),
    db: AsyncSession = Depends(get_db),
):
    """What the file would do. Writes nothing at all."""
    content = await _read(file)
    try:
        return await student_reconcile.preview(db, content)
    except ReconcileError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/apply")
async def apply(
    file: UploadFile = File(...),
    create_new: bool = Form(True),
    include_name_matches: bool = Form(False),
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("student.edit", "admission.create")),
    db: AsyncSession = Depends(get_db),
):
    """Apply the file.

    `include_name_matches` stays off unless somebody has read the review list
    and decided those rows are the children they look like.
    """
    content = await _read(file)
    try:
        return await student_reconcile.apply(
            db, content, actor=user,
            create_new=create_new,
            include_name_matches=include_name_matches,
        )
    except ReconcileError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        await db.rollback()
        raise

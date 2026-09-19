"""
Management API (ERP phase 8).

Three endpoints: the dashboard, the exceptions queue, and the assistant. All
three are permission-shaped rather than role-shaped — the Preschool Head's
dashboard is a shorter dashboard, not the Owner's with holes in it.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user
from middleware.rate_limit import limiter
from models.models import User
from routes.erp import erp_available
from services.erp import assistant as assistant_service, insights
from services.erp.permissions import permissions_for

logger = logging.getLogger("agent")

router = APIRouter(prefix="/erp/management", tags=["erp-management"])


@router.get("/dashboard")
async def dashboard(
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    held = await permissions_for(db, user)
    if not held:
        raise HTTPException(status_code=403, detail="You do not have a management view.")
    return await insights.management_dashboard(db, held)


@router.get("/exceptions")
async def exceptions(
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What needs a human today. Empty on a good day, which is the point."""
    held = await permissions_for(db, user)
    return {"items": await insights.exceptions(db, held)}


class AskRequest(BaseModel):
    question: str


@router.post("/ask")
async def ask(
    body: AskRequest,
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ask the school a question in plain words.

    The model picks which prepared question to run; it cannot compose a query,
    and it is only offered the reports this user may already open.
    """
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question first.")
    if len(question) > 500:
        raise HTTPException(status_code=400, detail="That question is too long.")

    held = await permissions_for(db, user)
    result = await assistant_service.ask(db, question=question, user=user, held=held)

    # Recorded like every other AI call, so the cost of this feature is visible
    # in the same place as the rest.
    try:
        from models.online_classes import AIUsageEvent
        from services.lss_ai_service import estimate_cost
        from config.settings import AI_MODEL

        db.add(AIUsageEvent(
            feature="erp_assistant",
            provider="anthropic",
            model=AI_MODEL,
            user_id=user.id,
            user_role=user.role,
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            est_cost_usd=estimate_cost(
                AI_MODEL, result.get("input_tokens", 0), result.get("output_tokens", 0),
            ),
            latency_ms=result.get("latency_ms"),
            status="ok",
        ))
        await db.commit()
    except Exception as exc:                       # noqa: BLE001
        # Usage accounting must never cost somebody their answer.
        logger.warning("Assistant usage not recorded: %s", exc)

    return {"answer": result["answer"], "used": result.get("used", [])}


@router.get("/suggestions")
async def suggestions(
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Questions this user can actually ask, shown as prompts.

    A blank box invites nothing. These are drawn from the tools they hold, so
    nobody is offered a question that would come back empty-handed.
    """
    held = await permissions_for(db, user)
    available = set(insights.tools_for(held))

    catalogue = [
        ("attendance_today", "How many students are absent today?"),
        ("fee_position", "How much fee was collected today?"),
        ("defaulter_list", "Show me the fee defaulters."),
        ("students_today", "How many students are in each class?"),
        ("payroll_position", "What is this month's payroll?"),
        ("exam_progress", "Which exams are still missing marks?"),
        ("family_summary", "How many families have more than one child here?"),
        ("staff_summary", "How many staff records are incomplete?"),
    ]
    return {"suggestions": [text for tool, text in catalogue if tool in available]}

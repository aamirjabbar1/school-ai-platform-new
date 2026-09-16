"""
LSS AI Service — the one place Online Classes talks to a language model.

Everything AI in this module obeys four rules from the specification:

  * **Text-to-text only.** The inputs are written, structured, approved school
    records. Classroom audio is never read, transcribed or sent anywhere — no
    speech service exists in this system, and nothing here could call one.
  * **Task-appropriate models.** A summary assembled from structured data runs
    on the low-cost model; a student's difficult question gets the capable one.
    Routing is configuration, not code.
  * **Budgets are enforced before the call, not regretted after it.** Daily and
    monthly caps, per-student question limits and per-class call limits are
    checked first; over budget means no call.
  * **Failure is survivable.** If the provider is down, the key is exhausted or
    an administrator switched the feature off, callers get `AIUnavailable` and
    show the classroom without AI. The lesson never depends on it.

Swapping providers means changing `_generate_anthropic`; nothing above it knows
which company answered.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import User, utcnow
from models.online_classes import AIUsageEvent, OnlineClassSettings

logger = logging.getLogger("agent")


class AIUnavailable(Exception):
    """AI could not run. Carries a reason a teacher or student can read."""

    def __init__(self, message: str, *, status: str = "failed"):
        super().__init__(message)
        self.status = status


# ─── Features ─────────────────────────────────────────────────────────────────

CLASS_SUMMARY = "class_summary"
COVERAGE_ANALYSIS = "coverage_analysis"
REVISION_NOTES = "revision_notes"
ASK_AI = "ask_ai"
TEACHER_ASSISTANT = "teacher_assistant"
HOMEWORK_DRAFT = "homework_draft"

# Which admin switch governs each feature.
_FEATURE_FLAGS = {
    CLASS_SUMMARY: "ai_class_summary_enabled",
    COVERAGE_ANALYSIS: "ai_coverage_analysis_enabled",
    REVISION_NOTES: "ai_revision_notes_enabled",
    ASK_AI: "ai_ask_enabled",
    TEACHER_ASSISTANT: "ai_teacher_assistant_enabled",
    HOMEWORK_DRAFT: "ai_teacher_assistant_enabled",
}

# Default routing. Organising structured data is cheap work; explaining
# photosynthesis to a confused child is not, so they do not get the same model.
FAST = "fast"
CAPABLE = "capable"
_FEATURE_TIER = {
    CLASS_SUMMARY: FAST,
    COVERAGE_ANALYSIS: FAST,
    REVISION_NOTES: FAST,
    HOMEWORK_DRAFT: FAST,
    ASK_AI: CAPABLE,
    TEACHER_ASSISTANT: CAPABLE,
}

# USD per million tokens (input, output). Used for budget arithmetic and the
# admin cost view; an unknown model falls back to the capable-tier rate so an
# unlisted model is never treated as free.
_PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
_DEFAULT_PRICING = (5.0, 25.0)


def model_for(settings: OnlineClassSettings, feature: str) -> str:
    """Which model answers this feature, honouring any admin override."""
    from config.settings import AI_MODEL, AI_MODEL_FAST

    routing = settings.ai_model_routing or {}
    if routing.get(feature):
        return routing[feature]

    tier = _FEATURE_TIER.get(feature, CAPABLE)
    if routing.get(tier):
        return routing[tier]
    return AI_MODEL_FAST if tier == FAST else AI_MODEL


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = _PRICING.get(model, _DEFAULT_PRICING)
    return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out


# ─── Guards ───────────────────────────────────────────────────────────────────

async def ensure_available(
    db: AsyncSession,
    settings: OnlineClassSettings,
    feature: str,
    *,
    user: User | None = None,
    session_id: str | None = None,
) -> None:
    """Raise `AIUnavailable` unless this feature may run right now.

    Checked before the call so a school cannot be surprised by a bill: an
    exhausted budget produces a polite message, not an invoice.
    """
    from config.settings import ANTHROPIC_API_KEY

    flag = _FEATURE_FLAGS.get(feature)
    if flag and not getattr(settings, flag, True):
        raise AIUnavailable("This AI feature is switched off by the school.", status="disabled")

    if not ANTHROPIC_API_KEY:
        raise AIUnavailable("AI is not configured on this server.", status="disabled")

    now = utcnow()
    day_start = datetime(now.year, now.month, now.day)
    month_start = datetime(now.year, now.month, 1)

    daily = await _spend_since(db, day_start)
    if daily >= (settings.ai_daily_budget_usd or 0):
        raise AIUnavailable(
            "Today's AI budget has been used up. The class itself is unaffected.",
            status="blocked_budget",
        )

    monthly = await _spend_since(db, month_start)
    if monthly >= (settings.ai_monthly_budget_usd or 0):
        raise AIUnavailable(
            "This month's AI budget has been used up. The class itself is unaffected.",
            status="blocked_budget",
        )

    if feature == ASK_AI and user is not None:
        asked = (await db.execute(
            select(func.count()).select_from(AIUsageEvent).where(
                AIUsageEvent.feature == ASK_AI,
                AIUsageEvent.user_id == user.id,
                AIUsageEvent.created_at >= day_start,
                AIUsageEvent.status == "ok",
            )
        )).scalar() or 0
        cap = settings.ai_max_questions_per_student_per_day or 10
        if asked >= cap:
            raise AIUnavailable(
                f"You have asked LSS AI {cap} questions today. Please try again tomorrow.",
                status="blocked_budget",
            )

    if session_id:
        used = (await db.execute(
            select(func.count()).select_from(AIUsageEvent).where(
                AIUsageEvent.session_id == session_id,
                AIUsageEvent.status == "ok",
            )
        )).scalar() or 0
        if used >= (settings.ai_max_calls_per_session or 50):
            raise AIUnavailable(
                "This class has reached its AI usage limit.", status="blocked_budget"
            )


async def _spend_since(db: AsyncSession, since: datetime) -> float:
    total = (await db.execute(
        select(func.sum(AIUsageEvent.est_cost_usd)).where(AIUsageEvent.created_at >= since)
    )).scalar()
    return float(total or 0.0)


# ─── Generation ───────────────────────────────────────────────────────────────

async def generate(
    db: AsyncSession,
    *,
    feature: str,
    settings: OnlineClassSettings,
    system: str,
    prompt: str,
    schema: dict | None = None,
    max_tokens: int = 2000,
    user: User | None = None,
    session_id: str | None = None,
    class_name: str | None = None,
) -> dict[str, Any]:
    """Run one AI request and record what it cost.

    Returns `{"text": ..., "data": ..., "model": ..., "usage": {...}}`. When a
    `schema` is given the answer comes back as validated JSON via tool use —
    the same structured-output pattern the question-paper generator already
    uses, so both halves of LSS Bot parse model output the same way.
    """
    await ensure_available(db, settings, feature, user=user, session_id=session_id)

    model = model_for(settings, feature)
    started = time.monotonic()

    try:
        result = await _generate_anthropic(
            model=model, system=system, prompt=prompt, schema=schema, max_tokens=max_tokens
        )
    except Exception as exc:
        logger.warning("[LSS AI] %s failed on %s: %s", feature, model, exc)
        await _record_usage(
            db, feature=feature, model=model, user=user, session_id=session_id,
            class_name=class_name, input_tokens=0, output_tokens=0,
            latency_ms=int((time.monotonic() - started) * 1000), status="failed",
        )
        raise AIUnavailable(
            "LSS AI could not answer just now. Please try again in a moment."
        ) from exc

    await _record_usage(
        db, feature=feature, model=model, user=user, session_id=session_id,
        class_name=class_name,
        input_tokens=result["usage"]["input_tokens"],
        output_tokens=result["usage"]["output_tokens"],
        latency_ms=int((time.monotonic() - started) * 1000),
        status="ok",
    )
    return result


async def _generate_anthropic(
    *, model: str, system: str, prompt: str, schema: dict | None, max_tokens: int
) -> dict[str, Any]:
    """The provider-specific half. Replacing this swaps the AI vendor."""
    from services.ai_service import get_async_client

    client = get_async_client()
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }

    if schema:
        kwargs["tools"] = [{
            "name": "emit",
            "description": "Return the requested result.",
            "input_schema": schema,
        }]
        kwargs["tool_choice"] = {"type": "tool", "name": "emit"}

    response = await client.messages.create(**kwargs)

    text = ""
    data = None
    for block in response.content:
        if block.type == "text":
            text += block.text
        elif block.type == "tool_use" and block.name == "emit":
            data = block.input

    if schema and data is None:
        # The model answered in prose despite being asked for a tool call;
        # salvage JSON if it is there rather than failing the whole feature.
        data = _loads_or_none(text)

    return {
        "text": text.strip(),
        "data": data,
        "model": model,
        "usage": {
            "input_tokens": getattr(response.usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(response.usage, "output_tokens", 0) or 0,
        },
    }


def _loads_or_none(text: str):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


async def _record_usage(
    db: AsyncSession,
    *,
    feature: str,
    model: str,
    user: User | None,
    session_id: str | None,
    class_name: str | None,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    status: str,
) -> None:
    """Write the usage ledger row. Never raises — accounting must not break a
    feature, and a missing row is cheaper than a failed lesson."""
    try:
        db.add(AIUsageEvent(
            feature=feature,
            provider="anthropic",
            model=model,
            user_id=user.id if user else None,
            user_role=user.role if user else None,
            session_id=session_id,
            class_name=class_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            est_cost_usd=estimate_cost(model, input_tokens, output_tokens),
            latency_ms=latency_ms,
            status=status,
        ))
        await db.commit()
    except Exception as exc:  # pragma: no cover - accounting is best effort
        logger.warning("[LSS AI] usage ledger write failed: %s", exc)


# ─── Reporting (spec §19G) ────────────────────────────────────────────────────

async def usage_summary(db: AsyncSession, *, days: int = 30) -> dict:
    """What AI has cost, by day, feature, class and person."""
    since = utcnow() - timedelta(days=max(1, min(days, 365)))
    now = utcnow()
    day_start = datetime(now.year, now.month, now.day)
    month_start = datetime(now.year, now.month, 1)

    by_feature = (await db.execute(
        select(
            AIUsageEvent.feature,
            func.count(AIUsageEvent.id),
            func.sum(AIUsageEvent.input_tokens),
            func.sum(AIUsageEvent.output_tokens),
            func.sum(AIUsageEvent.est_cost_usd),
        )
        .where(AIUsageEvent.created_at >= since)
        .group_by(AIUsageEvent.feature)
    )).all()

    by_class = (await db.execute(
        select(AIUsageEvent.class_name, func.count(AIUsageEvent.id), func.sum(AIUsageEvent.est_cost_usd))
        .where(AIUsageEvent.created_at >= since, AIUsageEvent.class_name.is_not(None))
        .group_by(AIUsageEvent.class_name)
        .order_by(func.sum(AIUsageEvent.est_cost_usd).desc())
        .limit(20)
    )).all()

    by_model = (await db.execute(
        select(AIUsageEvent.model, func.count(AIUsageEvent.id), func.sum(AIUsageEvent.est_cost_usd))
        .where(AIUsageEvent.created_at >= since)
        .group_by(AIUsageEvent.model)
    )).all()

    failures = (await db.execute(
        select(AIUsageEvent.status, func.count(AIUsageEvent.id))
        .where(AIUsageEvent.created_at >= since, AIUsageEvent.status != "ok")
        .group_by(AIUsageEvent.status)
    )).all()

    return {
        "days": days,
        "today_usd": round(await _spend_since(db, day_start), 4),
        "month_usd": round(await _spend_since(db, month_start), 4),
        "period_usd": round(await _spend_since(db, since), 4),
        "by_feature": [
            {
                "feature": feature, "requests": count,
                "input_tokens": int(tin or 0), "output_tokens": int(tout or 0),
                "cost_usd": round(float(cost or 0), 4),
            }
            for feature, count, tin, tout, cost in by_feature
        ],
        "by_class": [
            {"class_name": name, "requests": count, "cost_usd": round(float(cost or 0), 4)}
            for name, count, cost in by_class
        ],
        "by_model": [
            {"model": model, "requests": count, "cost_usd": round(float(cost or 0), 4)}
            for model, count, cost in by_model
        ],
        "non_ok": [{"status": status, "count": count} for status, count in failures],
    }

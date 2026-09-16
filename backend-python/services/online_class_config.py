"""
Admin configuration for the Online Classes module.

A single settings row holds classroom policy, attendance rules, recording
retention and AI budgets, so a school can retune them without a deploy. The row
is seeded by the migration; this module recreates it if it is ever missing so a
classroom can never fail to start for want of a configuration row.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.online_classes import OnlineClassSettings

logger = logging.getLogger("agent")

SETTINGS_ID = "00000000-0000-0000-0000-00000000c1a5"


async def get_settings(db: AsyncSession) -> OnlineClassSettings:
    result = await db.execute(select(OnlineClassSettings).limit(1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings

    logger.info("[ONLINE CLASSES] settings row missing — seeding defaults")
    settings = OnlineClassSettings(
        id=SETTINGS_ID,
        young_classes=["Pre-Nursery", "Nursery", "KG", "Class 1", "Class 2"],
        ai_model_routing={},
    )
    db.add(settings)
    await db.commit()
    await db.refresh(settings)
    return settings

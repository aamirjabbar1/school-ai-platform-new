"""
Curriculum mapping resolver.

Bridges a student's enrolled class to the knowledge-base class that should
actually be searched. Used by the chat pipeline so e.g. a "Class 8" (Pre-9th)
student automatically receives answers from "Class 9" content without having to
ask for it explicitly.

The mapping table is small (one row per source class), so the active mappings
are fetched and matched in Python. Matching is tolerant: a stored class name may
carry a section suffix ("Class 8 - Boys"), so we compare on the class prefix
(text before " - ") case-insensitively.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import CurriculumMapping

logger = logging.getLogger("agent")


def _normalize(class_name: str | None) -> str:
    """Lowercased class prefix with any ' - <section>' suffix removed."""
    if not class_name:
        return ""
    return class_name.split(" - ")[0].strip().lower()


async def resolve_curriculum_class(
    source_class: str | None,
    db: AsyncSession,
) -> str | None:
    """Return the knowledge-base class to search for a given student class.

    If an active mapping exists for `source_class`, returns its `target_class`;
    otherwise returns `source_class` unchanged. Never raises — on any error it
    falls back to the original class so chat retrieval is never broken by the
    mapping layer.
    """
    if not source_class:
        return source_class

    norm = _normalize(source_class)
    if not norm:
        return source_class

    try:
        result = await db.execute(
            select(CurriculumMapping).where(CurriculumMapping.is_active == True)  # noqa: E712
        )
        for mapping in result.scalars().all():
            if _normalize(mapping.source_class) == norm:
                if mapping.target_class and mapping.target_class != source_class:
                    logger.info(
                        "[CURRICULUM] mapping applied: %r → %r",
                        source_class, mapping.target_class,
                    )
                return mapping.target_class or source_class
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[CURRICULUM] resolve failed (using original class): %s", exc)

    return source_class

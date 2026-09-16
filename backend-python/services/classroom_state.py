"""
Ephemeral live-classroom state (raised hands, microphone grants).

This is the state that only matters while a class is running and that changes
many times a minute. Keeping it in Redis instead of PostgreSQL keeps hot-path
writes off the database, and the keys expire on their own if a class ends
badly. Anything that must survive the class — attendance, presented pages,
saved boards — goes to PostgreSQL instead.

Redis is not a hard dependency: if it is unreachable the store falls back to
process-local memory. The backend runs as a single container today, so the
fallback is correct rather than merely convenient; the docstring on
`_memory_fallback` records what would change if that stops being true.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from config.settings import REDIS_URL

logger = logging.getLogger("agent")

# Live state outlives a long class but never a day.
_TTL_SECONDS = 12 * 60 * 60

_redis = None
_redis_failed = False

# _memory_fallback: used only when Redis is unavailable. With more than one
# backend replica this would need to become Redis-only, because two replicas
# would otherwise disagree about who has their hand up.
_memory_fallback: dict[str, dict[str, Any]] = {}


def _key(session_id: str, bucket: str) -> str:
    return f"lss:class:{session_id}:{bucket}"


async def _client():
    """Lazily connect to Redis; returns None once a connection has failed."""
    global _redis, _redis_failed
    if _redis_failed:
        return None
    if _redis is None:
        try:
            import redis.asyncio as aioredis
            _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
            await _redis.ping()
        except Exception as exc:
            logger.warning("[CLASSROOM] Redis unavailable, using in-process state: %s", exc)
            _redis = None
            _redis_failed = True
            return None
    return _redis


# ─── Generic hash helpers ─────────────────────────────────────────────────────

async def _hset(session_id: str, bucket: str, field: str, value: dict) -> None:
    client = await _client()
    if client is None:
        _memory_fallback.setdefault(_key(session_id, bucket), {})[field] = value
        return
    await client.hset(_key(session_id, bucket), field, json.dumps(value))
    await client.expire(_key(session_id, bucket), _TTL_SECONDS)


async def _hdel(session_id: str, bucket: str, field: str) -> None:
    client = await _client()
    if client is None:
        _memory_fallback.get(_key(session_id, bucket), {}).pop(field, None)
        return
    await client.hdel(_key(session_id, bucket), field)


async def _hgetall(session_id: str, bucket: str) -> dict[str, dict]:
    client = await _client()
    if client is None:
        return dict(_memory_fallback.get(_key(session_id, bucket), {}))
    raw = await client.hgetall(_key(session_id, bucket))
    out: dict[str, dict] = {}
    for field, value in (raw or {}).items():
        try:
            out[field] = json.loads(value)
        except ValueError:
            continue
    return out


# ─── Raise hand (spec §12) ────────────────────────────────────────────────────

async def raise_hand(session_id: str, user_id: str, user_name: str) -> None:
    await _hset(session_id, "hands", user_id, {
        "user_id": user_id, "user_name": user_name, "at": time.time(),
    })


async def lower_hand(session_id: str, user_id: str) -> None:
    await _hdel(session_id, "hands", user_id)


async def list_hands(session_id: str) -> list[dict]:
    """Raised hands, oldest first — so the teacher answers in fair order."""
    hands = list((await _hgetall(session_id, "hands")).values())
    hands.sort(key=lambda h: h.get("at", 0))
    return hands


# ─── Publishing grants (spec §5, §12) ─────────────────────────────────────────
#
# Students publish nothing until the teacher says so. A grant is stored per
# student and re-read when they reconnect, so a student who was allowed to speak
# does not lose that permission to a dropped connection mid-answer.

async def set_grant(session_id: str, user_id: str, *, mic: bool, camera: bool) -> None:
    if not mic and not camera:
        await _hdel(session_id, "grants", user_id)
        return
    await _hset(session_id, "grants", user_id, {
        "mic": bool(mic), "camera": bool(camera), "at": time.time(),
    })


async def get_grant(session_id: str, user_id: str) -> dict:
    grant = (await _hgetall(session_id, "grants")).get(user_id) or {}
    return {"mic": bool(grant.get("mic")), "camera": bool(grant.get("camera"))}


async def list_grants(session_id: str) -> dict[str, dict]:
    return await _hgetall(session_id, "grants")


async def clear_grants(session_id: str) -> None:
    """Revoke every student grant at once (used by Mute All / cameras off)."""
    client = await _client()
    if client is None:
        _memory_fallback.pop(_key(session_id, "grants"), None)
        return
    try:
        await client.delete(_key(session_id, "grants"))
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("[CLASSROOM] grant clear failed for %s: %s", session_id, exc)


# ─── Board / page snapshot for late joiners (spec §8, §22) ────────────────────
#
# Live drawing travels teacher → students directly over the media server's data
# channel, which is why a stroke appears instantly and costs the backend
# nothing. The snapshot is the catch-up copy: a student who joins ten minutes
# in, or whose connection drops mid-lesson, gets the board as it stands rather
# than a blank canvas and a lost explanation.

# A board is a page of handwriting, not a document. Anything beyond this is a
# runaway client, and truncating protects Redis from one bad session.
_MAX_SNAPSHOT_BYTES = 512 * 1024


async def save_snapshot(session_id: str, snapshot: dict) -> bool:
    """Store the current teaching surface. Returns False if it was too large."""
    encoded = json.dumps(snapshot)
    if len(encoded) > _MAX_SNAPSHOT_BYTES:
        return False

    client = await _client()
    if client is None:
        _memory_fallback[_key(session_id, "snapshot")] = snapshot
        return True
    await client.set(_key(session_id, "snapshot"), encoded, ex=_TTL_SECONDS)
    return True


async def get_snapshot(session_id: str) -> dict | None:
    client = await _client()
    if client is None:
        return _memory_fallback.get(_key(session_id, "snapshot"))
    raw = await client.get(_key(session_id, "snapshot"))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


# ─── Stage state (spec §8) ────────────────────────────────────────────────────

def merge_stage_state(current: dict | None, mode: str, state: dict | None) -> dict:
    """Update one teaching surface without disturbing the others.

    This is what makes the book ↔ whiteboard switch lossless: leaving page 42 to
    solve a sum on the board and coming back returns to page 42, because the
    book's state was merged rather than replaced. Pure function so the behaviour
    can be tested without a classroom.
    """
    merged = dict(current or {})
    if state:
        merged[mode] = {**(merged.get(mode) or {}), **state}
    return merged


def publish_sources(grant: dict, *, cameras_locked: bool) -> list[str]:
    """What a student may publish, given their grant and the room's camera lock.

    An individual microphone grant outranks the room-wide microphone lock —
    "you may answer" is exactly what that grant means, and it survives a
    reconnect. A room-wide camera lock is not overridden: it exists to keep
    thirty video streams off a home connection.
    """
    sources = []
    if grant.get("mic"):
        sources.append("microphone")
    if grant.get("camera") and not cameras_locked:
        sources.append("camera")
    return sources


# ─── Cleanup ──────────────────────────────────────────────────────────────────

async def clear_session(session_id: str) -> None:
    """Drop all live state for a finished class."""
    client = await _client()
    keys = [_key(session_id, bucket) for bucket in ("hands", "grants", "snapshot")]
    if client is None:
        for key in keys:
            _memory_fallback.pop(key, None)
        return
    try:
        await client.delete(*keys)
    except Exception as exc:  # pragma: no cover - cleanup is best effort
        logger.warning("[CLASSROOM] state cleanup failed for %s: %s", session_id, exc)

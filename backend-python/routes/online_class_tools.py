"""
Teaching tools — whiteboard, book presentation, screen share (spec §6–§11).

The teacher decides what the class is looking at, and every student's screen
follows automatically. What travels between them is tiny: "page 62 of this
book", "this stroke on the board". The pages themselves are rendered on each
device from the Knowledge Base file, so a lesson stays sharp on a connection
that could never carry video of a document.

Along the way the module records what was actually shown — which book, which
pages, which board — because that structured record is what lesson records and
(later) AI summaries are built from. Nothing here is inferred from speech.

Deliberately no `from __future__ import annotations` — see the note in
`routes/online_classes.py`: it breaks rate-limited endpoints that take a body.
"""
import asyncio
import base64
import binascii
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import create_scoped_token, get_current_user, user_from_request
from middleware.rate_limit import limiter
from models.models import Document, User, utcnow
from models.online_classes import (
    SESSION_LIVE,
    STAGE_MODES,
    STAGE_VIDEO,
    OnlineClassResource,
    OnlineClassSession,
    OnlineClassWhiteboard,
)
from services import class_events, classroom_state, presentation_service, storage_service
from services import livekit_service as lk
from services.classroom_access import get_session, is_host, require_host, require_member

logger = logging.getLogger("agent")

router = APIRouter(prefix="/online-classes", tags=["online-classes"])

WHITEBOARD_BUCKET_PREFIX = "whiteboards"
# A board snapshot is handwriting, not artwork; anything larger is a bug.
MAX_BOARD_IMAGE_BYTES = 4 * 1024 * 1024


# ─── Request bodies ───────────────────────────────────────────────────────────

class StageRequest(BaseModel):
    mode: str
    state: dict | None = None


class PresentRequest(BaseModel):
    document_id: str
    page: int = 1


class PageRequest(BaseModel):
    document_id: str
    page: int
    zoom: float | None = None


class SnapshotRequest(BaseModel):
    snapshot: dict


class WhiteboardSaveRequest(BaseModel):
    page_index: int = 0
    strokes: list | None = None
    image_base64: str | None = None
    include_in_lesson_record: bool = True


# ─── Stage: what everyone is looking at ───────────────────────────────────────

async def _apply_stage(
    db: AsyncSession,
    session: OnlineClassSession,
    user: User,
    mode: str,
    state: dict | None,
) -> dict:
    """Persist the teaching surface and tell the room.

    State is stored per mode rather than replaced, which is what makes the
    book ↔ whiteboard switch instant and lossless: leaving page 42 to solve a
    sum on the board and coming back returns to page 42, because the book's
    state was never thrown away (spec §8).
    """
    if mode not in STAGE_MODES:
        raise HTTPException(status_code=400, detail=f"Unknown stage mode: {mode}")

    merged = classroom_state.merge_stage_state(session.stage_state, mode, state)
    session.stage_mode = mode
    session.stage_state = merged

    await class_events.record(
        db, session.id, class_events.STAGE_CHANGED,
        actor_id=user.id, actor_role=user.role,
        payload={"mode": mode, "state": merged.get(mode) or {}},
    )
    await db.commit()

    payload = {"t": "stage", "mode": mode, "state": merged}
    await lk.broadcast_safely(session.room_name, payload)
    return {"mode": mode, "state": merged}


@router.post("/{session_id}/stage")
async def set_stage(
    session_id: str,
    body: StageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(db, session_id)
    require_host(session, user)
    if body.mode == STAGE_VIDEO and body.state:
        # A video id reaches every student's player, so it only ever arrives
        # through the endpoint that validates it. Switching back to a video
        # already on the stage (no state) is fine here.
        raise HTTPException(status_code=400, detail="Share videos through /video.")
    return await _apply_stage(db, session, user, body.mode, body.state)


# ─── Books and resources (spec §7) ────────────────────────────────────────────

@router.get("/{session_id}/resources")
async def list_resources(
    session_id: str,
    search: str | None = None,
    all_subjects: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Knowledge Base material this class can open, already filtered.

    Defaults to the subject being taught; `all_subjects` widens it for the
    cross-subject lesson, rather than making the teacher search a whole library
    to find their own book.
    """
    session = await get_session(db, session_id)
    require_host(session, user)

    return {
        "resources": await presentation_service.resources_for_class(
            db,
            class_name=session.class_name,
            subject=None if all_subjects else session.subject,
            search=search,
        ),
        "presented": [r.to_dict() for r in await _session_resources(db, session.id)],
    }


async def _session_resources(db: AsyncSession, session_id: str) -> list[OnlineClassResource]:
    result = await db.execute(
        select(OnlineClassResource)
        .where(OnlineClassResource.session_id == session_id)
        .order_by(OnlineClassResource.first_shown_at)
    )
    return list(result.scalars().all())


@router.post("/{session_id}/present")
async def present_document(
    session_id: str,
    body: PresentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """OPEN BOOK — put a Knowledge Base document on every student's screen."""
    session = await get_session(db, session_id)
    require_host(session, user)

    document = (await db.execute(
        select(Document).where(Document.id == body.document_id)
    )).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    presentable = await presentation_service.ensure_presentable(db, document)
    if presentable["state"] == "unsupported":
        raise HTTPException(
            status_code=415,
            detail="This file type cannot be presented. Use Share Screen instead.",
        )
    if presentable["state"] == "failed":
        raise HTTPException(
            status_code=422,
            detail="This document could not be prepared for presenting. Use Share Screen instead.",
        )
    if presentable["state"] == "converting":
        # Honest answer while LibreOffice works, so the teacher sees progress
        # rather than a blank screen in front of a class.
        return {
            "state": "converting",
            "document_id": document.id,
            "title": document.title,
            "message": "Preparing this document…",
        }

    resource = await _record_resource(db, session, document, page=body.page)
    await class_events.record(
        db, session.id, class_events.BOOK_OPENED,
        actor_id=user.id, actor_role=user.role,
        payload={"document_id": document.id, "title": document.title, "page": body.page},
    )

    stage = await _apply_stage(db, session, user, "book", {
        "document_id": document.id,
        "title": document.title,
        "kind": presentable["kind"],
        "page": body.page,
        "zoom": 1.0,
        "page_count": presentable.get("page_count"),
    })

    return {
        "state": "ready",
        "document_id": document.id,
        "title": document.title,
        "kind": presentable["kind"],
        "page_count": presentable.get("page_count"),
        "pages_presented": resource.pages_presented or [],
        "stage": stage,
    }


@router.get("/{session_id}/resources/{document_id}/status")
async def conversion_status(
    session_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll while a PowerPoint or Word file is being prepared."""
    session = await get_session(db, session_id)
    require_member(session, user)

    document = (await db.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    presentable = await presentation_service.ensure_presentable(db, document)
    return {
        "document_id": document_id,
        "state": presentable["state"],
        "kind": presentable.get("kind"),
        "page_count": presentable.get("page_count"),
        "error": presentable.get("error"),
    }


@router.post("/{session_id}/page")
async def present_page(
    session_id: str,
    body: PageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Move the class to another page, and record that the page was shown.

    "Shown" is all this claims. Whether every part of the page was taught is a
    judgement only the teacher can make, and they confirm it in the lesson
    record afterwards (spec §18).
    """
    session = await get_session(db, session_id)
    require_host(session, user)

    document = (await db.execute(
        select(Document).where(Document.id == body.document_id)
    )).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    resource = await _record_resource(db, session, document, page=body.page)
    await class_events.record(
        db, session.id, class_events.PAGE_PRESENTED,
        actor_id=user.id, actor_role=user.role,
        payload={"document_id": document.id, "page": body.page},
    )

    state = {"document_id": document.id, "title": document.title, "page": body.page}
    if body.zoom:
        state["zoom"] = body.zoom
    stage = await _apply_stage(db, session, user, "book", state)

    return {"page": body.page, "pages_presented": resource.pages_presented or [], "stage": stage}


async def _record_resource(
    db: AsyncSession,
    session: OnlineClassSession,
    document: Document,
    *,
    page: int | None,
) -> OnlineClassResource:
    resource = (await db.execute(
        select(OnlineClassResource).where(
            OnlineClassResource.session_id == session.id,
            OnlineClassResource.document_id == document.id,
        )
    )).scalar_one_or_none()

    now = utcnow()
    if resource is None:
        resource = OnlineClassResource(
            session_id=session.id,
            document_id=document.id,
            title=document.title,
            resource_type=document.document_type,
            pages_presented=[],
            first_shown_at=now,
        )
        db.add(resource)

    if page:
        pages = list(resource.pages_presented or [])
        if page not in pages:
            pages.append(page)
            pages.sort()
            # Reassigned rather than mutated: SQLAlchemy does not track
            # in-place changes to a JSON column, and a silently unsaved page
            # list would quietly corrupt the lesson record.
            resource.pages_presented = pages

    resource.last_shown_at = now
    await db.flush()
    return resource


# ─── Serving the file a student's browser renders ─────────────────────────────

@router.get("/{session_id}/resource-token")
async def resource_token(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A short-lived key for the browser's own fetches (PDF viewer, images).

    Separate from the session token because a PDF viewer cannot send our
    Authorization header, and a session token in a URL would be a session token
    in somebody's browser history.

    Stable within a window, because this token ends up in the URL of the
    textbook the browser downloads: a token that changed on every join made
    every rejoin a cache miss, and a class re-fetched a book it already had.
    """
    session = await get_session(db, session_id)
    require_member(session, user)
    return {
        "token": create_scoped_token(
            user.id, scope="resource", session_id=session.id, minutes=30, stable=True,
        ),
        "expires_in": 900,
    }


@router.get("/{session_id}/resources/{document_id}/file")
@limiter.limit("240/minute")
async def resource_file(
    request: Request,
    session_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Stream a presentable document to a member of this class.

    Range requests are honoured so a browser's PDF viewer can fetch the part of
    a 400-page textbook it needs instead of the whole book — the difference
    between a page appearing in a second and a class waiting a minute.
    """
    session = await get_session(db, session_id)
    user = await user_from_request(request, db, session_id=session_id)
    require_member(session, user)

    document = (await db.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Students may only fetch what the teacher actually opened in this class —
    # a class token is not a key to the whole Knowledge Base.
    if not is_host(session, user):
        opened = (await db.execute(
            select(OnlineClassResource).where(
                OnlineClassResource.session_id == session.id,
                OnlineClassResource.document_id == document_id,
            )
        )).scalar_one_or_none()
        if not opened:
            raise HTTPException(status_code=403, detail="This resource is not part of your class.")

    presentable = await presentation_service.ensure_presentable(db, document)
    if presentable["state"] != "ready":
        raise HTTPException(status_code=409, detail="This document is still being prepared.")

    object_name = presentable["object_name"]
    content_type = presentable.get("content_type", "application/octet-stream")

    try:
        size = await asyncio.to_thread(presentation_service.object_size, object_name)
    except Exception as exc:
        logger.warning("[PRESENTATION] object unavailable %s: %s", object_name, exc)
        raise HTTPException(status_code=404, detail="File unavailable")

    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        start, end = _parse_range(range_header, size)
        if start is None:
            raise HTTPException(status_code=416, detail="Invalid range")
        length = end - start + 1
        chunk = await asyncio.to_thread(
            presentation_service.read_object_range, object_name, start, length
        )
        return Response(
            content=chunk,
            status_code=206,
            media_type=content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Cache-Control": "private, max-age=86400, immutable",
            },
        )

    data = await asyncio.to_thread(presentation_service.read_object, object_name)
    return StreamingResponse(
        iter([data]),
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=86400, immutable",
        },
    )


def _parse_range(header: str, size: int) -> tuple[int | None, int | None]:
    try:
        spec = header.split("=", 1)[1].split(",")[0].strip()
        start_text, _, end_text = spec.partition("-")
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            # Suffix form: "bytes=-500" means the final 500 bytes.
            start = max(0, size - int(end_text))
            end = size - 1
        if start > end or start >= size:
            return None, None
        return start, min(end, size - 1)
    except (ValueError, IndexError):
        return None, None


# ─── Whiteboard (spec §6) ─────────────────────────────────────────────────────

@router.post("/{session_id}/whiteboard/snapshot")
@limiter.limit("120/minute")
async def save_board_snapshot(
    request: Request,
    session_id: str,
    body: SnapshotRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Keep a catch-up copy of the current board for late joiners.

    Sent periodically by the teacher's browser, not per stroke: live drawing
    goes directly to the students over the data channel, and this is only what
    someone who arrives late (or reconnects) needs in order to see the board
    that is already there.
    """
    session = await get_session(db, session_id)
    require_host(session, user)

    stored = await classroom_state.save_snapshot(session.id, {
        "at": time.time(),
        "stage_mode": session.stage_mode,
        **body.snapshot,
    })
    return {"stored": stored}


@router.get("/{session_id}/whiteboard/snapshot")
async def get_board_snapshot(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(db, session_id)
    require_member(session, user)
    return {
        "snapshot": await classroom_state.get_snapshot(session.id),
        "stage_mode": session.stage_mode,
        "stage_state": session.stage_state or {},
    }


@router.post("/{session_id}/whiteboard/save")
async def save_whiteboard(
    session_id: str,
    body: WhiteboardSaveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SAVE WHITEBOARD — keep the board as part of today's lesson record."""
    session = await get_session(db, session_id)
    require_host(session, user)

    image_object = None
    if body.image_base64:
        raw = body.image_base64.split(",", 1)[-1]
        try:
            image_bytes = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=400, detail="Board image was not valid image data.")
        if len(image_bytes) > MAX_BOARD_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Board image is too large.")

        image_object = (
            f"{WHITEBOARD_BUCKET_PREFIX}/{session.id}/"
            f"{int(datetime.utcnow().timestamp())}-p{body.page_index}.png"
        )
        await asyncio.to_thread(storage_service.upload_file, image_object, image_bytes, "image/png")

    board = OnlineClassWhiteboard(
        session_id=session.id,
        page_index=body.page_index,
        strokes=body.strokes or [],
        image_object=image_object,
        saved_by=user.id,
        include_in_lesson_record=body.include_in_lesson_record,
    )
    db.add(board)

    await class_events.record(
        db, session.id, class_events.WHITEBOARD_SAVED,
        actor_id=user.id, actor_role=user.role,
        payload={"page_index": body.page_index, "has_image": bool(image_object)},
    )
    await db.commit()
    await db.refresh(board)
    return board.to_dict()


@router.get("/{session_id}/whiteboard")
async def list_whiteboards(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(db, session_id)
    require_member(session, user)

    result = await db.execute(
        select(OnlineClassWhiteboard)
        .where(OnlineClassWhiteboard.session_id == session.id)
        .order_by(OnlineClassWhiteboard.created_at)
    )
    return {"boards": [b.to_dict() for b in result.scalars().all()]}


@router.get("/{session_id}/whiteboard/{board_id}/image")
async def whiteboard_image(
    session_id: str,
    board_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await get_session(db, session_id)
    require_member(session, user)

    board = (await db.execute(
        select(OnlineClassWhiteboard).where(
            OnlineClassWhiteboard.id == board_id,
            OnlineClassWhiteboard.session_id == session.id,
        )
    )).scalar_one_or_none()
    if not board or not board.image_object:
        raise HTTPException(status_code=404, detail="Board image not found")

    data = await asyncio.to_thread(storage_service.download_file, board.image_object)
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=86400"})


# ─── Screen share / document camera bookkeeping ───────────────────────────────

class ShareRequest(BaseModel):
    active: bool
    source: str = "screen"   # screen | document_camera


@router.post("/{session_id}/share")
async def share_state(
    session_id: str,
    body: ShareRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record that the teacher started or stopped sharing, and move the stage.

    The media itself flows through the media server; this endpoint exists so the
    class follows automatically and so the lesson record knows a screen or a
    physical book was shown.
    """
    session = await get_session(db, session_id)
    require_host(session, user)
    if session.status != SESSION_LIVE:
        raise HTTPException(status_code=409, detail="This class is not live.")

    await class_events.record(
        db, session.id,
        class_events.SCREEN_SHARE_STARTED if body.active else class_events.SCREEN_SHARE_STOPPED,
        actor_id=user.id, actor_role=user.role, payload={"source": body.source},
    )

    if body.active:
        stage = await _apply_stage(db, session, user, "screen", {"source": body.source})
    else:
        # Falling back to the board or the book the class was on beats dropping
        # everyone onto a camera view mid-explanation.
        previous = (session.stage_state or {}).get("book") and "book" or "camera"
        stage = await _apply_stage(db, session, user, previous, None)

    return {"active": body.active, "stage": stage}


# ─── Shared video ─────────────────────────────────────────────────────────────

class VideoRequest(BaseModel):
    # A link to put a new video on the stage; omitted when the teacher only
    # plays, pauses or seeks the video already there.
    url: str | None = None
    playing: bool = False
    position: float | None = None


@router.post("/{session_id}/video")
async def share_video(
    session_id: str,
    body: VideoRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SHARE VIDEO — a YouTube video every student's device plays itself.

    Screen sharing cannot do this from a phone (no mobile browser can capture
    its screen), and from a laptop it sends the video as a second-hand stream.
    Here each device plays the original, sound included, and only "playing at
    1:32" crosses the classroom connection.

    Play, pause and seek are sent through here too, so a student who joins late
    starts at the right moment. The live position between those moments travels
    over the data channel from the teacher's browser, never through this route.
    """
    session = await get_session(db, session_id)
    require_host(session, user)
    if session.status != SESSION_LIVE:
        raise HTTPException(status_code=409, detail="This class is not live.")

    current = (session.stage_state or {}).get(STAGE_VIDEO) or {}

    if body.url is not None:
        parsed = classroom_state.parse_youtube_link(body.url)
        if not parsed:
            raise HTTPException(
                status_code=400,
                detail="That is not a YouTube video link. Copy the link from YouTube's Share button.",
            )
        video_id, start = parsed
        position = body.position if body.position is not None else start
        if video_id != current.get("video_id"):
            await class_events.record(
                db, session.id, class_events.VIDEO_SHARED,
                actor_id=user.id, actor_role=user.role,
                payload={"video_id": video_id, "start": start},
            )
        mode = STAGE_VIDEO
    else:
        video_id = current.get("video_id")
        if not video_id:
            raise HTTPException(status_code=400, detail="No video is being shared.")
        position = body.position if body.position is not None else current.get("position", 0)
        # A pause that lands after the teacher has already moved on to the
        # board must not drag the class back to the video.
        mode = session.stage_mode

    session.stage_state = classroom_state.merge_stage_state(
        session.stage_state, STAGE_VIDEO,
        classroom_state.video_stage_state(video_id, playing=body.playing, position=position),
    )
    return await _apply_stage(db, session, user, mode, None)

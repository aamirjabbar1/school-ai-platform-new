"""
Media layer — LiveKit integration.

Everything that touches the video engine lives behind this module, so swapping
providers later means rewriting one file rather than the classroom.

Two rules hold throughout:

  * The API key and secret never leave the server. Browsers receive only a
    short-lived, narrowly scoped access token minted here.
  * A browser is never granted room-admin rights. Teacher controls are requests
    to our API, which authorizes them and then acts on the room itself.

No audio or video is ever read, stored or forwarded by this module — it only
hands out permission to join a room. There is no transcription path anywhere.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import timedelta
from typing import Any

from config.settings import (
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_HTTP_URL,
    LIVEKIT_TOKEN_TTL_HOURS,
    LIVEKIT_URL,
)

logger = logging.getLogger("agent")


class LiveKitUnavailable(RuntimeError):
    """Raised when the media server is not configured or cannot be reached."""


# ─── Configuration ────────────────────────────────────────────────────────────

def is_configured() -> bool:
    return bool(LIVEKIT_API_KEY and LIVEKIT_API_SECRET and LIVEKIT_URL)


def public_url() -> str:
    """The wss:// URL a browser should connect to."""
    return LIVEKIT_URL


def room_name_for(session_id: str) -> str:
    """Room names derive from the session UUID, so they cannot be guessed and
    no meeting ID is ever shown to a user."""
    return f"lss-{session_id}"


def _require_sdk():
    try:
        from livekit import api  # noqa: PLC0415  (optional dependency, imported lazily)
        return api
    except ImportError as exc:  # pragma: no cover - depends on deployment image
        raise LiveKitUnavailable(
            "livekit-api is not installed in this image. Rebuild the backend "
            "container after adding it to requirements.txt."
        ) from exc


def _require_config():
    if not is_configured():
        raise LiveKitUnavailable(
            "Online Classes is not configured: set LIVEKIT_URL, LIVEKIT_API_KEY "
            "and LIVEKIT_API_SECRET."
        )


# ─── Access tokens ────────────────────────────────────────────────────────────

def create_access_token(
    *,
    identity: str,
    display_name: str,
    room: str,
    can_publish: bool,
    can_publish_data: bool = True,
    can_subscribe: bool = True,
    hidden: bool = False,
    metadata: dict[str, Any] | None = None,
    ttl_hours: int | None = None,
) -> str:
    """Mint a join token for one user and one room.

    `identity` is the LSS user id, which is what makes attendance possible: the
    webhook that reports a join carries this identity straight back to us.
    Nobody ever receives `room_admin` — not even the teacher.
    """
    _require_config()
    api = _require_sdk()

    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=can_publish,
        can_subscribe=can_subscribe,
        can_publish_data=can_publish_data,
        can_update_own_metadata=False,
        hidden=hidden,
    )

    token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(display_name or identity)
        .with_grants(grants)
        .with_ttl(timedelta(hours=ttl_hours or LIVEKIT_TOKEN_TTL_HOURS))
    )
    if metadata:
        token = token.with_metadata(json.dumps(metadata))
    return token.to_jwt()


# ─── Room service client ──────────────────────────────────────────────────────

_client = None  # livekit.api.LiveKitAPI singleton (holds an aiohttp session)


def _get_client():
    global _client
    if _client is None:
        _require_config()
        api = _require_sdk()
        _client = api.LiveKitAPI(
            url=LIVEKIT_HTTP_URL or LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://"),
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
        )
    return _client


async def close_client() -> None:
    """Release the HTTP session (called from the FastAPI lifespan on shutdown)."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as exc:  # pragma: no cover - shutdown best effort
            logger.warning("[LIVEKIT] client close failed: %s", exc)
        _client = None


# ─── Room operations ──────────────────────────────────────────────────────────

async def ensure_room(room: str, *, metadata: dict[str, Any] | None = None) -> None:
    """Make sure the room exists on the media server before anyone connects.

    `auto_create` is off in livekit.yaml, deliberately: a browser holding a
    token must not be able to conjure a room of its own. The consequence is
    that the room has to be created here first — a client connecting to a room
    that does not exist is refused with 404 "requested room does not exist",
    which reaches the teacher as "Could not connect to the class".

    Rooms are ephemeral, so this cannot be a one-off at START CLASS: the media
    server drops an empty room after `empty_timeout`, and a restart takes every
    room with it. Calling this on every token issue means a class that sat empty
    for ten minutes, or survived a media-server restart, is simply re-created
    when the next person joins instead of being dead for its remaining hour.

    CreateRoom is idempotent — an existing room is returned as-is, participants
    undisturbed — so calling it on every join is safe. Timeouts and participant
    limits deliberately come from livekit.yaml rather than being repeated here.
    """
    api = _require_sdk()
    client = _get_client()
    request = api.CreateRoomRequest(name=room)
    if metadata:
        request.metadata = json.dumps(metadata)
    await client.room.create_room(request)


async def list_participants(room: str) -> list[dict]:
    """Who is actually connected right now, according to the media server."""
    api = _require_sdk()
    client = _get_client()
    resp = await client.room.list_participants(api.ListParticipantsRequest(room=room))
    out = []
    for p in resp.participants:
        metadata = {}
        if p.metadata:
            try:
                metadata = json.loads(p.metadata)
            except ValueError:
                metadata = {}
        out.append({
            "identity": p.identity,
            "sid": p.sid,
            "name": p.name,
            "state": int(p.state),
            "joined_at": int(p.joined_at),
            "metadata": metadata,
            "tracks": [
                {"sid": t.sid, "source": int(t.source), "muted": bool(t.muted), "type": int(t.type)}
                for t in p.tracks
            ],
        })
    return out


async def set_participant_permissions(
    room: str,
    identity: str,
    *,
    sources: list[str] | None = None,
    can_subscribe: bool = True,
    can_publish_data: bool = True,
) -> None:
    """Set exactly what one participant may publish.

    `sources` is a list drawn from "microphone", "camera" and "screen_share";
    an empty list revokes publishing entirely. Restricting by source is what
    makes "this student may speak" mean only that — a granted student still
    cannot start a camera or take over the screen.
    """
    api = _require_sdk()
    client = _get_client()

    wanted = [s for s in (sources or []) if s]
    permission_kwargs: dict[str, Any] = {
        "can_publish": bool(wanted),
        "can_subscribe": can_subscribe,
        "can_publish_data": can_publish_data,
    }
    if wanted:
        enums = [e for e in (_track_source(name) for name in wanted) if e is not None]
        if enums:
            permission_kwargs["can_publish_sources"] = enums

    await client.room.update_participant(
        api.UpdateParticipantRequest(
            room=room,
            identity=identity,
            permission=_participant_permission(**permission_kwargs),
        )
    )


def _participant_permission(**kwargs):
    api = _require_sdk()
    cls = getattr(api, "ParticipantPermission", None)
    if cls is None:  # older SDK layouts keep it under the protocol package
        from livekit.protocol import models as lk_models
        cls = lk_models.ParticipantPermission
    return cls(**kwargs)


def _track_source(name: str):
    """Map "microphone"/"camera"/"screen_share" to the SDK's TrackSource enum."""
    api = _require_sdk()
    source = getattr(api, "TrackSource", None)
    if source is None:
        try:
            from livekit.protocol import models as lk_models
            source = lk_models.TrackSource
        except ImportError:  # pragma: no cover - defensive
            return None
    return getattr(source, name.upper(), None)


async def mute_participant(room: str, identity: str, *, muted: bool = True) -> int:
    """Mute (or unmute) every audio track a participant is publishing.

    Returns how many tracks were changed. Unmuting only works if the
    participant is still permitted to publish — permission is the real control,
    muting is the immediate one.
    """
    api = _require_sdk()
    client = _get_client()

    participants = await list_participants(room)
    target = next((p for p in participants if p["identity"] == identity), None)
    if not target:
        return 0

    changed = 0
    for track in target["tracks"]:
        # source 2 == MICROPHONE in the LiveKit track-source enum
        if track["source"] != 2:
            continue
        await client.room.mute_published_track(
            api.MuteRoomTrackRequest(
                room=room, identity=identity, track_sid=track["sid"], muted=muted
            )
        )
        changed += 1
    return changed


async def remove_participant(room: str, identity: str) -> None:
    api = _require_sdk()
    client = _get_client()
    await client.room.remove_participant(
        api.RoomParticipantIdentity(room=room, identity=identity)
    )


async def end_room(room: str) -> None:
    """Close the room and disconnect everyone (End Class for Everyone)."""
    api = _require_sdk()
    client = _get_client()
    await client.room.delete_room(api.DeleteRoomRequest(room=room))


async def update_room_metadata(room: str, metadata: dict[str, Any]) -> None:
    api = _require_sdk()
    client = _get_client()
    await client.room.update_room_metadata(
        api.UpdateRoomMetadataRequest(room=room, metadata=json.dumps(metadata))
    )


async def broadcast(
    room: str,
    message: dict[str, Any],
    *,
    to_identities: list[str] | None = None,
) -> None:
    """Push a classroom state message to connected clients.

    This is how "the teacher opened page 42", "your microphone was enabled" and
    "the class has ended" reach the browser instantly. It carries classroom
    state only — never media, never anything an AI produced.
    """
    api = _require_sdk()
    client = _get_client()
    request_kwargs: dict[str, Any] = {
        "room": room,
        "data": json.dumps(message).encode("utf-8"),
        "kind": _reliable_kind(),
    }
    if to_identities:
        request_kwargs["destination_identities"] = to_identities
    await client.room.send_data(api.SendDataRequest(**request_kwargs))


def _reliable_kind():
    api = _require_sdk()
    packet = getattr(api, "DataPacket", None)
    if packet is None:
        from livekit.protocol import models as lk_models
        packet = lk_models.DataPacket
    return packet.Kind.RELIABLE


async def broadcast_safely(room: str, message: dict[str, Any]) -> None:
    """Broadcast without letting a media-server hiccup fail the HTTP request.

    The database is the source of truth for classroom state; this message is
    only the fast path. Clients that miss it re-read state on their next poll
    or on reconnect, so a dropped broadcast degrades latency, not correctness.
    """
    try:
        await broadcast(room, message)
    except Exception as exc:
        logger.warning("[LIVEKIT] broadcast failed for room %s: %s", room, exc)


# ─── Recording (spec §15) ─────────────────────────────────────────────────────
#
# A room-composite recording: one MP4 of the lesson as a student saw it,
# uploaded by the recorder straight to object storage. It is an audio/video
# file and nothing more — it is never transcribed, and no AI model is given
# access to it.

def recording_configured() -> bool:
    from config.settings import RECORDING_S3_ENDPOINT
    return bool(is_configured() and RECORDING_S3_ENDPOINT)


async def start_recording(room: str, object_key: str) -> str:
    """Begin recording a room. Returns the recorder's job id."""
    from config.settings import (
        RECORDING_BUCKET, RECORDING_S3_ACCESS_KEY, RECORDING_S3_ENDPOINT,
        RECORDING_S3_REGION, RECORDING_S3_SECRET_KEY,
    )

    if not RECORDING_S3_ENDPOINT:
        raise LiveKitUnavailable(
            "Recording storage is not configured: set RECORDING_S3_ENDPOINT."
        )

    api = _require_sdk()
    client = _get_client()

    request = api.RoomCompositeEgressRequest(
        room_name=room,
        # "speaker" keeps whoever is talking — and whatever is being presented —
        # as the main frame, which is what a student re-watching a lesson needs.
        layout="speaker",
        audio_only=False,
        file_outputs=[
            api.EncodedFileOutput(
                file_type=api.EncodedFileType.MP4,
                filepath=object_key,
                s3=api.S3Upload(
                    access_key=RECORDING_S3_ACCESS_KEY,
                    secret=RECORDING_S3_SECRET_KEY,
                    region=RECORDING_S3_REGION,
                    bucket=RECORDING_BUCKET,
                    endpoint=RECORDING_S3_ENDPOINT,
                    force_path_style=True,
                ),
            )
        ],
    )
    info = await client.egress.start_room_composite_egress(request)
    return info.egress_id


async def stop_recording(egress_id: str) -> None:
    api = _require_sdk()
    client = _get_client()
    await client.egress.stop_egress(api.StopEgressRequest(egress_id=egress_id))


# ─── Webhooks ─────────────────────────────────────────────────────────────────

def verify_webhook(body: bytes, auth_header: str | None) -> dict:
    """Verify a LiveKit webhook and return its decoded JSON body.

    LiveKit signs each delivery with a JWT whose `sha256` claim is the digest of
    the request body, so verifying the token alone is not enough — the body has
    to hash to the value that was signed. Verified here by hand (python-jose is
    already a dependency) rather than through the SDK, so webhook handling does
    not move when the SDK's helper classes do.
    """
    _require_config()
    if not auth_header:
        raise ValueError("Missing Authorization header")

    from jose import jwt, JWTError

    token = auth_header.split(" ", 1)[1] if " " in auth_header else auth_header
    try:
        claims = jwt.decode(
            token,
            LIVEKIT_API_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise ValueError(f"Invalid webhook signature: {exc}") from exc

    expected = claims.get("sha256")
    if not expected:
        raise ValueError("Webhook token carries no body digest")

    actual = base64.b64encode(hashlib.sha256(body).digest()).decode()
    # LiveKit has used both standard and unpadded base64 over time.
    if actual != expected and actual.rstrip("=") != str(expected).rstrip("="):
        raise ValueError("Webhook body does not match its signature")

    return json.loads(body.decode("utf-8"))

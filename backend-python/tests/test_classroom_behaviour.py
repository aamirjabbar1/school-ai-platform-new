"""
Unit tests for classroom behaviour: teaching surfaces, publishing grants,
scoped media links, the timetable and recording bookkeeping.

Companion to `test_online_classes.py`, which covers authorization, attendance,
webhooks and AI cost control. Neither needs a database, a media server or an AI
provider.
"""
from __future__ import annotations

from datetime import date as date_type, datetime, time as time_type, timedelta

import pytest

from models.online_classes import OnlineClassSchedule, OnlineClassSession


def make_session(**kwargs):
    defaults = dict(id="s1", teacher_id="t1", subject="Mathematics",
                    class_name="Class 5", section="A")
    defaults.update(kwargs)
    return OnlineClassSession(**defaults)


# ─── Teaching surfaces (spec §8) ──────────────────────────────────────────────

class TestStageState:
    def test_book_state_survives_a_trip_to_the_whiteboard(self):
        """The spec's own example: explaining page 42, switching to the board to
        solve a sum, then returning to page 42."""
        from services.classroom_state import merge_stage_state

        state = merge_stage_state({}, "book", {"document_id": "d1", "page": 42})
        state = merge_stage_state(state, "whiteboard", {"page": 0})
        state = merge_stage_state(state, "book", None)

        assert state["book"]["page"] == 42
        assert state["book"]["document_id"] == "d1"
        assert state["whiteboard"]["page"] == 0

    def test_partial_updates_merge_rather_than_replace(self):
        from services.classroom_state import merge_stage_state

        state = merge_stage_state({}, "book", {"document_id": "d1", "page": 42, "zoom": 1.0})
        state = merge_stage_state(state, "book", {"zoom": 1.5})
        assert state["book"] == {"document_id": "d1", "page": 42, "zoom": 1.5}

    def test_switching_surface_without_state_changes_nothing(self):
        from services.classroom_state import merge_stage_state

        before = {"book": {"page": 7}}
        assert merge_stage_state(before, "camera", None) == before


# ─── Shared video ─────────────────────────────────────────────────────────────

class TestYouTubeLinks:
    ID = "dQw4w9WgXcQ"

    def parse(self, link):
        from services.classroom_state import parse_youtube_link
        return parse_youtube_link(link)

    @pytest.mark.parametrize("link", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=2",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=AbCdEf",
        "youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/live/dQw4w9WgXcQ?feature=share",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "  dQw4w9WgXcQ  ",
    ])
    def test_every_way_a_teacher_copies_a_link(self, link):
        assert self.parse(link) == (self.ID, 0)

    @pytest.mark.parametrize("link, start", [
        ("https://youtu.be/dQw4w9WgXcQ?t=90", 90),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=90s", 90),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1m30s", 90),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ?start=45", 45),
        ("https://youtu.be/dQw4w9WgXcQ?t=nonsense", 0),
    ])
    def test_a_link_to_a_moment_starts_there(self, link, start):
        assert self.parse(link) == (self.ID, start)

    @pytest.mark.parametrize("link", [
        "",
        None,
        "https://evil.example.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ",
        "javascript:alert(1)//youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ\"><script>",
        "https://www.youtube.com/@SomeChannel",
        "https://www.youtube.com/playlist?list=PL123",
    ])
    def test_anything_else_is_refused(self, link):
        assert self.parse(link) is None


class TestVideoStageState:
    def test_state_is_stamped_and_clamped(self):
        from services.classroom_state import video_stage_state

        state = video_stage_state("dQw4w9WgXcQ", playing=1, position=-4, now=1000.0)
        assert state == {
            "video_id": "dQw4w9WgXcQ", "playing": True, "position": 0.0, "updated_at": 1000.0,
        }

    def test_a_nonsense_position_starts_from_the_beginning(self):
        from services.classroom_state import video_stage_state

        assert video_stage_state("dQw4w9WgXcQ", playing=False, position=float("nan"))["position"] == 0.0

    def test_playing_the_video_keeps_the_book_where_it_was(self):
        from services.classroom_state import merge_stage_state, video_stage_state

        state = merge_stage_state({}, "book", {"document_id": "d1", "page": 42})
        state = merge_stage_state(state, "video", video_stage_state("dQw4w9WgXcQ", playing=True, position=12))
        assert state["book"]["page"] == 42
        assert state["video"]["position"] == 12


class TestPublishGrants:
    def sources(self, grant, cameras_locked=False):
        from services.classroom_state import publish_sources
        return publish_sources(grant, cameras_locked=cameras_locked)

    def test_students_publish_nothing_by_default(self):
        assert self.sources({"mic": False, "camera": False}) == []

    def test_microphone_grant_outranks_the_room_lock(self):
        """Being allowed to answer has to survive a reconnect, or a student
        loses the microphone their teacher just gave them."""
        assert self.sources({"mic": True, "camera": False}) == ["microphone"]

    def test_camera_lock_overrides_an_individual_camera_grant(self):
        assert self.sources({"mic": True, "camera": True}, cameras_locked=True) == ["microphone"]

    def test_camera_allowed_when_the_room_is_not_locked(self):
        assert self.sources({"mic": True, "camera": True}) == ["microphone", "camera"]

    def test_screen_share_is_never_granted_to_a_student(self):
        assert "screen_share" not in self.sources({"mic": True, "camera": True})


# ─── Scoped media links (spec §24) ────────────────────────────────────────────

class TestScopedTokens:
    @pytest.fixture(autouse=True)
    def _secret(self, monkeypatch):
        import middleware.auth as auth
        monkeypatch.setattr(auth, "JWT_SECRET", "unit-test-secret")

    def test_token_round_trips_for_its_own_class(self):
        from middleware.auth import create_scoped_token, decode_scoped_token

        token = create_scoped_token("user-1", scope="resource", session_id="sess-1")
        assert decode_scoped_token(token, scope="resource", session_id="sess-1") == "user-1"

    def test_token_from_another_class_is_refused(self):
        """A leaked book URL must be worth nothing in a different classroom."""
        from fastapi import HTTPException
        from middleware.auth import create_scoped_token, decode_scoped_token

        token = create_scoped_token("user-1", scope="resource", session_id="sess-1")
        with pytest.raises(HTTPException) as exc:
            decode_scoped_token(token, scope="resource", session_id="sess-2")
        assert exc.value.status_code == 403

    def test_token_for_another_purpose_is_refused(self):
        from fastapi import HTTPException
        from middleware.auth import create_scoped_token, decode_scoped_token

        token = create_scoped_token("user-1", scope="resource", session_id="sess-1")
        with pytest.raises(HTTPException):
            decode_scoped_token(token, scope="recording-export", session_id="sess-1")

    def test_expired_token_is_refused(self):
        from fastapi import HTTPException
        from middleware.auth import create_scoped_token, decode_scoped_token

        token = create_scoped_token("user-1", scope="resource", session_id="sess-1", minutes=-1)
        with pytest.raises(HTTPException) as exc:
            decode_scoped_token(token, scope="resource", session_id="sess-1")
        assert exc.value.status_code == 401

    def test_session_token_is_not_accepted_as_a_media_link(self):
        """The ordinary login token must not double as a media URL, or a link in
        a browser history would carry a full session."""
        from fastapi import HTTPException
        from middleware.auth import create_token, decode_scoped_token

        with pytest.raises(HTTPException):
            decode_scoped_token(create_token("user-1"), scope="resource", session_id="sess-1")


# ─── Timetable (spec §20) ─────────────────────────────────────────────────────

class TestScheduleOccurrence:
    def weekly(self, weekday, hour=8, **kwargs):
        return OnlineClassSchedule(
            recurrence="weekly", weekday=weekday, start_time=time_type(hour, 0),
            duration_minutes=40, **kwargs,
        )

    def test_later_today_is_the_next_occurrence(self):
        from routes.class_schedules import _next_occurrence

        now = datetime(2026, 9, 16, 6, 0)            # Wednesday morning
        assert _next_occurrence(self.weekly(2), now) == datetime(2026, 9, 16, 8, 0)

    def test_a_finished_slot_rolls_to_next_week(self):
        from routes.class_schedules import _next_occurrence

        now = datetime(2026, 9, 16, 18, 0)           # Wednesday evening
        assert _next_occurrence(self.weekly(2), now) == datetime(2026, 9, 23, 8, 0)

    def test_term_end_stops_the_slot(self):
        from routes.class_schedules import _next_occurrence

        schedule = self.weekly(2, end_date=date_type(2026, 9, 1))
        assert _next_occurrence(schedule, datetime(2026, 9, 16, 6, 0)) is None

    def test_slot_before_the_term_starts_is_not_scheduled(self):
        from routes.class_schedules import _next_occurrence

        schedule = self.weekly(2, start_date=date_type(2026, 10, 1))
        assert _next_occurrence(schedule, datetime(2026, 9, 16, 6, 0)) is None

    def test_one_off_class_uses_its_date(self):
        from routes.class_schedules import _next_occurrence

        schedule = OnlineClassSchedule(
            recurrence="once", class_date=date_type(2026, 9, 20),
            start_time=time_type(9, 30), duration_minutes=40,
        )
        assert _next_occurrence(schedule, datetime(2026, 9, 16, 6, 0)) == datetime(2026, 9, 20, 9, 30)


# ─── Recording bookkeeping (spec §15) ─────────────────────────────────────────

class TestRecordingStorage:
    def test_object_key_is_browsable_by_a_human(self):
        from routes.class_recordings import _object_key

        session = make_session(
            id="abc123", subject="General Science",
            actual_start=datetime(2026, 9, 16, 8, 0), class_name="Class 5",
        )
        assert _object_key(session) == "2026/09/16/Class 5/General_Science/abc123.mp4"

    def test_recording_is_off_unless_switched_on(self):
        """Recording must be an explicit decision, never a default that quietly
        films a room full of children."""
        assert make_session().recording_enabled in (None, False)


# ─── Module defaults (spec §19F, §24) ─────────────────────────────────────────

class TestSettingsDefaults:
    def settings(self):
        from models.online_classes import OnlineClassSettings
        return OnlineClassSettings()

    def test_recording_is_disabled_school_wide_by_default(self):
        settings = self.settings()
        assert settings.recording_enabled_globally in (None, False)
        assert settings.recording_default_on in (None, False)

    def test_observation_is_announced_by_default(self):
        """Silent supervision of a room full of children is not a default."""
        from models.online_classes import OnlineClassSettings
        column = OnlineClassSettings.__table__.c.announce_admin_observe
        assert column.default.arg is True

    def test_young_class_list_covers_pre_primary_through_class_2(self):
        from models.online_classes import OnlineClassSettings
        default = OnlineClassSettings.__table__.c.young_classes.default.arg(None)
        assert default == ["Pre-Nursery", "Nursery", "KG", "Class 1", "Class 2"]


# ─── Reaching the media server (spec §5, §22) ─────────────────────────────────

class TestRoomIsCreatedBeforeAnyoneDials:
    """`auto_create` is off on the media server, so a browser cannot open a room
    by connecting to it — the server must create it first. Issuing a token for a
    room that was never created produces a valid token, a successful-looking API
    response, and then a 404 in the browser that reads "Could not connect to the
    class". A class can be live in the database and unreachable in practice, and
    nothing short of dialling it would say so.

    Rooms are also ephemeral: the media server drops an empty one after
    `empty_timeout` and loses all of them on restart. So this is checked on every
    token issue, not once at START CLASS.
    """

    @pytest.fixture
    def issue(self, monkeypatch):
        import asyncio
        from routes import online_classes as oc

        calls = []

        async def fake_ensure_room(room, **kwargs):
            calls.append(("ensure_room", room))

        def fake_token(**kwargs):
            calls.append(("token", kwargs["room"]))
            return "fake-jwt"

        monkeypatch.setattr(oc.lk, "ensure_room", fake_ensure_room)
        monkeypatch.setattr(oc.lk, "create_access_token", fake_token)
        monkeypatch.setattr(oc.lk, "public_url", lambda: "wss://media.example")

        def run(session, user, role="teacher", sources=("microphone", "camera")):
            return asyncio.run(oc._issue_token(session, user, role=role, sources=list(sources))), calls

        return run

    def make_user(self):
        import types
        return types.SimpleNamespace(id="u1", name="A Teacher", role="teacher")

    def test_the_room_is_created_before_the_token_is_minted(self, issue):
        session = make_session(room_name="lss-s1")
        payload, calls = issue(session, self.make_user())
        assert calls == [("ensure_room", "lss-s1"), ("token", "lss-s1")], (
            "the room must exist before a browser is handed a token for it"
        )
        assert payload["token"] == "fake-jwt"

    def test_a_student_join_also_ensures_the_room(self, issue):
        """A class whose room expired while empty must heal when the next
        student joins, not stay broken for the rest of the period."""
        session = make_session(room_name="lss-s1")
        _, calls = issue(session, self.make_user(), role="student", sources=())
        assert ("ensure_room", "lss-s1") in calls

    def test_no_token_is_issued_when_the_room_cannot_be_created(self, monkeypatch):
        """Better an honest error than a token that cannot connect."""
        import asyncio
        from fastapi import HTTPException
        from routes import online_classes as oc

        async def boom(room, **kwargs):
            raise oc.lk.LiveKitUnavailable("media server down")

        issued = []
        monkeypatch.setattr(oc.lk, "ensure_room", boom)
        monkeypatch.setattr(oc.lk, "create_access_token",
                            lambda **kw: issued.append(kw) or "should-not-happen")

        import types
        user = types.SimpleNamespace(id="u1", name="A Teacher", role="teacher")
        with pytest.raises(HTTPException) as caught:
            asyncio.run(oc._issue_token(make_session(room_name="lss-s1"), user,
                                        role="teacher", sources=["microphone"]))
        assert caught.value.status_code == 503
        assert not issued, "a token for an unreachable room must not be handed out"


# ─── Classes that nobody ended (spec §22) ─────────────────────────────────────

class TestAbandonedClassesAreClosed:
    """A class that stays "live" forever keeps showing a JOIN CLASS card to a
    whole class of children for a lesson that is not happening. The disconnect
    sweep cannot catch every case: a teacher whose browser never connected has
    no disconnect to record, so the class has to be judged on its own clock.
    """

    def session_started(self, minutes_ago, planned=40):
        session = make_session(planned_duration_minutes=planned)
        session.actual_start = datetime(2026, 9, 16, 12, 0) - timedelta(minutes=minutes_ago)
        return session

    def now(self):
        return datetime(2026, 9, 16, 12, 0)

    def test_a_class_inside_its_period_is_left_alone(self):
        from tasks.online_class_tasks import is_overrun
        assert is_overrun(self.session_started(10), self.now()) is False

    def test_a_class_running_a_little_over_is_left_alone(self):
        """Lessons overrun. That is not abandonment."""
        from tasks.online_class_tasks import is_overrun
        assert is_overrun(self.session_started(55), self.now()) is False

    def test_a_class_long_past_its_end_is_stale(self):
        from tasks.online_class_tasks import is_overrun
        assert is_overrun(self.session_started(40 + 31), self.now()) is True

    def test_a_class_that_never_started_is_not_judged_by_this_rule(self):
        from tasks.online_class_tasks import is_overrun
        session = make_session()
        session.actual_start = None
        assert is_overrun(session, self.now()) is False

    def test_a_long_lesson_gets_its_full_length(self):
        """The grace runs from the planned end, not from a fixed hour, so a
        double period is not closed at the same moment as a single one."""
        from tasks.online_class_tasks import is_overrun
        assert is_overrun(self.session_started(100, planned=90), self.now()) is False
        assert is_overrun(self.session_started(125, planned=90), self.now()) is True


# ─── A room going empty is not a lesson ending (spec §22) ─────────────────────

class TestRoomFinishedDoesNotEndTheLesson:
    """The media server's rooms are ephemeral — one disappears when the last
    person drops, after the empty timeout, or on a restart. Treating that as the
    end of the lesson ended classes underneath teachers whose connection blinked,
    finalised registers mid-lesson, and refused the rejoin with "This class is
    not live" — for a room that the next join would simply re-create.

    Closure belongs to the grace clock, not to the room's existence.
    """

    def fire(self, monkeypatch, session, event="room_finished"):
        import asyncio
        import types
        from routes import livekit_webhooks as wh

        async def noop(*args, **kwargs):
            return None

        async def body():
            return b"{}"

        async def session_for_room(db, room):
            return session

        payload = {"event": event, "room": {"name": session.room_name}}
        monkeypatch.setattr(wh.lk, "verify_webhook", lambda b, a: payload)
        monkeypatch.setattr(wh, "_session_for_room", session_for_room)
        monkeypatch.setattr(wh.class_events, "record", noop)
        monkeypatch.setattr(wh.attendance_service, "finalize_session", noop)
        monkeypatch.setattr(wh.classroom_state, "clear_session", noop)

        request = types.SimpleNamespace(body=body)
        db = types.SimpleNamespace(commit=noop)
        return asyncio.run(wh.livekit_webhook(request, None, db))

    def live_session(self):
        from models.online_classes import SESSION_LIVE
        session = make_session(room_name="lss-s1")
        session.status = SESSION_LIVE
        session.teacher_disconnected_at = None
        return session

    def test_the_class_stays_live(self, monkeypatch):
        from models.online_classes import SESSION_LIVE
        session = self.live_session()
        self.fire(monkeypatch, session)
        assert session.status == SESSION_LIVE, (
            "a teacher whose connection dropped must be able to rejoin the same lesson"
        )

    def test_the_grace_clock_starts(self, monkeypatch):
        """Still live, but counting: a teacher who never returns is closed by
        the grace rules rather than left hanging forever."""
        session = self.live_session()
        self.fire(monkeypatch, session)
        assert session.teacher_disconnected_at is not None

    def test_a_repeated_event_does_not_restart_the_clock(self, monkeypatch):
        """Otherwise a room that finishes every few minutes would postpone the
        grace period indefinitely and the class really would hang."""
        session = self.live_session()
        self.fire(monkeypatch, session)
        first = session.teacher_disconnected_at
        self.fire(monkeypatch, session)
        assert session.teacher_disconnected_at == first

    def test_a_class_the_teacher_ended_is_left_alone(self, monkeypatch):
        """End Class tears the room down, which fires this event right back."""
        from models.online_classes import SESSION_ENDED
        session = self.live_session()
        session.status = SESSION_ENDED
        session.end_reason = "teacher"
        self.fire(monkeypatch, session)
        assert session.status == SESSION_ENDED
        assert session.end_reason == "teacher"

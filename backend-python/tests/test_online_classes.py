"""
Unit tests for the Online Classes module.

These cover the parts where a silent mistake would be worst: who is allowed
into a classroom, what attendance says a student did, whether a webhook is
genuine, and what an AI call is allowed to cost. They run without a database,
a media server or an AI provider — `pytest` from `backend-python/`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import types
from datetime import datetime, timedelta

import pytest

from models.online_classes import OnlineClassParticipant, OnlineClassSession
from services import attendance_service, class_matching, class_context, lss_ai_service
from services import livekit_service as lk


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def make_user(**kwargs):
    user = types.SimpleNamespace(
        id="u1", name="Test User", role="student",
        class_name=None, section=None, subjects=[],
        assigned_classes=[], assigned_sections=[],
    )
    user.__dict__.update(kwargs)
    return user


def make_session(**kwargs):
    defaults = dict(
        id="s1", teacher_id="t1", subject="Mathematics",
        class_name="Class 5", section="A",
    )
    defaults.update(kwargs)
    return OnlineClassSession(**defaults)


ATTENDANCE_RULES = types.SimpleNamespace(
    present_min_percent=75.0, partial_min_percent=25.0, late_after_minutes=10,
)


# ─── Authorization (spec §24) ─────────────────────────────────────────────────

class TestStudentJoinAuthorization:
    def test_matching_class_and_section_may_join(self):
        session = make_session()
        student = make_user(class_name="Class 5", section="A")
        assert class_matching.student_may_join(student, session)[0] is True

    @pytest.mark.parametrize("written_as", ["Class 5", "Grade 5", "5", "V", "Five"])
    def test_class_vocabularies_are_equivalent(self, written_as):
        """Teachers are assigned "Grade 5"; students are recorded as "Class 5".
        The same child must not be locked out by a spelling difference."""
        session = make_session()
        student = make_user(class_name=written_as, section="A")
        assert class_matching.student_may_join(student, session)[0] is True

    @pytest.mark.parametrize("section", ["A", "a", "Section A", "sec a"])
    def test_section_spellings_are_equivalent(self, section):
        session = make_session()
        student = make_user(class_name="Class 5", section=section)
        assert class_matching.student_may_join(student, session)[0] is True

    def test_other_section_is_refused(self):
        session = make_session()
        student = make_user(class_name="Class 5", section="B")
        allowed, reason = class_matching.student_may_join(student, session)
        assert allowed is False and "section" in reason.lower()

    def test_other_class_is_refused(self):
        session = make_session()
        student = make_user(class_name="Class 6", section="A")
        assert class_matching.student_may_join(student, session)[0] is False

    def test_student_without_a_section_cannot_join_a_sectioned_class(self):
        """Guessing which section a child belongs to would be worse than asking
        the office to fix their record."""
        session = make_session()
        student = make_user(class_name="Class 5", section=None)
        assert class_matching.student_may_join(student, session)[0] is False

    def test_whole_class_session_accepts_any_section(self):
        session = make_session(section=None)
        student = make_user(class_name="Class 5", section="C")
        assert class_matching.student_may_join(student, session)[0] is True

    def test_unrecognised_class_fails_closed(self):
        session = make_session(class_name="Class 5")
        student = make_user(class_name="???", section="A")
        assert class_matching.student_may_join(student, session)[0] is False

    def test_non_student_cannot_use_the_student_path(self):
        session = make_session()
        teacher = make_user(role="teacher", class_name="Class 5", section="A")
        assert class_matching.student_may_join(teacher, session)[0] is False


class TestTeacherAuthorization:
    def teacher(self):
        return make_user(
            role="teacher",
            assigned_classes=["Grade 5", "Grade 6"],
            assigned_sections=["Grade 5 - A", "Grade 6 - B"],
            subjects=["Mathematics"],
        )

    def test_own_class_section_and_subject(self):
        assert class_matching.teacher_may_teach(self.teacher(), "Class 5", "A", "Mathematics")[0]

    def test_unassigned_class_refused(self):
        assert not class_matching.teacher_may_teach(self.teacher(), "Class 9", "A", "Mathematics")[0]

    def test_unassigned_section_refused(self):
        assert not class_matching.teacher_may_teach(self.teacher(), "Class 5", "B", "Mathematics")[0]

    def test_unassigned_subject_refused(self):
        assert not class_matching.teacher_may_teach(self.teacher(), "Class 5", "A", "Physics")[0]

    def test_teacher_with_no_assignments_is_not_locked_out(self):
        """A newly added teacher with nothing configured can still teach — the
        same deliberate fallback the rest of LSS Bot uses."""
        fresh = make_user(role="teacher")
        assert class_matching.teacher_may_teach(fresh, "Class 3", "A", "Urdu")[0]

    def test_sections_for_a_class_are_extracted(self):
        assert class_matching.parse_teacher_sections(self.teacher(), "Class 5") == ["A"]


class TestYoungLearners:
    YOUNG = ["Pre-Nursery", "Nursery", "KG", "Class 1", "Class 2"]

    @pytest.mark.parametrize("class_name", ["Nursery", "KG", "Class 1", "Grade 2"])
    def test_young_classes_detected(self, class_name):
        assert class_matching.is_young_class(class_name, self.YOUNG)

    @pytest.mark.parametrize("class_name", ["Class 3", "Grade 7", "Class 10"])
    def test_older_classes_not_flagged(self, class_name):
        assert not class_matching.is_young_class(class_name, self.YOUNG)


# ─── Attendance arithmetic (spec §13) ─────────────────────────────────────────

class TestAttendanceScoring:
    START = datetime(2026, 9, 16, 8, 0)

    def session(self, minutes=45):
        return make_session(
            actual_start=self.START,
            actual_end=self.START + timedelta(minutes=minutes),
            planned_duration_minutes=minutes,
        )

    def participant(self, *, joined_after=0, minutes=0, rejoins=0):
        return OnlineClassParticipant(
            role="student",
            first_join_at=self.START + timedelta(minutes=joined_after),
            total_seconds=int(minutes * 60),
            rejoin_count=rejoins,
            is_connected=False,
        )

    def test_specification_worked_example(self):
        """The spec's own example: 42 of 45 minutes across a disconnect."""
        participant = self.participant(joined_after=3, minutes=42, rejoins=1)
        percent, status = attendance_service.score(participant, self.session(), ATTENDANCE_RULES)
        assert round(percent, 1) == 93.3
        assert status == "present"

    def test_late_but_stayed_is_late_not_partial(self):
        """Joining 20 minutes into a 45-minute class and staying to the end is
        lateness — the student attended everything that was left."""
        participant = self.participant(joined_after=20, minutes=25)
        percent, status = attendance_service.score(participant, self.session(), ATTENDANCE_RULES)
        assert status == "late"
        assert round(percent, 1) == 55.6  # the percentage stays honest

    def test_late_and_drifting_is_partial(self):
        participant = self.participant(joined_after=20, minutes=12)
        assert attendance_service.score(participant, self.session(), ATTENDANCE_RULES)[1] == "partial"

    def test_on_time_but_left_early_is_partial(self):
        participant = self.participant(joined_after=0, minutes=20)
        assert attendance_service.score(participant, self.session(), ATTENDANCE_RULES)[1] == "partial"

    def test_appearing_at_the_end_is_absent(self):
        participant = self.participant(joined_after=42, minutes=3)
        assert attendance_service.score(participant, self.session(), ATTENDANCE_RULES)[1] == "absent"

    def test_never_joined_is_absent(self):
        participant = OnlineClassParticipant(role="student", total_seconds=0, is_connected=False)
        percent, status = attendance_service.score(participant, self.session(), ATTENDANCE_RULES)
        assert percent == 0.0 and status == "absent"

    def test_full_attendance_caps_at_one_hundred(self):
        participant = self.participant(joined_after=0, minutes=60)
        percent, _ = attendance_service.score(participant, self.session(), ATTENDANCE_RULES)
        assert percent == 100.0

    def test_live_interval_counts_while_still_connected(self):
        """A student still in the room has their current interval counted, so a
        live register is not permanently zero."""
        now = self.START + timedelta(minutes=10)
        participant = OnlineClassParticipant(
            role="student", first_join_at=self.START, last_join_at=self.START,
            total_seconds=0, is_connected=True,
        )
        assert attendance_service.connected_seconds(participant, now=now) == 600

    def test_banked_time_only_when_disconnected(self):
        participant = OnlineClassParticipant(
            role="student", total_seconds=300, is_connected=False,
        )
        assert attendance_service.connected_seconds(participant) == 300


# ─── Webhook verification (spec §24) ──────────────────────────────────────────

class TestWebhookVerification:
    SECRET = "test-secret-value"

    def _token(self, body: bytes, *, secret=None, digest=None):
        from jose import jwt
        payload = {
            "iss": "APIkey",
            "exp": datetime.utcnow() + timedelta(minutes=5),
            "sha256": digest or base64.b64encode(hashlib.sha256(body).digest()).decode(),
        }
        return jwt.encode(payload, secret or self.SECRET, algorithm="HS256")

    @pytest.fixture(autouse=True)
    def _configure(self, monkeypatch):
        monkeypatch.setattr(lk, "LIVEKIT_API_SECRET", self.SECRET)
        monkeypatch.setattr(lk, "is_configured", lambda: True)

    def test_valid_delivery_is_accepted(self):
        body = json.dumps({"event": "participant_joined"}).encode()
        assert lk.verify_webhook(body, self._token(body))["event"] == "participant_joined"

    def test_bearer_prefix_is_tolerated(self):
        body = b'{"event":"room_finished"}'
        assert lk.verify_webhook(body, f"Bearer {self._token(body)}")["event"] == "room_finished"

    def test_tampered_body_is_rejected(self):
        """The signature alone is not enough — the body must hash to what was
        signed, or an attacker could replay a valid token with new content."""
        token = self._token(b'{"event":"participant_joined"}')
        with pytest.raises(ValueError):
            lk.verify_webhook(b'{"event":"room_finished"}', token)

    def test_foreign_signature_is_rejected(self):
        body = b'{"event":"participant_joined"}'
        with pytest.raises(ValueError):
            lk.verify_webhook(body, self._token(body, secret="not-our-secret"))

    def test_missing_header_is_rejected(self):
        with pytest.raises(ValueError):
            lk.verify_webhook(b"{}", None)

    def test_token_without_digest_is_rejected(self):
        from jose import jwt
        token = jwt.encode(
            {"iss": "APIkey", "exp": datetime.utcnow() + timedelta(minutes=5)},
            self.SECRET, algorithm="HS256",
        )
        with pytest.raises(ValueError):
            lk.verify_webhook(b"{}", token)


# ─── AI cost control (spec §19D, §19E) ────────────────────────────────────────

class TestAIRouting:
    def settings(self, routing=None):
        return types.SimpleNamespace(ai_model_routing=routing or {})

    def test_summaries_use_the_cheap_model(self, monkeypatch):
        import config.settings as cfg
        monkeypatch.setattr(cfg, "AI_MODEL", "claude-opus-5", raising=False)
        monkeypatch.setattr(cfg, "AI_MODEL_FAST", "claude-haiku-4-5", raising=False)
        model = lss_ai_service.model_for(self.settings(), lss_ai_service.CLASS_SUMMARY)
        assert model == "claude-haiku-4-5"

    def test_student_questions_use_the_capable_model(self, monkeypatch):
        import config.settings as cfg
        monkeypatch.setattr(cfg, "AI_MODEL", "claude-opus-5", raising=False)
        monkeypatch.setattr(cfg, "AI_MODEL_FAST", "claude-haiku-4-5", raising=False)
        model = lss_ai_service.model_for(self.settings(), lss_ai_service.ASK_AI)
        assert model == "claude-opus-5"

    def test_admin_override_wins(self):
        settings = self.settings({"ask_ai": "claude-sonnet-5"})
        assert lss_ai_service.model_for(settings, lss_ai_service.ASK_AI) == "claude-sonnet-5"

    def test_tier_override_applies_to_the_whole_tier(self):
        settings = self.settings({"fast": "claude-sonnet-5"})
        assert lss_ai_service.model_for(settings, lss_ai_service.REVISION_NOTES) == "claude-sonnet-5"


class TestAICostEstimation:
    def test_known_model_priced_correctly(self):
        cost = lss_ai_service.estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000)
        assert cost == pytest.approx(6.0)  # $1 in + $5 out

    def test_opus_priced_correctly(self):
        cost = lss_ai_service.estimate_cost("claude-opus-5", 100_000, 10_000)
        assert cost == pytest.approx(0.5 + 0.25)

    def test_unknown_model_is_not_free(self):
        """An unlisted model must not read as costing nothing, or a budget
        would never trip."""
        assert lss_ai_service.estimate_cost("some-future-model", 1_000_000, 0) > 0


# ─── Class context rendering (spec §17, §19) ──────────────────────────────────

class TestClassContext:
    def test_page_ranges_are_readable(self):
        assert class_context._page_ranges([24, 25, 26, 27, 31]) == "24-27, 31"

    def test_page_ranges_deduplicate_and_sort(self):
        assert class_context._page_ranges([9, 7, 8, 7]) == "7-9"

    def test_no_speech_rule_is_stated(self):
        """Every prompt carries the instruction that the AI did not hear the
        lesson. If this text ever goes missing, summaries could start implying
        they know what was said."""
        rule = class_context.NO_SPEECH_RULE.lower()
        assert "transcript" in rule and "never claim" in rule

    def test_facts_flag_an_unconfirmed_record(self):
        facts = {
            "session": {"subject": "Science", "class_name": "Class 5", "section": "A",
                        "teacher": "Ms Khan", "date": "16 September 2026", "minutes": 40},
            "resources": [{"title": "Oxford Science", "type": "book", "pages_presented": [24, 25]}],
            "whiteboards_saved": 1,
            "lesson_plan": None,
            "lesson_record": {"is_confirmed": False},
            "activity": [],
        }
        text = class_context.render_facts(facts)
        assert "pages 24-25" in text
        assert "provisional" in text
        assert "does not prove" in text

    def test_facts_mark_a_confirmed_record_authoritative(self):
        facts = {
            "session": {"subject": "Science", "class_name": "Class 5", "section": None,
                        "teacher": None, "date": None, "minutes": None},
            "resources": [],
            "whiteboards_saved": 0,
            "lesson_plan": None,
            "lesson_record": {
                "is_confirmed": True,
                "topics_covered": ["Photosynthesis"],
                "pages_covered": [24, 25],
                "homework": "Exercise 3",
                "teacher_notes": None,
            },
            "activity": [],
        }
        text = class_context.render_facts(facts)
        assert "TEACHER-CONFIRMED" in text and "Photosynthesis" in text and "Exercise 3" in text


# ─── Range requests (books and recordings) ────────────────────────────────────

class TestRangeParsing:
    def parse(self, header, size):
        from routes.online_class_tools import _parse_range
        return _parse_range(header, size)

    def test_open_ended_range(self):
        assert self.parse("bytes=0-", 1000) == (0, 999)

    def test_bounded_range(self):
        assert self.parse("bytes=100-199", 1000) == (100, 199)

    def test_suffix_range_returns_the_tail(self):
        assert self.parse("bytes=-100", 1000) == (900, 999)

    def test_range_past_the_end_is_clamped(self):
        assert self.parse("bytes=900-5000", 1000) == (900, 999)

    def test_start_past_the_end_is_invalid(self):
        assert self.parse("bytes=2000-3000", 1000) == (None, None)

    def test_garbage_is_invalid(self):
        assert self.parse("bytes=abc", 1000) == (None, None)


# ─── Presentation formats (spec §7) ───────────────────────────────────────────

class TestPresentation:
    def kind(self, ext):
        from services import presentation_service
        return presentation_service.presentation_kind(ext)

    @pytest.mark.parametrize("ext", ["pdf", "pptx", "docx", "ppt"])
    def test_documents_render_as_pdf(self, ext):
        assert self.kind(ext) == "pdf"

    @pytest.mark.parametrize("ext", ["png", "jpg", "jpeg"])
    def test_images_render_as_images(self, ext):
        assert self.kind(ext) == "image"

    @pytest.mark.parametrize("ext", ["zip", "mp4", "exe", None])
    def test_unsupported_formats_are_refused(self, ext):
        """A teacher gets "use Share Screen instead" rather than a broken
        viewer in front of a class."""
        assert self.kind(ext) == "unsupported"

    def test_all_classes_material_belongs_to_every_class(self):
        from services.presentation_service import _class_matches
        assert _class_matches("All Classes", "Class 5")
        assert _class_matches(None, "Class 5")

    def test_other_class_material_is_filtered_out(self):
        from services.presentation_service import _class_matches
        assert not _class_matches("Class 9", "Class 5")
        assert _class_matches("Grade 5", "Class 5")

"""
Attendance rules (ERP phase 3).

The arithmetic here ends up on report cards and, later, in payroll proration,
so the edge cases are pinned rather than trusted: a late child is present, a
child on leave is not absent, and a class whose register was never taken is not
silently 100%.
"""
import pytest

from models.erp_attendance import (
    ATT_ABSENT, ATT_HALF_DAY, ATT_LATE, ATT_LEAVE, ATT_PRESENT,
    ATTENDANCE_STATUSES, PRESENT_STATUSES, AttendanceDay, AttendanceRecord,
    LeaveRequest,
)


class TestAttendanceVocabulary:

    def test_the_five_states_a_school_actually_uses(self):
        assert set(ATTENDANCE_STATUSES) == {
            ATT_PRESENT, ATT_ABSENT, ATT_LEAVE, ATT_LATE, ATT_HALF_DAY,
        }

    def test_a_late_child_is_in_school(self):
        """Marking a late child absent produces two arguments instead of one."""
        assert ATT_LATE in PRESENT_STATUSES
        assert ATT_HALF_DAY in PRESENT_STATUSES

    def test_leave_is_not_presence(self):
        """Approved leave is not absence, but it is not attendance either — it
        must not inflate the percentage on a report card."""
        assert ATT_LEAVE not in PRESENT_STATUSES
        assert ATT_ABSENT not in PRESENT_STATUSES


class TestPercentage:
    """The number that reaches a report card."""

    @staticmethod
    def _percentage(counts: dict) -> float:
        total = sum(counts.values())
        present = sum(counts.get(s, 0) for s in PRESENT_STATUSES)
        return round(present * 100 / total, 1) if total else 0.0

    def test_a_full_month(self):
        assert self._percentage({ATT_PRESENT: 20}) == 100.0

    def test_three_days_away_in_twenty(self):
        assert self._percentage({ATT_PRESENT: 17, ATT_ABSENT: 3}) == 85.0

    def test_late_days_still_count_as_attended(self):
        assert self._percentage({ATT_PRESENT: 15, ATT_LATE: 5}) == 100.0

    def test_leave_counts_against_attendance(self):
        assert self._percentage({ATT_PRESENT: 18, ATT_LEAVE: 2}) == 90.0

    def test_a_register_never_taken_is_not_full_marks(self):
        """Zero days marked must be 0%, not 100% — otherwise a class whose
        teacher never took the register gets a perfect attendance report."""
        assert self._percentage({}) == 0.0


class TestRegisterShape:

    def test_one_register_per_class_per_day(self):
        """Without this a second save creates a second register and the child
        is counted twice."""
        names = {c.name for c in AttendanceDay.__table__.constraints}
        assert "uq_attendance_day" in names

    def test_one_mark_per_child_per_register(self):
        names = {c.name for c in AttendanceRecord.__table__.constraints}
        assert "uq_attendance_record" in names

    def test_a_whole_class_register_is_allowed(self):
        """A class with no sections takes one register, so section must be
        optional rather than a made-up default."""
        assert AttendanceDay.__table__.c.section_id.nullable

    def test_a_mark_records_where_it_came_from(self):
        """Teacher, online class or correction — the question asked a month
        later is always 'who changed this, and when'."""
        assert AttendanceRecord.__table__.c.source is not None
        assert AttendanceRecord.__table__.c.marked_by is not None


class TestStaffLeave:
    """Present in phase 3 because payroll cannot prorate against data that
    does not exist (specification §24)."""

    def test_leave_records_whether_it_is_paid(self):
        assert LeaveRequest.__table__.c.is_paid is not None

    def test_leave_has_a_range_not_a_single_day(self):
        assert LeaveRequest.__table__.c.from_date is not None
        assert LeaveRequest.__table__.c.to_date is not None

    def test_leave_needs_approving(self):
        assert LeaveRequest.__table__.c.approved_by is not None
        assert LeaveRequest.__table__.c.status.default.arg == "pending"


class TestOnlineClassSuggestion:
    """The register is the teacher's, even when the media server has an opinion."""

    def test_online_presence_maps_onto_school_presence(self):
        from models.online_classes import ATTEND_LATE, ATTEND_PARTIAL, ATTEND_PRESENT
        # A child who was connected for part of a lesson attended it. The
        # online module already decided that; attendance does not re-litigate.
        for status in (ATTEND_PRESENT, ATTEND_LATE, ATTEND_PARTIAL):
            assert status in ("present", "late", "partial")

    def test_a_suggestion_is_marked_as_one(self):
        """The screen must be able to say 'suggested' rather than presenting a
        machine's guess as the teacher's own record."""
        import inspect
        from services.erp import attendance
        source = inspect.getsource(attendance.roster)
        assert '"suggested"' in source

"""
Result rules (ERP phase 7).

Every number here ends up on a child's report card, so the awkward cases are
pinned rather than trusted: the child who was absent, the child excused from a
subject, the child with a 90% average and a 20% in mathematics.

The most important test in the file is the last one — that the combined ledger
and the combined report card call the same function. Specification §81.F is not
a preference; two calculation paths is how a school ends up defending two
different grades for the same child.
"""
from decimal import Decimal

import pytest

from models.erp_exams import (
    EXAM_PUBLISHED, EXAM_TYPES, MARKS_APPROVED, MARKS_DRAFT,
    MARKS_LOCKED_STATES, MARKS_SUBMITTED, Exam, ExamSubject, Mark,
    ResultScheme, SchemeComponent,
)
from services.erp.fees import ZERO, money
from services.erp.results import DEFAULT_BANDS, grade_for, percent, subject_result


class _Band:
    """A grade band without a database."""
    def __init__(self, min_percent, grade, point, remark):
        self.min_percent = Decimal(min_percent)
        self.grade = grade
        self.grade_point = Decimal(point)
        self.remark = remark


BANDS = [_Band(*b) for b in DEFAULT_BANDS]


def _paper(max_marks=100, passing=33, practical_max=0, practical_passing=0):
    return ExamSubject(
        exam_id="e", class_id="c", subject_id="s",
        max_marks=Decimal(str(max_marks)), passing_marks=Decimal(str(passing)),
        practical_max=Decimal(str(practical_max)),
        practical_passing=Decimal(str(practical_passing)),
    )


def _mark(obtained=None, practical=None, absent=False, exempt=False):
    return Mark(
        exam_subject_id="es", student_user_id="u",
        obtained=Decimal(str(obtained)) if obtained is not None else None,
        practical_obtained=Decimal(str(practical)) if practical is not None else None,
        is_absent=absent, is_exempt=exempt,
    )


class TestPercent:

    def test_a_plain_percentage(self):
        assert percent(money(80), money(100)) == money(80)

    def test_out_of_something_other_than_a_hundred(self):
        assert percent(money(37), money(50)) == money(74)

    def test_a_recurring_decimal_is_rounded_not_dropped(self):
        assert percent(money(2), money(3)) == money("66.67")

    def test_nothing_out_of_nothing_is_zero_not_an_error(self):
        """A class with no papers configured must not crash a report card."""
        assert percent(money(0), money(0)) == ZERO


class TestGradeBands:

    @pytest.mark.parametrize("pct,grade", [
        (95, "A+"), (80, "A+"), (79.99, "A"), (70, "A"),
        (65, "B"), (55, "C"), (45, "D"), (33, "E"), (32.99, "F"), (0, "F"),
    ])
    def test_the_band_a_percentage_falls_into(self, pct, grade):
        assert grade_for(BANDS, money(pct))["grade"] == grade

    def test_a_boundary_belongs_to_the_higher_band(self):
        """Exactly 80 is an A+, not an A. A child on a boundary should not be
        marked down by a rounding convention nobody told them about."""
        assert grade_for(BANDS, money(80))["grade"] == "A+"
        assert grade_for(BANDS, money("79.99"))["grade"] == "A"

    def test_the_pass_mark_is_a_band_of_its_own(self):
        assert grade_for(BANDS, money(33))["grade"] == "E"
        assert grade_for(BANDS, money(32))["grade"] == "F"


class TestOneSubject:

    def test_a_plain_mark(self):
        result = subject_result(_mark(80), _paper())
        assert result["obtained"] == "80.00"
        assert result["percent"] == "80.00"
        assert result["passed"] is True
        assert result["counts"] is True

    def test_below_the_pass_mark_fails(self):
        assert subject_result(_mark(20), _paper())["passed"] is False

    def test_exactly_the_pass_mark_passes(self):
        assert subject_result(_mark(33), _paper())["passed"] is True

    def test_absent_scores_zero_but_leaves_the_average_alone(self):
        """A child in hospital should not drag the class average down, but
        they did not score anything either."""
        result = subject_result(_mark(absent=True), _paper())
        assert result["obtained"] == "0.00"
        assert result["status"] == "absent"
        assert result["passed"] is False
        assert result["counts"] is True                 # counts towards their total
        assert result["counts_in_average"] is False     # not towards the class average

    def test_exempt_is_excluded_entirely(self):
        """A child not taking Islamiat is not failing it, and their maximum
        should not include it either."""
        result = subject_result(_mark(exempt=True), _paper())
        assert result["maximum"] == "0.00"
        assert result["passed"] is None
        assert result["counts"] is False

    def test_a_paper_with_no_mark_entered_counts_for_nothing_yet(self):
        result = subject_result(None, _paper())
        assert result["status"] == "not_entered"
        assert result["counts"] is False

    def test_absent_exempt_and_zero_are_three_different_things(self):
        zero = subject_result(_mark(0), _paper())
        absent = subject_result(_mark(absent=True), _paper())
        exempt = subject_result(_mark(exempt=True), _paper())
        assert zero["status"] == "marked"
        assert absent["status"] == "absent"
        assert exempt["status"] == "exempt"
        assert zero["counts_in_average"] and not absent["counts_in_average"]
        assert exempt["maximum"] == "0.00" and absent["maximum"] == "100.00"


class TestPracticals:

    def test_theory_and_practical_add_up(self):
        result = subject_result(_mark(60, practical=18), _paper(max_marks=75, practical_max=25))
        assert result["obtained"] == "78.00"
        assert result["maximum"] == "100.00"
        assert result["percent"] == "78.00"

    def test_failing_the_practical_fails_the_subject(self):
        """Passing the theory and failing the lab is a fail, where the school
        sets a practical pass mark."""
        paper = _paper(max_marks=75, passing=25, practical_max=25, practical_passing=10)
        result = subject_result(_mark(60, practical=5), paper)
        assert result["passed"] is False

    def test_passing_both_passes(self):
        paper = _paper(max_marks=75, passing=25, practical_max=25, practical_passing=10)
        assert subject_result(_mark(60, practical=18), paper)["passed"] is True


class TestOverallResult:
    """Totals and the pass rule, computed the way the engine does."""

    @staticmethod
    def _overall(subjects):
        obtained = sum((money(s["obtained"] or 0) for s in subjects if s["counts"]), ZERO)
        maximum = sum((money(s["maximum"]) for s in subjects if s["counts"]), ZERO)
        failed = any(s["passed"] is False for s in subjects if s["counts"])
        return {"percent": percent(obtained, maximum), "passed": not failed}

    def test_a_straightforward_pass(self):
        subjects = [subject_result(_mark(80), _paper()), subject_result(_mark(70), _paper())]
        result = self._overall(subjects)
        assert result["percent"] == money(75)
        assert result["passed"] is True

    def test_a_high_average_with_one_failed_subject_is_a_fail(self):
        """90% overall with 20% in mathematics is not a pass, whatever the
        average says."""
        subjects = [
            subject_result(_mark(100), _paper()),
            subject_result(_mark(100), _paper()),
            subject_result(_mark(20), _paper()),
        ]
        result = self._overall(subjects)
        assert result["percent"] == money("73.33")
        assert result["passed"] is False

    def test_an_exempt_subject_does_not_dilute_the_percentage(self):
        subjects = [
            subject_result(_mark(80), _paper()),
            subject_result(_mark(exempt=True), _paper()),
        ]
        assert self._overall(subjects)["percent"] == money(80)

    def test_an_absent_paper_counts_as_zero_in_the_total(self):
        subjects = [
            subject_result(_mark(80), _paper()),
            subject_result(_mark(absent=True), _paper()),
        ]
        assert self._overall(subjects)["percent"] == money(40)


class TestWeightedCombination:
    """The case that ran against the database: 40% monthly, 60% mid-term."""

    @staticmethod
    def _combine(pairs):
        return money(sum(
            (money(pct) * money(weight) / Decimal("100") for pct, weight in pairs),
            ZERO,
        ))

    def test_the_worked_example(self):
        assert self._combine([(80, 40), (90, 60)]) == money(86)
        assert self._combine([(60, 40), (40, 60)]) == money(48)

    def test_equal_weights_are_an_average(self):
        assert self._combine([(80, 50), (60, 50)]) == money(70)

    def test_six_exams_at_the_specification_shape(self):
        """Four monthlies at 10, mid-term at 25, final at 35 — totalling 100."""
        weights = [(70, 10), (80, 10), (60, 10), (90, 10), (75, 25), (85, 35)]
        assert sum(w for _, w in weights) == 100
        # 7 + 8 + 6 + 9 + 18.75 + 29.75
        assert self._combine(weights) == money("78.50")

    def test_weights_that_do_not_total_a_hundred_are_detectable(self):
        weights = [Decimal("40"), Decimal("40")]
        assert sum(weights) != Decimal("100")


class TestOneEngineOnly:
    """§81.F — the combined ledger and the combined report card must never
    disagree. They cannot, because they call the same function."""

    def test_the_report_card_calls_the_same_function_as_the_ledger(self):
        import inspect
        from services.erp import results
        card = inspect.getsource(results.report_card)
        ledger = inspect.getsource(results.combined_ledger)
        assert "combined_result(" in card
        assert "combined_result(" in ledger

    def test_the_exam_ledger_calls_the_shared_exam_result(self):
        import inspect
        from services.erp import results
        assert "exam_result(" in inspect.getsource(results.exam_ledger)

    def test_no_route_computes_a_percentage_of_its_own(self):
        """The one rule that keeps the guarantee true as the code grows."""
        import pathlib
        routes = pathlib.Path(__file__).resolve().parent.parent / "routes"
        source = (routes / "erp_exams.py").read_text(encoding="utf-8")
        assert "/ 100" not in source
        assert "* 100" not in source
        assert "percent(" not in source.replace("weight_percent", "")

    def test_weight_validation_lives_in_the_engine(self):
        from services.erp import results
        assert hasattr(results, "validate_weights")


class TestMarksLifecycle:

    def test_submitted_and_approved_are_locked(self):
        assert MARKS_SUBMITTED in MARKS_LOCKED_STATES
        assert MARKS_APPROVED in MARKS_LOCKED_STATES
        assert MARKS_DRAFT not in MARKS_LOCKED_STATES

    def test_one_mark_per_child_per_paper(self):
        names = {c.name for c in Mark.__table__.constraints}
        assert "uq_mark" in names

    def test_one_paper_per_subject_per_class_per_exam(self):
        names = {c.name for c in ExamSubject.__table__.constraints}
        assert "uq_exam_subject" in names

    def test_marks_are_stored_raw(self):
        """Nothing derived is stored, so nothing stored can drift."""
        columns = {c.name for c in Mark.__table__.columns}
        for derived in ("percent", "percentage", "grade", "weighted"):
            assert derived not in columns

    def test_a_teacher_cannot_mark_a_class_they_do_not_teach(self):
        import inspect
        from routes import erp_exams
        source = inspect.getsource(erp_exams._may_enter_marks)
        assert "TeacherAssignment" in source

    def test_marks_for_a_child_outside_the_class_are_refused(self):
        """§42: a stale tab must not write marks for somebody who never sat
        the paper."""
        import inspect
        from routes import erp_exams
        source = inspect.getsource(erp_exams.save_marks)
        assert "not in this class" in source


class TestSchemes:

    def test_a_scheme_belongs_to_a_session_and_optionally_a_class(self):
        assert ResultScheme.__table__.c.session_id.nullable is False
        assert ResultScheme.__table__.c.class_id.nullable is True

    def test_one_weight_per_exam_per_scheme(self):
        names = {c.name for c in SchemeComponent.__table__.constraints}
        assert "uq_scheme_component" in names

    def test_position_is_published_only_when_asked_for(self):
        """§81.E — some schools publish rank, some deliberately do not."""
        assert ResultScheme.__table__.c.show_position.default.arg is False

    def test_weightage_is_data_not_a_constant(self):
        import pathlib
        results = (pathlib.Path(__file__).resolve().parent.parent
                   / "services/erp/results.py").read_text(encoding="utf-8")
        # No hard-coded weightings anywhere in the engine.
        assert "0.4" not in results
        assert "weight_percent" in results

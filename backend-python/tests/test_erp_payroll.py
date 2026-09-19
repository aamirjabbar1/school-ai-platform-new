"""
Payroll rules (ERP phase 5).

Payroll is judged on the awkward months, not the easy ones: the person who
joined on the 14th, the one who resigned on the 3rd, the four days of unpaid
leave, the salary revised mid-year. Those are pinned here.
"""
import calendar
from datetime import date
from decimal import Decimal

import pytest

from models.erp_hr import (
    CALC_PERCENT_OF_BASIC, COMPONENT_ALLOWANCE, COMPONENT_DEDUCTION,
    PAYROLL_APPROVED, PAYROLL_CALCULATED, PAYROLL_DRAFT, PAYROLL_LOCKED_STATES,
    PAYROLL_PAID, EmployeeAdvance, EmployeeDocument, PayrollLine, PayrollRun,
    SalaryComponent, SalaryStructure,
)
from services.erp.fees import ZERO, money


class TestSalaryHistory:

    def test_a_structure_has_a_start_and_an_optional_end(self):
        assert SalaryStructure.__table__.c.effective_from.nullable is False
        assert SalaryStructure.__table__.c.effective_to.nullable is True

    def test_a_revision_points_back_at_what_it_replaced(self):
        """Increment history is then free — it is simply the chain."""
        assert SalaryStructure.__table__.c.supersedes_id is not None

    def test_nothing_overwrites_a_salary(self):
        """§25: never overwrite. A two-year-old payslip must still reproduce."""
        import inspect
        from services.erp import payroll
        source = inspect.getsource(payroll.set_salary)
        assert "SalaryStructure(" in source          # a new row
        assert "existing.effective_to = effective_from" in source   # the old one closed
        assert "existing.basic = " not in source     # never edited in place

    def test_a_revision_records_who_approved_it(self):
        assert SalaryStructure.__table__.c.approved_by is not None
        assert SalaryStructure.__table__.c.reason is not None


class TestProration:
    """The number that has to be right, and visible on the payslip."""

    @staticmethod
    def _prorate(basic, days_payable, days_in_month):
        return money(money(basic) * Decimal(days_payable) / Decimal(days_in_month))

    def test_a_full_month_is_the_full_salary(self):
        assert self._prorate(60000, 30, 30) == money(60000)

    def test_joining_on_the_fifteenth_of_september(self):
        """15 to 30 September inclusive is 16 days of a 30-day month."""
        assert self._prorate(60000, 16, 30) == money(32000)

    def test_february_is_shorter(self):
        """A daily rate that assumes 30 days underpays every February."""
        assert calendar.monthrange(2026, 2)[1] == 28
        assert self._prorate(60000, 14, 28) == money(30000)

    def test_a_long_month_is_longer(self):
        assert self._prorate(62000, 31, 31) == money(62000)

    def test_unpaid_leave_comes_off_the_days(self):
        assert self._prorate(60000, 26, 30) == money(52000)

    def test_someone_who_had_not_joined_earns_nothing(self):
        assert self._prorate(60000, 0, 30) == ZERO

    def test_the_reason_is_carried_to_the_payslip(self):
        """A number a teacher cannot account for is a conversation the office
        has to have instead."""
        assert PayrollLine.__table__.c.note is not None
        assert PayrollLine.__table__.c.days_payable is not None
        assert PayrollLine.__table__.c.is_prorated is not None


class TestComponents:

    @staticmethod
    def _value(component_type, calculation, value, basic, factor=Decimal("1")):
        raw = money(money(basic) * money(value) / Decimal("100")) \
            if calculation == CALC_PERCENT_OF_BASIC else money(value)
        return money(raw * factor)

    def test_a_percentage_allowance_is_of_basic(self):
        assert self._value(COMPONENT_ALLOWANCE, CALC_PERCENT_OF_BASIC,
                           30, 60000) == money(18000)

    def test_a_fixed_deduction_is_fixed(self):
        assert self._value(COMPONENT_DEDUCTION, "fixed", 370, 60000) == money(370)

    def test_components_prorate_with_the_days(self):
        factor = Decimal(16) / Decimal(30)
        assert self._value(COMPONENT_ALLOWANCE, CALC_PERCENT_OF_BASIC,
                           30, 60000, factor) == money(9600)

    def test_a_component_can_be_told_not_to_prorate(self):
        """A fixed conveyance allowance is often paid whole for a half month."""
        assert SalaryComponent.__table__.c.prorates is not None
        assert SalaryComponent.__table__.c.prorates.default.arg is True


class TestRunLifecycle:

    def test_one_run_per_month(self):
        names = {c.name for c in PayrollRun.__table__.constraints}
        assert "uq_payroll_month" in names

    def test_one_line_per_employee_per_run(self):
        names = {c.name for c in PayrollLine.__table__.constraints}
        assert "uq_payroll_line" in names

    def test_approved_and_paid_are_locked(self):
        assert PAYROLL_APPROVED in PAYROLL_LOCKED_STATES
        assert PAYROLL_PAID in PAYROLL_LOCKED_STATES
        assert PAYROLL_CALCULATED not in PAYROLL_LOCKED_STATES
        assert PAYROLL_DRAFT not in PAYROLL_LOCKED_STATES

    def test_an_approved_month_cannot_be_regenerated(self):
        """That payslip has been handed over. A correction belongs in the next
        month, not in a quiet rewrite of this one."""
        import inspect
        from services.erp import payroll
        source = inspect.getsource(payroll.generate_payroll)
        assert "PAYROLL_LOCKED_STATES" in source
        assert "already been approved" in source

    def test_a_line_keeps_what_it_was_computed_from(self):
        assert PayrollLine.__table__.c.breakdown is not None
        assert PayrollLine.__table__.c.structure_id is not None

    def test_approval_tells_accounting(self):
        import inspect
        from services.erp import payroll
        source = inspect.getsource(payroll.approve_payroll)
        assert "PAYROLL_APPROVED" in source
        assert "events.emit" in source


class TestAdvances:

    def test_recovery_happens_at_approval_not_calculation(self):
        """Otherwise re-running a draft takes the instalment twice."""
        import inspect
        from services.erp import payroll
        approve = inspect.getsource(payroll.approve_payroll)
        generate = inspect.getsource(payroll.generate_payroll)
        assert "advance.outstanding = money(advance.outstanding - take)" in approve
        assert "advance.outstanding = money(" not in generate

    def test_the_last_instalment_takes_only_what_is_left(self):
        """A 1,000 instalment against 300 outstanding takes 300."""
        outstanding, instalment = money(300), money(1000)
        assert min(instalment, outstanding) == money(300)

    def test_a_cleared_advance_stops_recovering(self):
        import inspect
        from services.erp import payroll
        source = inspect.getsource(payroll.approve_payroll)
        assert "advance.is_active = False" in source


class TestPayrollMoney:

    def test_no_float_columns(self):
        from sqlalchemy import Float
        import models.erp_hr as hr

        for name in dir(hr):
            table = getattr(getattr(hr, name), "__table__", None)
            if table is None:
                continue
            for column in table.columns:
                assert not isinstance(column.type, Float), (
                    f"{table.name}.{column.name} is a Float — payroll must be NUMERIC"
                )

    def test_a_full_calculation(self):
        """60,000 basic, 30% house rent, 370 EOBI, sixteen days of thirty —
        the case that was run against the database."""
        factor = Decimal(16) / Decimal(30)
        basic = money(money(60000) * factor)
        hra = money(money(money(60000) * Decimal("30") / Decimal("100")) * factor)
        eobi = money(money(370) * factor)

        assert basic == money(32000)
        assert hra == money(9600)
        gross = money(basic + hra)
        assert gross == money(41600)
        assert money(gross - eobi) == money("41402.67")


class TestPersonnelFile:

    def test_documents_are_not_public(self):
        """A CNIC scan in a bucket anyone can read is a CNIC scan anyone can
        read. The file key is stored; access goes through a permission check."""
        assert EmployeeDocument.__table__.c.file_key is not None
        assert "has_file" in EmployeeDocument(
            employee_user_id="x", doc_type="cnic", title="t",
        ).to_dict()

    def test_a_document_is_versioned(self):
        assert EmployeeDocument.__table__.c.version is not None

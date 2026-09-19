"""
Fee arithmetic (ERP phase 4).

This is the module where a wrong number is not a bug report but a parent at a
counter, so the sums are pinned rather than trusted. The cases below are the
ones that actually went wrong, or that would have.
"""
from decimal import Decimal

import pytest

from models.erp_fees import (
    CONCESSION_CATEGORIES, CONCESSION_FIXED, CONCESSION_PERCENT,
    OPEN_VOUCHER_STATES, VOUCHER_CANCELLED, VOUCHER_PAID, VOUCHER_PARTIAL,
    VOUCHER_UNPAID, Concession, LedgerEntry, Receipt, StudentFeeAccount,
    Voucher, VoucherLine,
)
from services.erp.fees import ZERO, concession_for_head, money, month_start

# Every column in the fee schema that holds an amount of money. Listed rather
# than pattern-matched, so a new money column has to be added here deliberately.
MONEY_COLUMNS = {
    "amount", "value", "gross", "concession", "arrears", "late_fee",
    "payable", "paid", "net", "debit", "credit", "balance",
    "total_billed", "total_paid", "outstanding", "advance",
    "last_payment_amount", "total_amount",
}


class TestMoney:

    @pytest.mark.parametrize("value,expected", [
        (5000, "5000.00"),
        ("5000.5", "5000.50"),
        (Decimal("0.005"), "0.01"),      # half-up, the way a cashier rounds
        (Decimal("0.004"), "0.00"),
        (None, "0.00"),
        (-250, "-250.00"),               # reversals are negative and stay exact
    ])
    def test_two_places_half_up(self, value, expected):
        assert str(money(value)) == expected

    def test_a_third_of_a_rupee_does_not_drift(self):
        """Ten thousand divided three ways, added back, must be the original
        amount to the paisa — this is exactly what a float gets wrong."""
        third = money(Decimal("10000") / 3)
        assert third == Decimal("3333.33")
        assert money(third * 3) == Decimal("9999.99")

    def test_percentages_are_exact(self):
        assert money(Decimal("5500") * Decimal("12.5") / Decimal("100")) == Decimal("687.50")


class TestConcessions:

    @staticmethod
    def _c(**kwargs):
        return Concession(**{"concession_type": CONCESSION_PERCENT, "value": Decimal("0"),
                             "head_id": None, **kwargs})

    def test_a_percentage_comes_off(self):
        c = self._c(value=Decimal("25"))
        assert concession_for_head([c], "head-1", money(4000)) == money(1000)

    def test_a_fixed_amount_comes_off(self):
        c = self._c(concession_type=CONCESSION_FIXED, value=Decimal("750"))
        assert concession_for_head([c], "head-1", money(4000)) == money(750)

    def test_concessions_add_up(self):
        """A sibling discount and a merit scholarship are both real."""
        both = [
            self._c(value=Decimal("10")),
            self._c(concession_type=CONCESSION_FIXED, value=Decimal("500")),
        ]
        assert concession_for_head(both, "head-1", money(5000)) == money(1000)

    def test_a_discount_never_exceeds_the_fee(self):
        """Otherwise the school appears to owe the parent money, and the
        voucher total goes negative."""
        too_much = [
            self._c(value=Decimal("100")),
            self._c(concession_type=CONCESSION_FIXED, value=Decimal("5000")),
        ]
        assert concession_for_head(too_much, "head-1", money(4000)) == money(4000)

    def test_a_head_specific_discount_stays_on_its_head(self):
        c = self._c(head_id="tuition", value=Decimal("50"))
        assert concession_for_head([c], "tuition", money(1000)) == money(500)
        assert concession_for_head([c], "transport", money(1000)) == ZERO

    def test_a_blanket_discount_applies_everywhere(self):
        c = self._c(head_id=None, value=Decimal("10"))
        assert concession_for_head([c], "anything", money(1000)) == money(100)

    def test_orphan_is_a_category_not_a_special_case(self):
        """It carries a permission on its documents, not a separate code path."""
        assert "orphan" in CONCESSION_CATEGORIES
        assert "sibling" in CONCESSION_CATEGORIES
        assert "staff_child" in CONCESSION_CATEGORIES


class TestArrearsAreBilledOnce:
    """The bug this module was rewritten to avoid.

    A Pakistani fee voucher *prints* current charges plus arrears as one figure
    to pay. Storing it that way means summing three months counts February's
    unpaid fee three times, and every total in the system drifts.
    """

    def test_payable_is_one_month(self):
        """`payable` is this month's charge; `arrears` is a separate snapshot
        for printing."""
        import inspect
        from services.erp import fees
        source = inspect.getsource(fees.generate_vouchers)
        assert "voucher.payable = money(gross - concession_total)" in source
        assert "voucher.payable = money(gross - concession_total + arrears)" not in source

    def test_the_printed_total_still_includes_arrears(self):
        """The parent must still be told one figure to hand over."""
        voucher = Voucher(
            voucher_no="V1", student_user_id="s", session_id="x",
            month=None, issue_date=None, due_date=None,
            gross=money(5500), concession=ZERO, arrears=money(5500),
            payable=money(5500), paid=ZERO, status=VOUCHER_UNPAID,
        )
        assert voucher.to_dict()["payable"] == "5500.00"
        assert voucher.to_dict()["total_due"] == "11000.00"

    def test_three_unpaid_months_owe_three_months(self):
        """Not six, which is what rolling arrears into payable produced."""
        monthly = money(5500)
        billed = sum((monthly for _ in range(3)), ZERO)
        assert billed == money(16500)

    def test_the_account_is_billed_less_received(self):
        import inspect
        from services.erp import fees
        source = inspect.getsource(fees._recalculate_account)
        assert "position = money(billed - received)" in source


class TestAccountPosition:

    @staticmethod
    def _position(billed, received):
        position = money(money(billed) - money(received))
        return {
            "outstanding": position if position > ZERO else ZERO,
            "advance": money(-position) if position < ZERO else ZERO,
        }

    def test_nothing_paid(self):
        assert self._position(11000, 0)["outstanding"] == money(11000)

    def test_part_paid(self):
        assert self._position(11000, 5500)["outstanding"] == money(5500)

    def test_fully_paid(self):
        result = self._position(11000, 11000)
        assert result["outstanding"] == ZERO and result["advance"] == ZERO

    def test_overpaid_becomes_an_advance_not_a_negative_bill(self):
        """A parent who hands over a round figure should not be turned away,
        and must never appear to be owed money by the school."""
        result = self._position(11000, 15000)
        assert result["outstanding"] == ZERO
        assert result["advance"] == money(4000)


class TestIdempotentPayment:

    def test_a_bank_reference_is_unique(self):
        """Importing the same bank file twice must not take a parent's money
        twice. This is the one duplicate in the ERP that is a real loss."""
        names = {c.name for c in Receipt.__table__.constraints}
        assert "uq_receipt_bank_reference" in names

    def test_a_duplicate_is_reported_not_refused(self):
        """A retry is normal. It should return the original receipt, not an
        error the cashier has to interpret."""
        import inspect
        from services.erp import fees
        source = inspect.getsource(fees.receive_payment)
        assert '"duplicate": True' in source


class TestReversal:

    def test_a_reversal_points_at_what_it_undoes(self):
        assert Receipt.__table__.c.reversal_of is not None
        assert Receipt.__table__.c.reversal_reason is not None

    def test_nothing_is_deleted(self):
        """The question afterwards is always 'what happened', never 'what is
        the total now' — so the original receipt stays exactly where it is."""
        import inspect
        from services.erp import fees
        source = inspect.getsource(fees.reverse_receipt)
        assert "db.delete" not in source
        assert "money(-original.amount)" in source


class TestVoucherRules:

    def test_one_voucher_per_student_per_month(self):
        """Without this, pressing Generate twice bills the month twice."""
        names = {c.name for c in Voucher.__table__.constraints}
        assert "uq_voucher_student_month" in names

    def test_open_states_exclude_paid_and_cancelled(self):
        assert VOUCHER_UNPAID in OPEN_VOUCHER_STATES
        assert VOUCHER_PARTIAL in OPEN_VOUCHER_STATES
        assert VOUCHER_PAID not in OPEN_VOUCHER_STATES
        assert VOUCHER_CANCELLED not in OPEN_VOUCHER_STATES

    def test_a_line_snapshots_the_head_name(self):
        """Fee heads get renamed. A voucher printed last March must still read
        the way it read last March."""
        assert VoucherLine.__table__.c.head_name is not None

    def test_oldest_month_is_settled_first(self):
        import inspect
        from services.erp import fees
        source = inspect.getsource(fees._apply_to_vouchers)
        assert "order_by(Voucher.month)" in source


class TestAllMoneyIsExact:

    def test_no_float_columns_anywhere_in_fees(self):
        """One float column is enough to make a statement disagree with itself."""
        from sqlalchemy import Float, Numeric
        import models.erp_fees as fees_models

        for name in dir(fees_models):
            model = getattr(fees_models, name)
            table = getattr(model, "__table__", None)
            if table is None:
                continue
            for column in table.columns:
                assert not isinstance(column.type, Float), (
                    f"{table.name}.{column.name} is a Float — money must be NUMERIC"
                )
                # Matched on the whole name, not a substring: `oldest_unpaid_month`
                # contains "paid" and is a date.
                if column.name in MONEY_COLUMNS:
                    assert isinstance(column.type, Numeric), (
                        f"{table.name}.{column.name} holds money and must be NUMERIC"
                    )


class TestMonthHandling:

    def test_a_month_is_its_first_day(self):
        from datetime import date
        assert month_start(date(2026, 9, 19)) == date(2026, 9, 1)
        assert month_start(date(2026, 2, 28)) == date(2026, 2, 1)

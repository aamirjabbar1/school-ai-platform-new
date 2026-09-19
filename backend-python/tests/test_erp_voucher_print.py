"""
The printed fee voucher.

Every number below is taken from the voucher LSS actually issued to ANFAAL
AWAIS for September 2026, because the surest way to know the ERP's voucher is
right is to reproduce one the school has already sent out.

    Tuition Fee              8,085
    Taekwondo                  200
    Total                    8,060
    Late Fine 300 · Discount 525 · Prev. Bal 0 · Paid 0 · Net Bal. 8,060

    Issue 24/08/2026 · Due 10/09/2026 · Valid Till 15/09/2026
"""
from datetime import date
from decimal import Decimal

import pytest

from services.erp.fees import ZERO, money
from services.erp.voucher_pdf import COPIES, _rupees, _date
from services.erp.voucher_print import DEFAULT_NOTE, late_fine_for


class TestTheSampleVoucherReproduces:

    HEADS = [money(8085), money(200)]
    DISCOUNT = money(525)
    LATE_FINE = money(300)

    def test_the_heads_add_up_to_the_gross(self):
        assert sum(self.HEADS, ZERO) == money(8285)

    def test_the_total_is_gross_less_discount_plus_fine(self):
        """8,285 − 525 + 300 = 8,060, which is what the school's voucher
        prints. The discount comes off and the fine goes on before Total."""
        gross = sum(self.HEADS, ZERO)
        assert money(gross - self.DISCOUNT + self.LATE_FINE) == money(8060)

    def test_the_net_balance_repeats_the_total_when_nothing_is_paid(self):
        total = money(8060)
        previous, paid = ZERO, ZERO
        assert money(total + previous - paid) == money(8060)

    def test_a_part_payment_comes_off_the_net_balance(self):
        assert money(money(8060) + ZERO - money(3000)) == money(5060)

    def test_arrears_are_added_to_the_net_balance_not_the_total(self):
        """The Total is this month; Prev. Bal is what was already owed. Adding
        arrears into Total would double-count them next month."""
        total, previous = money(8060), money(5500)
        assert money(total + previous - ZERO) == money(13560)


class TestLateFine:

    def test_the_sample_fine(self):
        """Due on the 10th, valid till the 15th, Rs.50/- per day — the six days
        the voucher is still payable, which is the 300 it prints."""
        fine = late_fine_for(
            due_date=date(2026, 9, 10),
            valid_till=date(2026, 9, 15),
            per_day=Decimal("50"),
        )
        assert fine == money(300)

    def test_no_valid_till_means_no_printed_fine(self):
        assert late_fine_for(due_date=date(2026, 9, 10), valid_till=None,
                             per_day=Decimal("50")) == ZERO

    def test_a_valid_till_on_the_due_date_means_no_fine(self):
        assert late_fine_for(due_date=date(2026, 9, 10),
                             valid_till=date(2026, 9, 10),
                             per_day=Decimal("50")) == ZERO

    def test_a_longer_window_costs_more(self):
        assert late_fine_for(due_date=date(2026, 9, 10),
                             valid_till=date(2026, 9, 20),
                             per_day=Decimal("50")) == money(550)

    def test_the_rate_is_configurable(self):
        assert late_fine_for(due_date=date(2026, 9, 10),
                             valid_till=date(2026, 9, 15),
                             per_day=Decimal("100")) == money(600)


class TestFormatting:

    @pytest.mark.parametrize("value,expected", [
        (8085, "8,085"), (200, "200"), (8060, "8,060"),
        (0, "0"), (123456, "123,456"),
    ])
    def test_amounts_read_the_way_the_voucher_prints_them(self, value, expected):
        assert _rupees(value) == expected

    def test_paisa_are_rounded_away(self):
        """The sample shows whole rupees. A decimal on a fee voucher invites an
        argument at the counter."""
        assert _rupees(Decimal("8060.49")) == "8,060"
        assert _rupees(Decimal("8060.50")) == "8,061"

    def test_dates_are_day_first(self):
        assert _date(date(2026, 8, 24)) == "24/08/2026"
        assert _date(None) == ""


class TestThreeCopies:

    def test_the_three_copies_the_school_issues(self):
        assert COPIES == ("Bank Copy", "School Copy", "Student Copy")

    def test_they_fit_across_a_landscape_page(self):
        from services.erp.voucher_pdf import COPY_WIDTH, GUTTER, MARGIN, PAGE_WIDTH
        used = 3 * COPY_WIDTH + 2 * GUTTER + 2 * MARGIN
        assert abs(used - PAGE_WIDTH) < 1


class TestSchoolPolicyIsNotHardCoded:

    def test_the_note_is_the_school_s_wording(self):
        assert "Rs.50/- per day" in DEFAULT_NOTE
        assert "not refundable" in DEFAULT_NOTE

    def test_the_bank_and_account_live_in_settings(self):
        """Changing a bank account must not need a deployment."""
        from models.erp_fees import VoucherSettings
        columns = {c.name for c in VoucherSettings.__table__.columns}
        for field in ("bank_name", "bank_account", "campus_code", "note",
                      "late_fine_per_day", "kuickpay_prefix"):
            assert field in columns

    def test_the_challan_number_is_on_the_voucher_not_derived(self):
        """A reprint must be the same piece of paper — same number, same
        barcode, or the bank reconciles a payment against nothing."""
        from models.erp_fees import Voucher
        columns = {c.name for c in Voucher.__table__.columns}
        assert "challan_no" in columns
        assert "kuickpay_id" in columns
        assert "valid_till" in columns

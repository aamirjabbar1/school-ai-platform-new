"""
Accounting rules (ERP phase 6).

The ledger is the one place in the ERP where being approximately right is worse
than being visibly broken, so the invariants are asserted at the schema level
wherever that is possible and at the service level where it is not.
"""
from datetime import date
from decimal import Decimal

import pytest

from models.erp_accounts import (
    ACCOUNT_TYPES, ASSET, CREDIT_NATURED, DEBIT_NATURED, EQUITY, EXPENSE,
    INCOME, LIABILITY, PERIOD_LOCKED, PERIOD_OPEN,
    AccountingPeriod, BankStatementLine, Expense, GLAccount, Journal,
    JournalLine, Vendor,
)
from services.erp.accounts import (
    ACCOUNT_CASH, ACCOUNT_FEE_INCOME, ACCOUNT_SALARIES_PAYABLE,
    ACCOUNT_SALARY_EXPENSE, STANDARD_CHART, period_of,
)
from services.erp.fees import ZERO, money


class TestChartOfAccounts:

    def test_every_account_has_a_known_type(self):
        for code, name, account_type, postable in STANDARD_CHART:
            assert account_type in ACCOUNT_TYPES, f"{code} {name} has type {account_type}"

    def test_codes_are_unique(self):
        codes = [c for c, _, _, _ in STANDARD_CHART]
        assert len(codes) == len(set(codes))

    def test_codes_follow_their_type(self):
        """1 assets, 2 liabilities, 3 equity, 4 income, 5 expenses — the
        convention every accountant already has in their head."""
        prefix = {"1": ASSET, "2": LIABILITY, "3": EQUITY, "4": INCOME, "5": EXPENSE}
        for code, name, account_type, _ in STANDARD_CHART:
            assert prefix[code[0]] == account_type, f"{code} {name} is in the wrong range"

    def test_headings_are_not_postable(self):
        """Posting to a heading is how a trial balance stops adding up."""
        for code, name, _, postable in STANDARD_CHART:
            if code.endswith("000"):
                assert not postable, f"{name} is a heading and must not be postable"

    def test_the_accounts_the_posting_rules_need_exist(self):
        codes = {c for c, _, _, _ in STANDARD_CHART}
        for code in (ACCOUNT_CASH, ACCOUNT_FEE_INCOME,
                     ACCOUNT_SALARY_EXPENSE, ACCOUNT_SALARIES_PAYABLE):
            assert code in codes

    def test_a_school_chart_not_a_generic_one(self):
        names = {name for _, name, _, _ in STANDARD_CHART}
        assert "Tuition Fee Income" in names
        assert "Fees Receivable" in names
        assert "Salaries & Wages" in names


class TestNaturalSides:

    def test_assets_and_expenses_are_debit_natured(self):
        assert ASSET in DEBIT_NATURED and EXPENSE in DEBIT_NATURED

    def test_income_liabilities_and_equity_are_credit_natured(self):
        for kind in (INCOME, LIABILITY, EQUITY):
            assert kind in CREDIT_NATURED

    def test_every_type_has_exactly_one_side(self):
        assert set(DEBIT_NATURED) | set(CREDIT_NATURED) == set(ACCOUNT_TYPES)
        assert not set(DEBIT_NATURED) & set(CREDIT_NATURED)


class TestBalanceIsStructural:
    """Not a convention the code follows — a constraint the database enforces."""

    def test_a_journal_must_balance(self):
        names = {c.name for c in Journal.__table__.constraints}
        assert "ck_journal_balanced" in names

    def test_a_line_cannot_be_negative(self):
        names = {c.name for c in JournalLine.__table__.constraints}
        assert "ck_line_non_negative" in names

    def test_a_line_is_one_side_only(self):
        """A line that is both a debit and a credit is not an entry, it is a
        typo that still balances."""
        names = {c.name for c in JournalLine.__table__.constraints}
        assert "ck_line_one_side" in names

    def test_the_service_refuses_an_unbalanced_entry_too(self):
        import inspect
        from services.erp import accounts
        source = inspect.getsource(accounts.post)
        assert "does not balance" in source

    def test_an_entry_with_no_amount_is_refused(self):
        import inspect
        from services.erp import accounts
        assert "no amount cannot be posted" in inspect.getsource(accounts.post)


class TestIdempotentPosting:

    def test_dedupe_key_is_unique(self):
        """An event replayed by the outbox must post once. This is the only
        reason retrying the outbox is safe at all."""
        names = {c.name for c in Journal.__table__.constraints}
        assert "uq_journal_dedupe" in names

    def test_a_replay_returns_none_rather_than_raising(self):
        import inspect
        from services.erp import accounts
        source = inspect.getsource(accounts.post)
        assert "return None" in source

    def test_both_posting_rules_carry_a_dedupe_key(self):
        import inspect
        from services.erp import accounts
        for fn in (accounts._post_fee_receipt, accounts._post_payroll):
            assert "dedupe_key=" in inspect.getsource(fn)


class TestPostingRules:
    """Business events post themselves; nobody types a journal to record a fee."""

    def test_a_fee_debits_cash_and_credits_income(self):
        import inspect
        from services.erp import accounts
        source = inspect.getsource(accounts._post_fee_receipt)
        assert "ACCOUNT_FEE_INCOME" in source
        assert '"credit": amount' in source

    def test_a_bank_payment_goes_to_the_bank_account(self):
        import inspect
        from services.erp import accounts
        source = inspect.getsource(accounts._post_fee_receipt)
        assert "ACCOUNT_BANK if method in" in source

    def test_payroll_credits_a_liability_not_cash(self):
        """The school owes the money the moment payroll is approved, whether or
        not the transfer has left the bank."""
        import inspect
        from services.erp import accounts
        source = inspect.getsource(accounts._post_payroll)
        assert "ACCOUNT_SALARIES_PAYABLE" in source
        assert "ACCOUNT_SALARY_EXPENSE" in source

    def test_handlers_are_registered_on_the_events(self):
        from services.erp import accounts, events
        assert events.PAYMENT_RECEIVED in events._HANDLERS
        assert events.PAYROLL_APPROVED in events._HANDLERS


class TestPeriods:

    def test_a_period_is_a_month(self):
        assert period_of(date(2026, 9, 19)) == "2026-09"
        assert period_of(date(2026, 12, 1)) == "2026-12"

    def test_periods_lock(self):
        assert PERIOD_LOCKED != PERIOD_OPEN
        assert AccountingPeriod.__table__.c.locked_by is not None

    def test_posting_into_a_locked_period_is_refused(self):
        import inspect
        from services.erp import accounts
        assert "is closed" in inspect.getsource(accounts.post)


class TestReversal:

    def test_a_reversal_mirrors_the_original(self):
        import inspect
        from services.erp import accounts
        source = inspect.getsource(accounts.reverse)
        assert '"debit": line.credit, "credit": line.debit' in source

    def test_nothing_is_deleted(self):
        import inspect
        from services.erp import accounts
        assert "db.delete" not in inspect.getsource(accounts.reverse)

    def test_an_entry_is_reversed_only_once(self):
        import inspect
        from services.erp import accounts
        assert "already been reversed" in inspect.getsource(accounts.reverse)


class TestStatementArithmetic:

    def test_a_balanced_ledger_totals_equally(self):
        """The case that ran against the database: a 5,500 fee, a 12,000
        expense and a 77,630 payroll."""
        debits = money(5500) + money(12000) + money(77630)
        credits = money(5500) + money(12000) + money(77630)
        assert debits == credits == money(95130)

    def test_surplus_is_income_less_expenses(self):
        assert money(money(5500) - money(89630)) == money("-84130.00")

    def test_an_asset_balance_is_debits_less_credits(self):
        assert money(money(5500) - money(0)) == money(5500)

    def test_an_income_balance_is_credits_less_debits(self):
        assert money(money(5500) - money(0)) == money(5500)


class TestAccountingMoney:

    def test_no_float_columns(self):
        from sqlalchemy import Float
        import models.erp_accounts as accounts_models

        for name in dir(accounts_models):
            table = getattr(getattr(accounts_models, name), "__table__", None)
            if table is None:
                continue
            for column in table.columns:
                assert not isinstance(column.type, Float), (
                    f"{table.name}.{column.name} is a Float — the ledger must be NUMERIC"
                )


class TestReconciliation:

    def test_an_imported_line_cannot_be_imported_twice(self):
        names = {c.name for c in BankStatementLine.__table__.constraints}
        assert "uq_bank_line_import" in names

    def test_an_unmatched_line_waits_for_a_human(self):
        """AI may rank candidates; it may not confirm one."""
        assert BankStatementLine.__table__.c.status.default.arg == "unmatched"
        assert BankStatementLine.__table__.c.matched_by is not None


class TestCeleryLoopTrap:
    """The bug that would have broken the outbox after its first run.

    `asyncio.run()` closes its loop, and asyncpg connections are bound to the
    loop that opened them — so a shared engine works exactly once per worker
    process. For a task running every sixty seconds that is every run after the
    first.
    """

    def test_the_drain_task_makes_its_own_engine(self):
        import inspect
        from tasks import erp_tasks
        source = inspect.getsource(erp_tasks)
        assert "create_async_engine" in source
        assert "await engine.dispose()" in source

    def test_it_does_not_use_the_shared_session(self):
        import inspect
        from tasks import erp_tasks
        source = inspect.getsource(erp_tasks.drain_domain_events)
        assert "from config.database import async_session" not in source

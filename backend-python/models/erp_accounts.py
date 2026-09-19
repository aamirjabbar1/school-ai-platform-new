"""
Double-entry accounting (ERP phase 6).

The rule the whole module rests on: **nothing writes to the ledger except the
posting service.** Fees, payroll and expenses post through it; nobody types a
journal entry to record a fee.

Two guarantees are made structural rather than hoped for:

  * A journal carries its own totals with a CHECK constraint that they are
    equal. An unbalanced entry cannot exist in the database, whatever the
    application believes.
  * `dedupe_key` is unique, so an event replayed by the outbox posts once. The
    handler can be retried freely, which is the only reason the outbox is safe
    to retry at all.

Periods lock. A correction inside a locked period is a reversal plus a re-post,
never an edit — because an audit that finds a changed figure and no trail is an
audit that stops believing the rest.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index,
    Numeric, String, Text, UniqueConstraint,
)

from config.database import Base
from models.models import gen_uuid, utcnow


ASSET = "asset"
LIABILITY = "liability"
EQUITY = "equity"
INCOME = "income"
EXPENSE = "expense"

ACCOUNT_TYPES = (ASSET, LIABILITY, EQUITY, INCOME, EXPENSE)

# Which side increases an account. Assets and expenses are debit-natured;
# income, liabilities and equity are credit-natured.
DEBIT_NATURED = (ASSET, EXPENSE)
CREDIT_NATURED = (LIABILITY, EQUITY, INCOME)

PERIOD_OPEN = "open"
PERIOD_LOCKED = "locked"


class GLAccount(Base):
    """One line of the chart of accounts."""
    __tablename__ = "gl_accounts"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    code = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(120), nullable=False)
    account_type = Column(String(20), nullable=False)
    parent_id = Column(String(36), ForeignKey("gl_accounts.id"), nullable=True)
    # Only leaves are postable. Posting to a heading is how a trial balance
    # stops adding up.
    is_postable = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "code": self.code, "name": self.name,
            "account_type": self.account_type, "parent_id": self.parent_id,
            "is_postable": bool(self.is_postable), "is_active": bool(self.is_active),
        }


class AccountingPeriod(Base):
    """A month, open or locked."""
    __tablename__ = "accounting_periods"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    period = Column(String(7), nullable=False, unique=True)     # "2026-09"
    status = Column(String(20), nullable=False, default=PERIOD_OPEN)
    locked_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {"period": self.period, "status": self.status,
                "locked_at": self.locked_at.isoformat() if self.locked_at else None}


class Journal(Base):
    """One balanced entry.

    `total_debit` and `total_credit` are stored so the database itself can
    refuse an unbalanced entry. A CHECK across two columns is enforceable;
    a rule about the sum of child rows is not, without a trigger.
    """
    __tablename__ = "journals"
    __table_args__ = (
        CheckConstraint("total_debit = total_credit", name="ck_journal_balanced"),
        UniqueConstraint("dedupe_key", name="uq_journal_dedupe"),
        Index("ix_journal_period", "period"),
        Index("ix_journal_date", "entry_date"),
        Index("ix_journal_source", "source_type", "source_id"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    journal_no = Column(String(30), nullable=False, unique=True, index=True)
    entry_date = Column(Date, nullable=False)
    period = Column(String(7), nullable=False)

    # Where it came from: fee_receipt, payroll_run, expense, manual…
    source_type = Column(String(40), nullable=True)
    source_id = Column(String(36), nullable=True)
    # Unique. An event replayed by the outbox posts exactly once.
    dedupe_key = Column(String(120), nullable=True)

    memo = Column(String(300), nullable=True)
    total_debit = Column(Numeric(14, 2), nullable=False, default=0)
    total_credit = Column(Numeric(14, 2), nullable=False, default=0)

    reversal_of = Column(String(36), ForeignKey("journals.id"), nullable=True)
    reversal_reason = Column(String(200), nullable=True)
    posted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "journal_no": self.journal_no,
            "entry_date": self.entry_date.isoformat() if self.entry_date else None,
            "period": self.period, "memo": self.memo,
            "source_type": self.source_type, "source_id": self.source_id,
            "total": str(self.total_debit),
            "reversal_of": self.reversal_of,
        }


class JournalLine(Base):
    """One side of one entry. Exactly one of debit or credit is non-zero."""
    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint("debit >= 0 AND credit >= 0", name="ck_line_non_negative"),
        CheckConstraint("NOT (debit > 0 AND credit > 0)", name="ck_line_one_side"),
        Index("ix_journal_line_account", "account_id"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    journal_id = Column(String(36), ForeignKey("journals.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    account_id = Column(String(36), ForeignKey("gl_accounts.id"), nullable=False)
    debit = Column(Numeric(14, 2), nullable=False, default=0)
    credit = Column(Numeric(14, 2), nullable=False, default=0)
    memo = Column(String(200), nullable=True)

    def to_dict(self):
        return {"account_id": self.account_id, "debit": str(self.debit),
                "credit": str(self.credit), "memo": self.memo}


class Vendor(Base):
    """Somebody the school buys from."""
    __tablename__ = "vendors"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    code = Column(String(30), nullable=False, unique=True)
    name = Column(String(150), nullable=False)
    contact_person = Column(String(120), nullable=True)
    phone = Column(String(30), nullable=True)
    email = Column(String(150), nullable=True)
    address = Column(Text, nullable=True)
    tax_number = Column(String(40), nullable=True)
    bank_name = Column(String(100), nullable=True)
    bank_account = Column(String(40), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {"id": self.id, "code": self.code, "name": self.name,
                "phone": self.phone, "email": self.email,
                "tax_number": self.tax_number, "is_active": bool(self.is_active)}


class Expense(Base):
    """Money going out, other than salaries."""
    __tablename__ = "expenses"
    __table_args__ = (
        Index("ix_expense_date", "expense_date"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    expense_no = Column(String(30), nullable=False, unique=True, index=True)
    expense_date = Column(Date, nullable=False)
    account_id = Column(String(36), ForeignKey("gl_accounts.id"), nullable=False)
    vendor_id = Column(String(36), ForeignKey("vendors.id"), nullable=True)
    amount = Column(Numeric(14, 2), nullable=False)
    # cash | bank | cheque — decides which account is credited.
    paid_from = Column(String(20), nullable=False, default="cash")
    reference = Column(String(80), nullable=True)
    description = Column(String(300), nullable=True)
    journal_id = Column(String(36), ForeignKey("journals.id"), nullable=True)
    recorded_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "expense_no": self.expense_no,
            "expense_date": self.expense_date.isoformat() if self.expense_date else None,
            "account_id": self.account_id, "vendor_id": self.vendor_id,
            "amount": str(self.amount), "paid_from": self.paid_from,
            "reference": self.reference, "description": self.description,
        }


class BankStatementLine(Base):
    """An imported bank line, waiting to be matched.

    Reconciliation is the one place the specification allows AI to help and
    forbids it to decide: an uncertain match sits here until a human says yes.
    """
    __tablename__ = "bank_statement_lines"
    __table_args__ = (
        UniqueConstraint("import_key", name="uq_bank_line_import"),
        Index("ix_bank_line_date", "value_date"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    account_id = Column(String(36), ForeignKey("gl_accounts.id"), nullable=True)
    value_date = Column(Date, nullable=False)
    description = Column(String(300), nullable=True)
    reference = Column(String(80), nullable=True)
    debit = Column(Numeric(14, 2), nullable=False, default=0)
    credit = Column(Numeric(14, 2), nullable=False, default=0)

    # Bank reference plus date plus amount. Unique, so re-importing an
    # overlapping statement does not duplicate lines.
    import_key = Column(String(160), nullable=True)
    status = Column(String(20), nullable=False, default="unmatched")  # unmatched|matched|ignored
    matched_journal_id = Column(String(36), ForeignKey("journals.id"), nullable=True)
    matched_receipt_id = Column(String(36), ForeignKey("receipts.id"), nullable=True)
    matched_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    matched_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "value_date": self.value_date.isoformat() if self.value_date else None,
            "description": self.description, "reference": self.reference,
            "debit": str(self.debit), "credit": str(self.credit),
            "status": self.status,
        }

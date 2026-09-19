"""
Fees (ERP phase 4).

The first module that holds money, which changes the rules:

  * **Every amount is `NUMERIC(14,2)`, never a float.** A float produces
    statements that are off by a paisa, and a finance office that finds one
    wrong total stops trusting every total.
  * **Nothing is deleted.** A wrong receipt is reversed by another receipt, so
    the trail of what happened survives the correction.
  * **A payment is idempotent on the bank's own reference.** A bank file
    imported twice, or a retried request, must not take a second payment from
    the same parent. This is the one place in the ERP where a duplicate is not
    an annoyance but a real loss.

The account summary (`student_fee_accounts`) is maintained as vouchers and
receipts land rather than recomputed on read. The specification asks for the
whole school's defaulter list "in seconds", and that is a single indexed scan
here versus 755 aggregations there.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint,
)

from config.database import Base
from models.models import gen_uuid, utcnow


# A fee head is charged every month, or once.
HEAD_RECURRING = "recurring"
HEAD_ONE_TIME = "one_time"

VOUCHER_UNPAID = "unpaid"
VOUCHER_PARTIAL = "partial"
VOUCHER_PAID = "paid"
VOUCHER_CANCELLED = "cancelled"

OPEN_VOUCHER_STATES = (VOUCHER_UNPAID, VOUCHER_PARTIAL)

CONCESSION_FIXED = "fixed"
CONCESSION_PERCENT = "percent"

# Categories the specification names (§55). Orphan is one of these and carries
# no special code path — only a permission on its supporting documents.
CONCESSION_CATEGORIES = (
    "sibling", "staff_child", "merit", "scholarship", "orphan",
    "hardship", "management", "other",
)

PAYMENT_CASH = "cash"
PAYMENT_BANK = "bank"
PAYMENT_ONLINE = "online"
PAYMENT_CHEQUE = "cheque"


class FeeHead(Base):
    """What the school charges for — tuition, admission, transport, exam."""
    __tablename__ = "fee_heads"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    code = Column(String(30), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    head_type = Column(String(20), nullable=False, default=HEAD_RECURRING)
    is_refundable = Column(Boolean, nullable=False, default=False)
    # Where this lands in the chart of accounts once phase 6 exists. A string
    # rather than a foreign key so fees can ship before accounting does.
    gl_code = Column(String(20), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {"id": self.id, "code": self.code, "name": self.name,
                "head_type": self.head_type, "is_refundable": bool(self.is_refundable),
                "sort_order": self.sort_order, "is_active": bool(self.is_active)}


class FeeStructure(Base):
    """What a class pays for a head, this session."""
    __tablename__ = "fee_structures"
    __table_args__ = (
        UniqueConstraint("session_id", "class_id", "head_id", name="uq_fee_structure"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("academic_sessions.id"), nullable=False, index=True)
    class_id = Column(String(36), ForeignKey("school_classes.id"), nullable=False, index=True)
    head_id = Column(String(36), ForeignKey("fee_heads.id"), nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    effective_from = Column(Date, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class StudentFeeOverride(Base):
    """One child who pays something other than their class rate."""
    __tablename__ = "student_fee_overrides"
    __table_args__ = (
        UniqueConstraint("student_user_id", "session_id", "head_id", name="uq_student_fee_override"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("academic_sessions.id"), nullable=False)
    head_id = Column(String(36), ForeignKey("fee_heads.id"), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    reason = Column(String(200), nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class Concession(Base):
    """A discount, held against a child or a whole family.

    Family-level is what makes a sibling discount behave: adding a third child
    re-evaluates the discount without anyone remembering to.
    """
    __tablename__ = "concessions"
    __table_args__ = (
        Index("ix_concession_student", "student_user_id"),
        Index("ix_concession_family", "family_id"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    scope = Column(String(20), nullable=False, default="student")   # student | family
    student_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    family_id = Column(String(36), ForeignKey("families.id"), nullable=True)
    # Null means every head — a blanket discount on the whole bill.
    head_id = Column(String(36), ForeignKey("fee_heads.id"), nullable=True)

    concession_type = Column(String(20), nullable=False, default=CONCESSION_PERCENT)
    value = Column(Numeric(14, 2), nullable=False, default=0)
    category = Column(String(30), nullable=False, default="other")

    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    reason = Column(Text, nullable=True)
    # Supporting papers for a hardship or orphan concession sit behind a
    # permission, not in the open.
    document_key = Column(String(300), nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "scope": self.scope,
            "student_user_id": self.student_user_id, "family_id": self.family_id,
            "head_id": self.head_id, "concession_type": self.concession_type,
            "value": str(self.value), "category": self.category,
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "is_active": bool(self.is_active), "reason": self.reason,
        }


class Voucher(Base):
    """One month's bill for one child."""
    __tablename__ = "vouchers"
    __table_args__ = (
        UniqueConstraint("student_user_id", "session_id", "month", name="uq_voucher_student_month"),
        Index("ix_voucher_status", "status"),
        Index("ix_voucher_month", "month"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    voucher_no = Column(String(30), nullable=False, unique=True, index=True)
    student_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("academic_sessions.id"), nullable=False, index=True)
    class_id = Column(String(36), ForeignKey("school_classes.id"), nullable=True)
    section_id = Column(String(36), ForeignKey("sections.id"), nullable=True)

    # The first of the month it bills. A month is a calendar fact, so it is a
    # DATE — a voucher due on the 10th is due on the 10th in any timezone.
    month = Column(Date, nullable=False)
    issue_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)

    gross = Column(Numeric(14, 2), nullable=False, default=0)
    concession = Column(Numeric(14, 2), nullable=False, default=0)
    arrears = Column(Numeric(14, 2), nullable=False, default=0)
    late_fee = Column(Numeric(14, 2), nullable=False, default=0)
    payable = Column(Numeric(14, 2), nullable=False, default=0)
    paid = Column(Numeric(14, 2), nullable=False, default=0)

    # What the bank scans, and what KuickPay quotes. Held on the voucher
    # rather than derived, so a reprint is the same piece of paper.
    challan_no = Column(String(30), nullable=True, index=True)
    kuickpay_id = Column(String(30), nullable=True, index=True)
    valid_till = Column(Date, nullable=True)
    # Which child of the family this is — the sample voucher prints "Child # 1".
    child_number = Column(Integer, nullable=True)

    status = Column(String(20), nullable=False, default=VOUCHER_UNPAID)
    cancelled_reason = Column(String(200), nullable=True)
    generated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "voucher_no": self.voucher_no,
            "student_user_id": self.student_user_id,
            "month": self.month.isoformat() if self.month else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "gross": str(self.gross), "concession": str(self.concession),
            "arrears": str(self.arrears), "late_fee": str(self.late_fee),
            "challan_no": self.challan_no, "kuickpay_id": self.kuickpay_id,
            "valid_till": self.valid_till.isoformat() if self.valid_till else None,
            "payable": str(self.payable), "paid": str(self.paid),
            "outstanding": str((self.payable or 0) - (self.paid or 0)),
            # What the parent hands over: this month's charge plus whatever was
            # already owed when the voucher was printed.
            "total_due": str((self.payable or 0) + (self.arrears or 0)),
            "status": self.status,
        }


class VoucherLine(Base):
    """One head on one voucher — the breakdown a parent reads."""
    __tablename__ = "voucher_lines"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    voucher_id = Column(String(36), ForeignKey("vouchers.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    head_id = Column(String(36), ForeignKey("fee_heads.id"), nullable=False)
    head_name = Column(String(100), nullable=True)      # snapshot: heads get renamed
    amount = Column(Numeric(14, 2), nullable=False, default=0)
    concession = Column(Numeric(14, 2), nullable=False, default=0)
    net = Column(Numeric(14, 2), nullable=False, default=0)

    def to_dict(self):
        return {"head_id": self.head_id, "head_name": self.head_name,
                "amount": str(self.amount), "concession": str(self.concession),
                "net": str(self.net)}


class Receipt(Base):
    """Money actually received.

    `bank_reference` is unique where present: that is what makes importing the
    same bank file twice harmless.
    """
    __tablename__ = "receipts"
    __table_args__ = (
        UniqueConstraint("bank_reference", name="uq_receipt_bank_reference"),
        Index("ix_receipt_student", "student_user_id"),
        Index("ix_receipt_date", "received_on"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    receipt_no = Column(String(30), nullable=False, unique=True, index=True)
    student_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    voucher_id = Column(String(36), ForeignKey("vouchers.id"), nullable=True, index=True)

    amount = Column(Numeric(14, 2), nullable=False)
    method = Column(String(20), nullable=False, default=PAYMENT_CASH)
    bank_reference = Column(String(80), nullable=True)
    received_on = Column(Date, nullable=False)
    received_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    note = Column(String(200), nullable=True)

    # A reversal is another receipt with a negative amount pointing at the one
    # it undoes. Nothing is ever deleted.
    reversal_of = Column(String(36), ForeignKey("receipts.id"), nullable=True)
    reversal_reason = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "receipt_no": self.receipt_no,
            "student_user_id": self.student_user_id, "voucher_id": self.voucher_id,
            "amount": str(self.amount), "method": self.method,
            "bank_reference": self.bank_reference,
            "received_on": self.received_on.isoformat() if self.received_on else None,
            "note": self.note, "reversal_of": self.reversal_of,
        }


class LedgerEntry(Base):
    """The student's statement, one line per event.

    Debit is what they owe, credit is what they paid — the convention every
    accountant already has in their head.
    """
    __tablename__ = "student_ledger"
    __table_args__ = (
        Index("ix_ledger_student_date", "student_user_id", "entry_date"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    entry_date = Column(Date, nullable=False)
    description = Column(String(200), nullable=False)
    debit = Column(Numeric(14, 2), nullable=False, default=0)
    credit = Column(Numeric(14, 2), nullable=False, default=0)
    # Running balance as at this line, so a statement prints without the
    # browser re-adding a year of history.
    balance = Column(Numeric(14, 2), nullable=False, default=0)
    source_type = Column(String(30), nullable=True)     # voucher | receipt | adjustment
    source_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "date": self.entry_date.isoformat() if self.entry_date else None,
            "description": self.description,
            "debit": str(self.debit), "credit": str(self.credit),
            "balance": str(self.balance),
            "source_type": self.source_type, "source_id": self.source_id,
        }


class StudentFeeAccount(Base):
    """The running position for one child, maintained as things happen.

    The specification wants the whole school's active defaulters in seconds.
    That is this table with an index, rather than 755 aggregations over the
    ledger every time somebody opens the report.
    """
    __tablename__ = "student_fee_accounts"
    __table_args__ = (
        Index("ix_fee_account_outstanding", "outstanding"),
    )

    student_user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    total_billed = Column(Numeric(14, 2), nullable=False, default=0)
    total_paid = Column(Numeric(14, 2), nullable=False, default=0)
    outstanding = Column(Numeric(14, 2), nullable=False, default=0)
    advance = Column(Numeric(14, 2), nullable=False, default=0)

    oldest_unpaid_month = Column(Date, nullable=True)
    unpaid_months = Column(Integer, nullable=False, default=0)
    last_payment_on = Column(Date, nullable=True)
    last_payment_amount = Column(Numeric(14, 2), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "student_user_id": self.student_user_id,
            "total_billed": str(self.total_billed),
            "total_paid": str(self.total_paid),
            "outstanding": str(self.outstanding),
            "advance": str(self.advance),
            "oldest_unpaid_month": self.oldest_unpaid_month.isoformat() if self.oldest_unpaid_month else None,
            "unpaid_months": self.unpaid_months,
            "last_payment_on": self.last_payment_on.isoformat() if self.last_payment_on else None,
            "last_payment_amount": str(self.last_payment_amount) if self.last_payment_amount is not None else None,
        }


class VoucherRun(Base):
    """One generation job, so a bulk run is reportable and re-runnable."""
    __tablename__ = "voucher_runs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    session_id = Column(String(36), ForeignKey("academic_sessions.id"), nullable=False)
    month = Column(Date, nullable=False)
    class_id = Column(String(36), ForeignKey("school_classes.id"), nullable=True)
    section_id = Column(String(36), ForeignKey("sections.id"), nullable=True)
    status = Column(String(20), nullable=False, default="done")
    created_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    total_amount = Column(Numeric(14, 2), nullable=False, default=0)
    run_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "month": self.month.isoformat() if self.month else None,
            "created": self.created_count, "skipped": self.skipped_count,
            "total_amount": str(self.total_amount),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class VoucherSettings(Base):
    """Everything on the printed voucher that is school policy rather than
    layout — the bank, the account, the campus code, the note, the daily fine.

    A single row. It is here so the office can change a bank account without a
    deployment, and so the wording of the note stays the school's wording.
    """
    __tablename__ = "voucher_settings"

    id = Column(String(36), primary_key=True, default=gen_uuid)

    school_name = Column(String(120), nullable=False, default="Lahore School System")
    email = Column(String(120), nullable=True, default="info@lss.edu.pk")
    website = Column(String(120), nullable=True, default="www.lss.edu.pk")

    bank_name = Column(String(80), nullable=True, default="BankIslami")
    bank_account = Column(String(60), nullable=True)
    campus_code = Column(String(30), nullable=True)
    post_to = Column(String(60), nullable=True, default="POST TO CMD")
    bank_line = Column(String(200), nullable=True)

    note = Column(Text, nullable=True)
    # Rs per day after the due date. Shown in the note and used to work out the
    # late fine between the due date and the valid-till date.
    late_fine_per_day = Column(Numeric(10, 2), nullable=False, default=50)
    # How long after the due date the bank will still accept the voucher.
    valid_days_after_due = Column(Integer, nullable=False, default=5)

    # Challan numbers are what the bank reconciles against; KuickPay issues its
    # own voucher id. Both are patterns so the school's existing numbering can
    # be reproduced rather than replaced.
    challan_pattern = Column(String(60), nullable=True, default="{seq:09d}")
    kuickpay_prefix = Column(String(20), nullable=True)

    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "school_name": self.school_name, "email": self.email, "website": self.website,
            "bank_name": self.bank_name, "bank_account": self.bank_account,
            "campus_code": self.campus_code, "post_to": self.post_to,
            "bank_line": self.bank_line, "note": self.note,
            "late_fine_per_day": str(self.late_fine_per_day),
            "valid_days_after_due": self.valid_days_after_due,
            "challan_pattern": self.challan_pattern,
            "kuickpay_prefix": self.kuickpay_prefix,
        }

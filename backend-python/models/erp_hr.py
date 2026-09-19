"""
Salary and payroll (ERP phase 5).

Two rules from the specification shape every table here, and both are about
history rather than arithmetic:

  * **Salary is never overwritten.** A revision closes the current structure
    with an `effective_to` and inserts a new one. History is then free, and a
    payslip from two years ago still reproduces exactly.

  * **The letter is not the record.** An appointment letter is a rendering of
    the salary structure at a point in time. Payroll reads the structure, never
    a document — which is what lets a month run without a human opening a file.

A payroll line snapshots the components it was computed from. Approving a run
freezes it, so a salary corrected next March cannot silently change a payslip
that was already handed over.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, JSON,
    Numeric, String, Text, UniqueConstraint,
)

from config.database import Base
from models.models import gen_uuid, utcnow


COMPONENT_ALLOWANCE = "allowance"
COMPONENT_DEDUCTION = "deduction"

CALC_FIXED = "fixed"
CALC_PERCENT_OF_BASIC = "percent_of_basic"

PAYROLL_DRAFT = "draft"
PAYROLL_CALCULATED = "calculated"
PAYROLL_APPROVED = "approved"
PAYROLL_PAID = "paid"

# Once a run is approved its lines are frozen. Anything after that is a
# correction in a later month, not an edit of a payslip already issued.
PAYROLL_LOCKED_STATES = (PAYROLL_APPROVED, PAYROLL_PAID)


class SalaryStructure(Base):
    """What one employee is paid, from a date until it is revised."""
    __tablename__ = "salary_structures"
    __table_args__ = (
        Index("ix_salary_employee_active", "employee_user_id", "is_active"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    employee_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    basic = Column(Numeric(14, 2), nullable=False, default=0)

    effective_from = Column(Date, nullable=False)
    # Null means "still in force". Set when a revision supersedes it.
    effective_to = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    supersedes_id = Column(String(36), ForeignKey("salary_structures.id"), nullable=True)
    reason = Column(String(200), nullable=True)          # increment, promotion, correction
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "employee_user_id": self.employee_user_id,
            "basic": str(self.basic),
            "effective_from": self.effective_from.isoformat() if self.effective_from else None,
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "is_active": bool(self.is_active), "reason": self.reason,
        }


class SalaryComponent(Base):
    """An allowance or a deduction on a structure."""
    __tablename__ = "salary_components"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    structure_id = Column(String(36), ForeignKey("salary_structures.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    component_type = Column(String(20), nullable=False, default=COMPONENT_ALLOWANCE)
    code = Column(String(30), nullable=False)
    name = Column(String(100), nullable=False)
    calculation = Column(String(30), nullable=False, default=CALC_FIXED)
    # A rupee amount, or a percentage of basic — the calculation column says which.
    value = Column(Numeric(14, 2), nullable=False, default=0)
    is_taxable = Column(Boolean, nullable=False, default=True)
    # Some allowances are paid whole even for a half month (a fixed conveyance
    # allowance, say). Most prorate with the days worked.
    prorates = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)

    def to_dict(self):
        return {
            "id": self.id, "component_type": self.component_type,
            "code": self.code, "name": self.name, "calculation": self.calculation,
            "value": str(self.value), "is_taxable": bool(self.is_taxable),
            "prorates": bool(self.prorates),
        }


class PayrollRun(Base):
    """One month's payroll."""
    __tablename__ = "payroll_runs"
    __table_args__ = (
        UniqueConstraint("month", name="uq_payroll_month"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    month = Column(Date, nullable=False)          # first of the month
    status = Column(String(20), nullable=False, default=PAYROLL_DRAFT, index=True)

    employee_count = Column(Integer, nullable=False, default=0)
    total_gross = Column(Numeric(14, 2), nullable=False, default=0)
    total_deductions = Column(Numeric(14, 2), nullable=False, default=0)
    total_net = Column(Numeric(14, 2), nullable=False, default=0)

    generated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    paid_on = Column(Date, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "month": self.month.isoformat() if self.month else None,
            "status": self.status,
            "employee_count": self.employee_count,
            "total_gross": str(self.total_gross),
            "total_deductions": str(self.total_deductions),
            "total_net": str(self.total_net),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "paid_on": self.paid_on.isoformat() if self.paid_on else None,
        }


class PayrollLine(Base):
    """One employee's pay for one month, frozen once approved."""
    __tablename__ = "payroll_lines"
    __table_args__ = (
        UniqueConstraint("run_id", "employee_user_id", name="uq_payroll_line"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    run_id = Column(String(36), ForeignKey("payroll_runs.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    employee_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    structure_id = Column(String(36), ForeignKey("salary_structures.id"), nullable=True)

    basic = Column(Numeric(14, 2), nullable=False, default=0)
    allowances = Column(Numeric(14, 2), nullable=False, default=0)
    gross = Column(Numeric(14, 2), nullable=False, default=0)
    deductions = Column(Numeric(14, 2), nullable=False, default=0)
    bonus = Column(Numeric(14, 2), nullable=False, default=0)
    arrears = Column(Numeric(14, 2), nullable=False, default=0)
    advance_recovery = Column(Numeric(14, 2), nullable=False, default=0)
    tax = Column(Numeric(14, 2), nullable=False, default=0)
    net = Column(Numeric(14, 2), nullable=False, default=0)

    # Proration (§24): joining or leaving mid-month, and unpaid leave.
    days_in_month = Column(Integer, nullable=False, default=30)
    days_payable = Column(Integer, nullable=False, default=30)
    unpaid_leave_days = Column(Numeric(6, 2), nullable=False, default=0)
    is_prorated = Column(Boolean, nullable=False, default=False)

    # What it was computed from, kept with the line. Approving freezes the
    # payslip; a salary corrected later cannot rewrite one already handed over.
    breakdown = Column(JSON, nullable=True)
    note = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "employee_user_id": self.employee_user_id,
            "basic": str(self.basic), "allowances": str(self.allowances),
            "gross": str(self.gross), "deductions": str(self.deductions),
            "bonus": str(self.bonus), "arrears": str(self.arrears),
            "advance_recovery": str(self.advance_recovery), "tax": str(self.tax),
            "net": str(self.net),
            "days_in_month": self.days_in_month, "days_payable": self.days_payable,
            "unpaid_leave_days": str(self.unpaid_leave_days),
            "is_prorated": bool(self.is_prorated),
            "breakdown": self.breakdown, "note": self.note,
        }


class EmployeeAdvance(Base):
    """Money lent to an employee, recovered from later payrolls."""
    __tablename__ = "employee_advances"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    employee_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(14, 2), nullable=False)
    instalment = Column(Numeric(14, 2), nullable=False)
    outstanding = Column(Numeric(14, 2), nullable=False)
    reason = Column(String(200), nullable=True)
    taken_on = Column(Date, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "employee_user_id": self.employee_user_id,
            "amount": str(self.amount), "instalment": str(self.instalment),
            "outstanding": str(self.outstanding), "reason": self.reason,
            "taken_on": self.taken_on.isoformat() if self.taken_on else None,
            "is_active": bool(self.is_active),
        }


class EmployeeDocument(Base):
    """The digital personnel file (§15).

    Documents are held in MinIO and served only through a permission-checked
    endpoint that issues a short-lived scoped token. Never a public URL: a
    CNIC scan in a bucket anyone can read is a CNIC scan anyone can read.
    """
    __tablename__ = "employee_documents"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    employee_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    # appointment_letter | cnic | cv | degree | certificate | contract |
    # increment_letter | resignation | clearance | other
    doc_type = Column(String(40), nullable=False, default="other")
    title = Column(String(200), nullable=False)
    file_key = Column(String(300), nullable=True)
    issue_date = Column(Date, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    note = Column(Text, nullable=True)
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id, "employee_user_id": self.employee_user_id,
            "doc_type": self.doc_type, "title": self.title,
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "version": self.version, "note": self.note,
            "has_file": bool(self.file_key),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

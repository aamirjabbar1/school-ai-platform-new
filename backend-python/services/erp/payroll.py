"""
The payroll engine (ERP phase 5).

Salary defined once, generate monthly, review, approve — the specification's
whole ask for this module. Which means the engine has to be right about the
awkward months rather than the easy ones:

  * somebody who joined on the 14th,
  * somebody who resigned on the 3rd,
  * somebody who took four days of unpaid leave,
  * somebody whose salary was revised mid-month.

All four come down to one number — how many days of this month the employee is
actually owed — so that number is computed once, explicitly, and shown on the
payslip rather than hidden inside a total.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import EmployeeProfile
from models.erp_attendance import LeaveRequest
from models.erp_hr import (
    CALC_PERCENT_OF_BASIC, COMPONENT_ALLOWANCE, COMPONENT_DEDUCTION,
    PAYROLL_APPROVED, PAYROLL_CALCULATED, PAYROLL_DRAFT, PAYROLL_LOCKED_STATES,
    PAYROLL_PAID, EmployeeAdvance, PayrollLine, PayrollRun, SalaryComponent,
    SalaryStructure,
)
from models.models import User, utcnow
from services.erp import audit, events
from services.erp.fees import ZERO, money, month_start

logger = logging.getLogger("agent")


class PayrollError(RuntimeError):
    """Something HR needs to fix, phrased for HR."""


# ─── Salary structures ────────────────────────────────────────────────────────

async def current_structure(db: AsyncSession, employee_user_id: str) -> SalaryStructure | None:
    result = await db.execute(
        select(SalaryStructure).where(
            SalaryStructure.employee_user_id == employee_user_id,
            SalaryStructure.is_active.is_(True),
        ).order_by(SalaryStructure.effective_from.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def structure_for_month(
    db: AsyncSession, employee_user_id: str, month: date,
) -> SalaryStructure | None:
    """The structure in force during a month.

    Looks back rather than at "current", so re-running an old month uses the
    salary that applied then and not the one that applies now.
    """
    end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    result = await db.execute(
        select(SalaryStructure).where(
            SalaryStructure.employee_user_id == employee_user_id,
            SalaryStructure.effective_from <= end,
            or_(SalaryStructure.effective_to.is_(None), SalaryStructure.effective_to >= month),
        ).order_by(SalaryStructure.effective_from.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def set_salary(
    db: AsyncSession,
    *,
    employee_user_id: str,
    basic,
    components: list[dict] | None = None,
    effective_from: date | None = None,
    reason: str | None = None,
    actor: User | None = None,
) -> SalaryStructure:
    """Define or revise a salary.

    A revision never overwrites: the current structure is closed the day before
    the new one starts, and the new row points back at it. That is what makes a
    two-year-old payslip reproducible and an increment history free.
    """
    basic = money(basic)
    if basic <= ZERO:
        raise PayrollError("The basic salary must be more than zero.")

    effective_from = effective_from or date.today()
    existing = await current_structure(db, employee_user_id)

    if existing and existing.effective_from > effective_from:
        raise PayrollError(
            "This employee already has a salary starting later than that date. "
            "Choose a later effective date."
        )

    structure = SalaryStructure(
        employee_user_id=employee_user_id,
        basic=basic,
        effective_from=effective_from,
        reason=reason,
        approved_by=actor.id if actor else None,
        approved_at=utcnow(),
        supersedes_id=existing.id if existing else None,
    )
    db.add(structure)
    await db.flush()

    for index, component in enumerate(components or []):
        db.add(SalaryComponent(
            structure_id=structure.id,
            component_type=component.get("component_type", COMPONENT_ALLOWANCE),
            code=component.get("code") or f"C{index + 1}",
            name=component.get("name") or "Allowance",
            calculation=component.get("calculation", "fixed"),
            value=money(component.get("value", 0)),
            is_taxable=bool(component.get("is_taxable", True)),
            prorates=bool(component.get("prorates", True)),
            sort_order=index,
        ))

    if existing:
        from datetime import timedelta
        existing.is_active = False
        existing.effective_to = effective_from - timedelta(days=1)

    audit.record(
        db, actor=actor, entity_type="salary_structure", action="revised" if existing else "created",
        entity_id=structure.id,
        old_value={"basic": str(existing.basic)} if existing else None,
        new_value={"basic": str(basic), "effective_from": effective_from.isoformat()},
        reason=reason,
    )
    return structure


# ─── Proration ────────────────────────────────────────────────────────────────

async def payable_days(
    db: AsyncSession, *, employee_user_id: str, month: date, profile: EmployeeProfile | None,
) -> tuple[int, int, Decimal, list[str]]:
    """How many days of this month the employee is owed, and why.

    Returns (days_in_month, days_payable, unpaid_leave_days, reasons). The
    reasons are shown on the payslip: "joined on the 14th" is an answer, "your
    salary is 12,900 this month" on its own is a complaint.
    """
    days_in_month = calendar.monthrange(month.year, month.month)[1]
    first = month
    last = date(month.year, month.month, days_in_month)

    start = first
    end = last
    reasons: list[str] = []

    if profile and profile.joining_date and profile.joining_date > first:
        if profile.joining_date > last:
            return days_in_month, 0, ZERO, ["had not joined yet"]
        start = profile.joining_date
        reasons.append(f"joined on {profile.joining_date.strftime('%d %B')}")

    if profile and profile.left_on and profile.left_on < last:
        if profile.left_on < first:
            return days_in_month, 0, ZERO, ["had already left"]
        end = profile.left_on
        reasons.append(f"left on {profile.left_on.strftime('%d %B')}")

    worked = (end - start).days + 1 if end >= start else 0

    # Approved unpaid leave inside the month.
    result = await db.execute(
        select(LeaveRequest).where(
            LeaveRequest.employee_user_id == employee_user_id,
            LeaveRequest.status == "approved",
            LeaveRequest.is_paid.is_(False),
            LeaveRequest.from_date <= last,
            LeaveRequest.to_date >= first,
        )
    )
    unpaid = ZERO
    for leave in result.scalars().all():
        overlap_start = max(leave.from_date, first)
        overlap_end = min(leave.to_date, last)
        days = (overlap_end - overlap_start).days + 1
        if days > 0:
            unpaid += Decimal(days)
    if unpaid > ZERO:
        reasons.append(f"{unpaid:g} day{'s' if unpaid != 1 else ''} unpaid leave")

    payable = max(Decimal(worked) - unpaid, ZERO)
    return days_in_month, int(payable), unpaid, reasons


# ─── Generating a month ───────────────────────────────────────────────────────

async def generate_payroll(
    db: AsyncSession, *, month: date, actor: User | None = None,
) -> dict:
    """Calculate every active employee's pay for a month.

    Re-running a draft replaces its lines, because the usual reason for
    re-running is that somebody has just fixed a salary. Re-running an approved
    month is refused — that payslip has been handed over.
    """
    month = month_start(month)

    result = await db.execute(select(PayrollRun).where(PayrollRun.month == month))
    run = result.scalar_one_or_none()

    if run and run.status in PAYROLL_LOCKED_STATES:
        raise PayrollError(
            f"Payroll for {month.strftime('%B %Y')} has already been approved. "
            "Make any correction in the next month's payroll."
        )

    if run is None:
        run = PayrollRun(month=month, generated_by=actor.id if actor else None)
        db.add(run)
        await db.flush()
    else:
        await db.execute(
            PayrollLine.__table__.delete().where(PayrollLine.run_id == run.id)
        )

    result = await db.execute(
        select(User, EmployeeProfile)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id, isouter=True)
        .where(User.role.in_(("teacher", "admin")), User.is_active.is_(True))
        .order_by(User.name)
    )
    staff = result.all()

    total_gross = total_deductions = total_net = ZERO
    counted = 0
    without_salary: list[str] = []

    for employee, profile in staff:
        structure = await structure_for_month(db, employee.id, month)
        if structure is None:
            # Not an error: a new joiner whose salary has not been set yet.
            # They appear on the exceptions list instead of silently earning
            # zero, which is the failure mode that reaches a payslip.
            without_salary.append(employee.name)
            continue

        result = await db.execute(
            select(SalaryComponent)
            .where(SalaryComponent.structure_id == structure.id)
            .order_by(SalaryComponent.sort_order)
        )
        components = list(result.scalars().all())

        days_in_month, days, unpaid_days, reasons = await payable_days(
            db, employee_user_id=employee.id, month=month, profile=profile,
        )
        if days <= 0:
            continue

        factor = Decimal(days) / Decimal(days_in_month)
        prorated = days < days_in_month

        basic = money(money(structure.basic) * factor)
        allowances = deductions = ZERO
        breakdown = {"basic": str(basic), "components": [], "reasons": reasons}

        for component in components:
            base = money(structure.basic)
            raw = money(base * money(component.value) / Decimal("100")) \
                if component.calculation == CALC_PERCENT_OF_BASIC else money(component.value)
            value = money(raw * factor) if component.prorates else raw

            if component.component_type == COMPONENT_ALLOWANCE:
                allowances += value
            else:
                deductions += value
            breakdown["components"].append({
                "name": component.name, "type": component.component_type,
                "value": str(value),
            })

        # Advance recovery — capped at what is left, so a final instalment of
        # 300 against a 1,000 instalment takes 300.
        result = await db.execute(
            select(EmployeeAdvance).where(
                EmployeeAdvance.employee_user_id == employee.id,
                EmployeeAdvance.is_active.is_(True),
                EmployeeAdvance.outstanding > 0,
            )
        )
        advances = list(result.scalars().all())
        advance_recovery = ZERO
        for advance in advances:
            take = min(money(advance.instalment), money(advance.outstanding))
            advance_recovery += take

        gross = money(basic + allowances)
        net = money(gross - deductions - advance_recovery)

        db.add(PayrollLine(
            run_id=run.id,
            employee_user_id=employee.id,
            structure_id=structure.id,
            basic=basic,
            allowances=allowances,
            gross=gross,
            deductions=deductions,
            advance_recovery=advance_recovery,
            net=net,
            days_in_month=days_in_month,
            days_payable=days,
            unpaid_leave_days=unpaid_days,
            is_prorated=prorated,
            breakdown=breakdown,
            note="; ".join(reasons) or None,
        ))

        total_gross += gross
        total_deductions += money(deductions + advance_recovery)
        total_net += net
        counted += 1

    run.status = PAYROLL_CALCULATED
    run.employee_count = counted
    run.total_gross = money(total_gross)
    run.total_deductions = money(total_deductions)
    run.total_net = money(total_net)

    audit.record(
        db, actor=actor, entity_type="payroll", action="generated",
        entity_id=run.id,
        new_value={"month": month.isoformat(), "employees": counted,
                   "net": str(money(total_net))},
    )

    return {
        **run.to_dict(),
        "without_salary": without_salary,
    }


async def approve_payroll(db: AsyncSession, *, run_id: str, actor: User | None = None) -> dict:
    """Approve a month. Recovers advances, freezes the lines, tells accounting."""
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise PayrollError("That payroll run was not found.")
    if run.status in PAYROLL_LOCKED_STATES:
        raise PayrollError("This payroll has already been approved.")
    if run.status == PAYROLL_DRAFT:
        raise PayrollError("Generate the payroll before approving it.")

    result = await db.execute(select(PayrollLine).where(PayrollLine.run_id == run.id))
    lines = list(result.scalars().all())
    if not lines:
        raise PayrollError("There is nothing to approve — no salaries were calculated.")

    # Advances are only recovered at approval, never at calculation. A draft
    # re-run would otherwise take the instalment twice.
    for line in lines:
        if money(line.advance_recovery) <= ZERO:
            continue
        result = await db.execute(
            select(EmployeeAdvance).where(
                EmployeeAdvance.employee_user_id == line.employee_user_id,
                EmployeeAdvance.is_active.is_(True),
                EmployeeAdvance.outstanding > 0,
            )
        )
        remaining = money(line.advance_recovery)
        for advance in result.scalars().all():
            if remaining <= ZERO:
                break
            take = min(money(advance.outstanding), remaining)
            advance.outstanding = money(advance.outstanding - take)
            remaining = money(remaining - take)
            if advance.outstanding <= ZERO:
                advance.is_active = False

    run.status = PAYROLL_APPROVED
    run.approved_by = actor.id if actor else None
    run.approved_at = utcnow()

    events.emit(
        db, events.PAYROLL_APPROVED,
        {"run_id": run.id, "month": run.month.isoformat(),
         "total_net": str(run.total_net), "employees": run.employee_count},
        dedupe_key=f"payroll_approved:{run.id}",
    )
    audit.record(
        db, actor=actor, entity_type="payroll", action="approved",
        entity_id=run.id,
        new_value={"month": run.month.isoformat(), "net": str(run.total_net),
                   "employees": run.employee_count},
    )
    return run.to_dict()


async def mark_paid(db: AsyncSession, *, run_id: str, paid_on: date, actor: User | None = None) -> dict:
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise PayrollError("That payroll run was not found.")
    if run.status != PAYROLL_APPROVED:
        raise PayrollError("Approve the payroll before marking it paid.")

    run.status = PAYROLL_PAID
    run.paid_on = paid_on
    audit.record(db, actor=actor, entity_type="payroll", action="paid",
                 entity_id=run.id, new_value={"paid_on": paid_on.isoformat()})
    return run.to_dict()


# ─── Reporting ────────────────────────────────────────────────────────────────

async def run_detail(db: AsyncSession, *, run_id: str) -> dict:
    result = await db.execute(select(PayrollRun).where(PayrollRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise PayrollError("That payroll run was not found.")

    result = await db.execute(
        select(PayrollLine, User, EmployeeProfile)
        .join(User, User.id == PayrollLine.employee_user_id)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id, isouter=True)
        .where(PayrollLine.run_id == run_id)
        .order_by(User.name)
    )
    lines = [
        {
            **line.to_dict(),
            "name": employee.name,
            "employee_no": profile.employee_no if profile else None,
            "designation": profile.designation if profile else None,
            "bank_name": profile.bank_name if profile else None,
            "bank_iban": profile.bank_iban if profile else None,
        }
        for line, employee, profile in result.all()
    ]
    return {**run.to_dict(), "lines": lines}


async def bank_transfer_rows(db: AsyncSession, *, run_id: str) -> list[dict]:
    """What the bank needs, and nothing else.

    Deliberately minimal: employee number, name, account, amount. A bank file
    carrying designations and CNICs is a payroll leak waiting to be emailed to
    the wrong address.
    """
    detail = await run_detail(db, run_id=run_id)
    return [
        {
            "employee_no": line["employee_no"],
            "name": line["name"],
            "bank": line["bank_name"],
            "iban": line["bank_iban"],
            "amount": line["net"],
        }
        for line in detail["lines"]
        if money(line["net"]) > ZERO
    ]

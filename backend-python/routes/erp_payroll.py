"""
Payroll API (ERP phase 5).

Select month → generate → review → approve, which is the specification's whole
flow for this module. Defining a salary and approving a payroll are separate
permissions: the person who sets what someone earns should not be the only
person who checks the month before the money leaves.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user
from models.erp import EmployeeProfile
from models.erp_hr import (
    EmployeeAdvance, EmployeeDocument, PayrollLine, PayrollRun,
    SalaryComponent, SalaryStructure,
)
from models.models import User
from routes.erp import erp_available
from services.erp import audit, payroll as payroll_service
from services.erp.fees import money
from services.erp.payroll import PayrollError
from services.erp.permissions import permissions_for, require_permission

router = APIRouter(prefix="/erp/payroll", tags=["erp-payroll"])


def _fail(exc: PayrollError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# ─── Salary structures ────────────────────────────────────────────────────────

class ComponentRequest(BaseModel):
    component_type: str = "allowance"
    code: str | None = None
    name: str
    calculation: str = "fixed"
    value: Decimal
    is_taxable: bool = True
    prorates: bool = True


class SalaryRequest(BaseModel):
    basic: Decimal
    components: list[ComponentRequest] = []
    effective_from: date | None = None
    reason: str | None = None


@router.get("/salaries")
async def list_salaries(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.structure")),
    db: AsyncSession = Depends(get_db),
):
    """Every employee with their current salary, and who has none yet.

    "Who has no salary defined" is the list that blocks a payroll run, so it
    comes back with the rest rather than being a separate hunt.
    """
    result = await db.execute(
        select(User, EmployeeProfile)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id, isouter=True)
        .where(User.role.in_(("teacher", "admin")), User.is_active.is_(True))
        .order_by(User.name)
    )
    staff = result.all()

    result = await db.execute(
        select(SalaryStructure).where(SalaryStructure.is_active.is_(True))
    )
    current = {s.employee_user_id: s for s in result.scalars().all()}

    return {
        "staff": [
            {
                "id": employee.id,
                "name": employee.name,
                "employee_no": profile.employee_no if profile else None,
                "designation": profile.designation if profile else None,
                "joining_date": profile.joining_date.isoformat() if profile and profile.joining_date else None,
                "basic": str(current[employee.id].basic) if employee.id in current else None,
                "effective_from": current[employee.id].effective_from.isoformat()
                                  if employee.id in current else None,
                "has_salary": employee.id in current,
            }
            for employee, profile in staff
        ]
    }


@router.get("/salaries/{employee_user_id}")
async def salary_history(
    employee_user_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.structure")),
    db: AsyncSession = Depends(get_db),
):
    """Every salary this employee has ever had. Nothing is overwritten, so the
    increment history is simply this list."""
    result = await db.execute(
        select(SalaryStructure)
        .where(SalaryStructure.employee_user_id == employee_user_id)
        .order_by(SalaryStructure.effective_from.desc())
    )
    structures = list(result.scalars().all())

    out = []
    for structure in structures:
        result = await db.execute(
            select(SalaryComponent)
            .where(SalaryComponent.structure_id == structure.id)
            .order_by(SalaryComponent.sort_order)
        )
        out.append({
            **structure.to_dict(),
            "components": [c.to_dict() for c in result.scalars().all()],
        })
    return {"history": out}


@router.put("/salaries/{employee_user_id}")
async def set_salary(
    employee_user_id: str,
    body: SalaryRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.structure")),
    db: AsyncSession = Depends(get_db),
):
    try:
        structure = await payroll_service.set_salary(
            db,
            employee_user_id=employee_user_id,
            basic=body.basic,
            components=[c.model_dump() for c in body.components],
            effective_from=body.effective_from,
            reason=body.reason,
            actor=user,
        )
    except PayrollError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return structure.to_dict()


# ─── Runs ─────────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    month: date


@router.get("/runs")
async def list_runs(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.report")),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(24, le=60),
):
    result = await db.execute(select(PayrollRun).order_by(PayrollRun.month.desc()).limit(limit))
    return {"runs": [r.to_dict() for r in result.scalars().all()]}


@router.post("/runs/generate")
async def generate(
    body: GenerateRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.run")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await payroll_service.generate_payroll(db, month=body.month, actor=user)
    except PayrollError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return result


@router.get("/runs/{run_id}")
async def run_detail(
    run_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.report")),
    db: AsyncSession = Depends(get_db),
):
    held = await permissions_for(db, user)
    try:
        detail = await payroll_service.run_detail(db, run_id=run_id)
    except PayrollError as exc:
        raise _fail(exc)

    # Bank details are payroll-sensitive even inside payroll.
    if "employee.sensitive" not in held:
        for line in detail["lines"]:
            line.pop("bank_name", None)
            line.pop("bank_iban", None)
    return detail


@router.post("/runs/{run_id}/approve")
async def approve(
    run_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.approve")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await payroll_service.approve_payroll(db, run_id=run_id, actor=user)
    except PayrollError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return result


class PaidRequest(BaseModel):
    paid_on: date | None = None


@router.post("/runs/{run_id}/paid")
async def mark_paid(
    run_id: str,
    body: PaidRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.approve")),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await payroll_service.mark_paid(
            db, run_id=run_id, paid_on=body.paid_on or date.today(), actor=user,
        )
    except PayrollError as exc:
        await db.rollback()
        raise _fail(exc)
    await db.commit()
    return result


@router.get("/runs/{run_id}/bank-file")
async def bank_file(
    run_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.approve", "employee.sensitive")),
    db: AsyncSession = Depends(get_db),
):
    """The bank transfer list. Requires sight of bank details by definition."""
    try:
        rows = await payroll_service.bank_transfer_rows(db, run_id=run_id)
    except PayrollError as exc:
        raise _fail(exc)

    missing = [r["name"] for r in rows if not r["iban"]]
    return {"rows": rows, "missing_bank_details": missing}


@router.get("/payslip/{run_id}/{employee_user_id}")
async def payslip(
    run_id: str,
    employee_user_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One payslip. An employee may always read their own."""
    held = await permissions_for(db, user)
    if user.id != employee_user_id and "payroll.report" not in held:
        raise HTTPException(status_code=403, detail="You may only see your own payslip.")

    result = await db.execute(
        select(PayrollLine, PayrollRun, User, EmployeeProfile)
        .join(PayrollRun, PayrollRun.id == PayrollLine.run_id)
        .join(User, User.id == PayrollLine.employee_user_id)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id, isouter=True)
        .where(PayrollLine.run_id == run_id, PayrollLine.employee_user_id == employee_user_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Payslip not found")

    line, run, employee, profile = row
    if run.status not in ("approved", "paid") and user.id == employee_user_id:
        raise HTTPException(status_code=404, detail="This month's payslip is not ready yet.")

    return {
        **line.to_dict(),
        "month": run.month.isoformat(),
        "status": run.status,
        "name": employee.name,
        "employee_no": profile.employee_no if profile else None,
        "designation": profile.designation if profile else None,
    }


# ─── Advances ─────────────────────────────────────────────────────────────────

class AdvanceRequest(BaseModel):
    employee_user_id: str
    amount: Decimal
    instalment: Decimal
    reason: str | None = None
    taken_on: date | None = None


@router.get("/advances")
async def list_advances(
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.structure")),
    db: AsyncSession = Depends(get_db),
    employee_user_id: str | None = None,
):
    stmt = select(EmployeeAdvance, User).join(User, User.id == EmployeeAdvance.employee_user_id)
    if employee_user_id:
        stmt = stmt.where(EmployeeAdvance.employee_user_id == employee_user_id)
    result = await db.execute(stmt.order_by(EmployeeAdvance.created_at.desc()))
    return {
        "advances": [
            {**advance.to_dict(), "name": employee.name}
            for advance, employee in result.all()
        ]
    }


@router.post("/advances")
async def create_advance(
    body: AdvanceRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("payroll.structure")),
    db: AsyncSession = Depends(get_db),
):
    if body.amount <= 0 or body.instalment <= 0:
        raise HTTPException(status_code=400, detail="The amount and the instalment must be more than zero.")
    if body.instalment > body.amount:
        raise HTTPException(status_code=400, detail="The instalment cannot be more than the advance.")

    advance = EmployeeAdvance(
        employee_user_id=body.employee_user_id,
        amount=money(body.amount),
        instalment=money(body.instalment),
        outstanding=money(body.amount),
        reason=body.reason,
        taken_on=body.taken_on or date.today(),
        approved_by=user.id,
    )
    db.add(advance)
    await db.flush()
    audit.record(db, actor=user, entity_type="employee_advance", action="granted",
                 entity_id=advance.id, new_value=advance.to_dict())
    await db.commit()
    return advance.to_dict()


# ─── Personnel file ───────────────────────────────────────────────────────────

class DocumentRequest(BaseModel):
    employee_user_id: str
    doc_type: str = "other"
    title: str
    issue_date: date | None = None
    note: str | None = None


@router.get("/documents/{employee_user_id}")
async def list_documents(
    employee_user_id: str,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("employee.sensitive")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EmployeeDocument)
        .where(EmployeeDocument.employee_user_id == employee_user_id)
        .order_by(EmployeeDocument.created_at.desc())
    )
    return {"documents": [d.to_dict() for d in result.scalars().all()]}


@router.post("/documents")
async def record_document(
    body: DocumentRequest,
    _: User = Depends(erp_available),
    user: User = Depends(require_permission("employee.sensitive")),
    db: AsyncSession = Depends(get_db),
):
    """Record a document in the personnel file.

    The file itself is uploaded separately through the storage service; this
    records that it exists, what it is, and when it was issued.
    """
    document = EmployeeDocument(**body.model_dump(), uploaded_by=user.id)
    db.add(document)
    await db.flush()
    audit.record(db, actor=user, entity_type="employee_document", action="added",
                 entity_id=document.id,
                 new_value={"employee": body.employee_user_id, "type": body.doc_type,
                            "title": body.title})
    await db.commit()
    return document.to_dict()

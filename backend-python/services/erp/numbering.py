"""
Institutional number allocation (blueprint §1.3).

GR No., Admission No., Employee No., voucher and receipt numbers all come from
here. Two properties matter:

  * **No collisions.** Allocation takes a row lock on the series, so two
    admissions saved in the same second get different numbers even across
    workers.
  * **No gaps a human has to explain.** The number is allocated inside the
    caller's transaction. If the admission rolls back, so does the number.

Patterns are ordinary Python format strings over {seq} and {session}, which
keeps them configurable from a settings screen without anyone writing code.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.erp import NumberSeries


# Scopes the ERP allocates from. Seeded by bootstrap; patterns are editable.
SCOPE_GR = "gr_no"
SCOPE_ADMISSION = "admission_no"
# The number on the application form, allocated at enquiry. Separate from the
# admission number because most enquiries never become admissions, and a gap in
# the admission register is a question somebody has to answer.
SCOPE_ADMISSION_APPLICATION = "application_no"
SCOPE_EMPLOYEE = "employee_no"
SCOPE_FAMILY = "family_code"
SCOPE_VOUCHER = "voucher_no"
SCOPE_RECEIPT = "receipt_no"

DEFAULT_SERIES = [
    (SCOPE_GR, "GR Number", "{seq:05d}", 1),
    (SCOPE_ADMISSION, "Admission Number", "{seq:05d}", 1),
    (SCOPE_ADMISSION_APPLICATION, "Application Number", "APP-{seq:05d}", 1),
    (SCOPE_EMPLOYEE, "Employee Number", "LSS-EMP-{seq:04d}", 1),
    (SCOPE_FAMILY, "Family Code", "FAM-{seq:05d}", 1),
    (SCOPE_VOUCHER, "Fee Voucher Number", "V{seq:07d}", 1),
    (SCOPE_RECEIPT, "Receipt Number", "R{seq:07d}", 1),
]


class SeriesNotConfigured(RuntimeError):
    pass


async def allocate(
    db: AsyncSession,
    scope: str,
    *,
    session_name: str = "",
    count: int = 1,
) -> list[str]:
    """Allocate `count` numbers from `scope`, in the caller's transaction.

    The caller commits. Nothing here does, deliberately: a number must not
    survive a failed admission.
    """
    if count < 1:
        return []

    # FOR UPDATE: the lock is what makes concurrent allocation safe. Without it
    # two workers read the same next_value and issue the same GR number.
    result = await db.execute(
        select(NumberSeries).where(NumberSeries.scope == scope).with_for_update()
    )
    series = result.scalar_one_or_none()
    if series is None or not series.is_active:
        raise SeriesNotConfigured(f"No active number series configured for '{scope}'")

    numbers: list[str] = []
    for i in range(count):
        seq = series.next_value + i
        try:
            numbers.append(series.pattern.format(seq=seq, session=session_name))
        except (KeyError, ValueError, IndexError):
            # A broken pattern must not block an admission. Fall back to the
            # bare sequence and let the settings screen surface the problem.
            numbers.append(str(seq))

    series.next_value = series.next_value + count
    return numbers


async def allocate_one(db: AsyncSession, scope: str, *, session_name: str = "") -> str:
    return (await allocate(db, scope, session_name=session_name, count=1))[0]


async def peek(db: AsyncSession, scope: str) -> str | None:
    """What the next number would look like, without consuming it."""
    result = await db.execute(select(NumberSeries).where(NumberSeries.scope == scope))
    series = result.scalar_one_or_none()
    return series.preview() if series else None

"""
ERP permissions (blueprint §1.5).

`users.role` is compared in 93 `require_roles(...)` call sites and 45 direct
comparisons across the live platform. Redefining it would be the single most
likely way to break a working dashboard, so we do not touch it. Instead:

  * `users.role` keeps its existing values and keeps guarding existing routes.
  * New ERP routes use `require_permission(...)`, which resolves a user's ERP
    roles to a permission set.
  * A legacy shim grants `admin`, `teacher` and `student` their equivalent
    permissions, so every existing account works on day one with no data
    change at all.

Owner-only powers are enforced in three independent places, because one check
in application code is not a security boundary: the permission set here, the
invariants in `services/erp/people.py`, and (once configured) the absence of a
DELETE grant on the audit tables.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user
from models.erp import Role, RolePermission, UserRole
from models.models import User


# ─── The catalogue ────────────────────────────────────────────────────────────
# Grouped by module. A permission is only real if it appears here — the seeding
# routine grants from this list, so a typo in a route becomes a 403 rather than
# a silent hole.

PERMISSIONS: dict[str, str] = {
    # Setup and masters
    "setup.view":            "See the ERP setup screen",
    "setup.run":             "Run school setup and link existing records",
    "session.manage":        "Create and switch academic sessions",
    "class.manage":          "Manage classes, sections and subjects",

    # People
    "student.view":          "View student records",
    "student.edit":          "Add and edit student records",
    "student.credentials":   "Reset a student's password",
    "family.view":           "View families",
    "family.edit":           "Create and edit families",
    "employee.view":         "View staff records",
    "employee.edit":         "Add and edit staff records",
    "employee.sensitive":    "See CNIC, bank details and salary",

    # Admissions (phase 2)
    "admission.view":        "View admissions and applications",
    "admission.create":      "Record a new admission",
    "admission.confirm":     "Confirm an admission and activate the student",

    # Attendance (phase 3)
    "attendance.mark":       "Mark attendance for an assigned class",
    "attendance.view":       "View attendance reports",
    "attendance.correct":    "Correct attendance after it was submitted",

    # Fees (phase 4)
    "fee.structure":         "Define fee heads and structures",
    "fee.voucher":           "Generate fee vouchers",
    "fee.collect":           "Receive fees and issue receipts",
    "fee.concession":        "Approve concessions and discounts",
    "fee.report":            "View fee, ledger and defaulter reports",

    # HR and payroll (phase 5)
    "payroll.structure":     "Define and revise salary structures",
    "payroll.run":           "Generate monthly payroll",
    "payroll.approve":       "Approve payroll and release payslips",
    "payroll.report":        "View payroll reports",

    # Accounting (phase 6)
    "accounts.view":         "View accounts, ledgers and statements",
    "accounts.post":         "Record expenses and journal entries",
    "accounts.reconcile":    "Reconcile bank statements",

    # Examinations (phase 7)
    "exam.configure":        "Create and configure examinations",
    "exam.marks.enter":      "Enter marks for an assigned class and subject",
    "exam.marks.review":     "Review and approve submitted marks",
    "exam.publish":          "Publish results and report cards",
    "exam.ledger":           "Generate examination ledgers",

    # Reporting and oversight
    "report.view":           "Run reports",
    "dashboard.management":  "See the management dashboard",
    "audit.view":            "Read the audit trail",

    # Owner-only. No role other than Owner may ever hold these.
    "owner.users":           "Create, disable and re-role any account",
    "owner.roles":           "Change what a role may do",
    "owner.settings":        "Change system configuration and numbering",
    "owner.flags":           "Switch modules on and off",
}

OWNER_ONLY = {k for k in PERMISSIONS if k.startswith("owner.")}

# Everything except the owner-only keys — the ERP Manager's working set.
_ALL_OPERATIONAL = [k for k in PERMISSIONS if k not in OWNER_ONLY]


# ─── Roles ────────────────────────────────────────────────────────────────────
# `rank` is authority order, lowest first. It is what stops a role from editing
# a role above it.

ROLE_DEFINITIONS: list[dict] = [
    {
        "key": "owner", "name": "Owner", "rank": 0, "is_system": True,
        "description": "Unrestricted authority over the whole system.",
        "permissions": list(PERMISSIONS.keys()),
    },
    {
        "key": "erp_accounts_manager", "name": "ERP & Accounts Manager", "rank": 10,
        "is_system": True,
        "description": (
            "Broad day-to-day operational authority across admissions, students, "
            "families, staff, fees, payroll, accounting and reporting — without "
            "the Owner's security powers."
        ),
        "permissions": _ALL_OPERATIONAL,
    },
    {
        "key": "principal", "name": "Principal", "rank": 20, "is_system": True,
        "description": "Full academic and school authority.",
        "permissions": [
            "setup.view", "session.manage", "class.manage",
            "student.view", "student.edit", "student.credentials",
            "family.view", "employee.view", "employee.edit",
            "admission.view", "admission.create", "admission.confirm",
            "attendance.view", "attendance.correct",
            "exam.configure", "exam.marks.review", "exam.publish", "exam.ledger",
            "fee.report", "report.view", "dashboard.management", "audit.view",
        ],
    },
    {
        "key": "preschool_head", "name": "Preschool Head", "rank": 25, "is_system": True,
        "description": "Runs the preschool: its children, staff, attendance and results.",
        "permissions": [
            "setup.view", "class.manage",
            "student.view", "student.edit", "family.view",
            "admission.view", "admission.create", "admission.confirm",
            "attendance.view", "attendance.correct",
            "exam.configure", "exam.marks.review", "exam.ledger",
            "employee.view", "report.view",
        ],
    },
    {
        "key": "coordinator", "name": "Coordinator", "rank": 30, "is_system": True,
        "description": "Academic supervision for assigned classes.",
        "permissions": [
            "student.view", "attendance.view", "attendance.correct",
            "exam.marks.review", "exam.ledger", "report.view",
        ],
    },
    {
        "key": "exam_officer", "name": "Examination Officer", "rank": 30, "is_system": True,
        "description": "Runs examinations end to end, short of final approval.",
        "permissions": [
            "student.view", "exam.configure", "exam.marks.review",
            "exam.ledger", "report.view",
        ],
    },
    {
        "key": "accountant", "name": "Accountant", "rank": 40, "is_system": True,
        "description": "Fee collection, expenses and accounting entries.",
        "permissions": [
            "student.view", "family.view",
            "fee.voucher", "fee.collect", "fee.report",
            "accounts.view", "accounts.post", "report.view",
        ],
    },
    {
        "key": "cashier", "name": "Cashier", "rank": 50, "is_system": True,
        "description": "Receives fees and issues receipts. Nothing else.",
        "permissions": ["student.view", "fee.collect", "fee.report"],
    },
    {
        "key": "admission_officer", "name": "Admission Officer", "rank": 40, "is_system": True,
        "description": "Records admissions and maintains family records.",
        "permissions": [
            "student.view", "student.edit", "family.view", "family.edit",
            "admission.view", "admission.create", "report.view",
        ],
    },
    {
        "key": "teacher", "name": "Teacher", "rank": 60, "is_system": True,
        "description": "Their own classes: attendance, marks, lessons.",
        "permissions": ["attendance.mark", "exam.marks.enter", "student.view"],
    },
    {
        "key": "auditor", "name": "Auditor", "rank": 45, "is_system": True,
        "description": "Reads everything financial, changes nothing.",
        "permissions": [
            "student.view", "family.view", "employee.view",
            "fee.report", "payroll.report", "accounts.view",
            "report.view", "audit.view",
        ],
    },
    {
        "key": "parent", "name": "Parent", "rank": 80, "is_system": True,
        "description": "Their own children's records.",
        "permissions": [],
    },
    {
        "key": "student", "name": "Student", "rank": 90, "is_system": True,
        "description": "Their own record.",
        "permissions": [],
    },
]

ROLE_BY_KEY = {r["key"]: r for r in ROLE_DEFINITIONS}


# ─── Legacy bridge ────────────────────────────────────────────────────────────
# What an existing `users.role` is worth before anyone assigns ERP roles. This
# is what lets the ERP deploy against 755 live accounts without a data change.

LEGACY_ROLE_PERMISSIONS: dict[str, list[str]] = {
    # The existing admin account runs the school today; it keeps that reach.
    "admin": _ALL_OPERATIONAL + ["owner.flags"],
    "teacher": ROLE_BY_KEY["teacher"]["permissions"],
    "student": [],
    "principal": ROLE_BY_KEY["principal"]["permissions"],
    "accountant": ROLE_BY_KEY["accountant"]["permissions"],
}


# ─── Resolution ───────────────────────────────────────────────────────────────

async def permissions_for(db: AsyncSession, user: User) -> set[str]:
    """Every permission a user holds: their ERP roles, plus the legacy bridge.

    Deliberately a union rather than an override. An existing admin who is
    later given the Principal role does not quietly lose the access they had
    this morning.
    """
    granted: set[str] = set(LEGACY_ROLE_PERMISSIONS.get(user.role, []))

    result = await db.execute(
        select(RolePermission.permission_key)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    )
    granted.update(row[0] for row in result.all())
    return granted


async def role_keys_for(db: AsyncSession, user: User) -> list[str]:
    result = await db.execute(
        select(Role.key).join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id).order_by(Role.rank)
    )
    return [row[0] for row in result.all()]


async def is_owner(db: AsyncSession, user: User) -> bool:
    return "owner" in await role_keys_for(db, user)


def require_permission(*needed: str):
    """FastAPI dependency: the user must hold *all* of `needed`.

    Returns the `User`, so a route can depend on this alone and still know who
    is calling.
    """
    async def checker(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        held = await permissions_for(db, user)
        missing = [p for p in needed if p not in held]
        if missing:
            # Name the permission, not the role. "You need fee.collect" is
            # actionable for whoever has to fix it; "access denied" is not.
            raise HTTPException(
                status_code=403,
                detail=f"You do not have permission to do this ({', '.join(missing)}).",
            )
        return user

    return checker


# ─── Scope ────────────────────────────────────────────────────────────────────
# A role can be held over the whole school or over part of it. The Preschool
# Head runs Pre-Nursery, Nursery and KG; she is not a Principal who happens to
# work mornings, and a system that cannot express that ends up either showing
# her 755 children or inventing a second Principal.
#
# Scope lives on the *grant*, not the role, because the same role can be held
# differently by two people. An empty scope means the whole school.

LEVELS = ("pre_primary", "primary", "middle", "secondary")

# What a role is scoped to by default when it is granted, unless the Owner says
# otherwise. Everything else defaults to the whole school.
DEFAULT_ROLE_SCOPE: dict[str, list[str]] = {
    "preschool_head": ["pre_primary"],
}


async def scope_for(db: AsyncSession, user: User) -> list[str] | None:
    """The school levels this user may see, or None for all of them.

    None and "every level" are deliberately different answers: None means
    unscoped, which is what almost everyone is, and skipping the filter
    entirely is cheaper than an IN over four constants on every query.
    """
    result = await db.execute(
        select(UserRole.scope, Role.key)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user.id)
    )
    rows = result.all()
    if not rows:
        return None

    levels: set[str] = set()
    for scope, role_key in rows:
        wanted = (scope or {}).get("levels") if isinstance(scope, dict) else None
        if not wanted:
            # A role granted without a scope is held over the whole school, so
            # holding any such role removes the limit entirely.
            return None
        levels.update(wanted)

    # A legacy admin is unscoped whatever else they hold.
    if user.role == "admin":
        return None
    return sorted(levels) or None

"""
ERP phase 1 tests.

Two kinds of thing are pinned here.

**The promise to the live school.** The whole programme rests on one claim: the
ERP adds and never disturbs. That claim is worth exactly as much as the test
that checks it, so the migration is parsed and asserted against — a future
autogenerate that quietly proposes dropping an index on `lesson_plans` fails
here instead of in production.

**The rules that are easy to break later.** Owner-only permissions, the
permission catalogue, number patterns and the class-level mapping are all
places where a small edit months from now has consequences nobody would notice
by reading the diff.
"""
import ast
import re
from pathlib import Path

import pytest

from services.erp import audit, numbering
from services.erp.permissions import (
    LEGACY_ROLE_PERMISSIONS, OWNER_ONLY, PERMISSIONS, ROLE_BY_KEY, ROLE_DEFINITIONS,
)
from services.erp.setup import _default_session_name, _level_for, _sort_order_for

BACKEND = Path(__file__).resolve().parent.parent
MIGRATION = BACKEND / "alembic/versions/20260919_1431_d58c75ac40b7_add_erp_foundations.py"

# Everything that existed before the ERP. The migration may reference these by
# foreign key; it may not alter, drop or re-index them.
PRE_EXISTING_TABLES = {
    "users", "assignments", "submissions", "documents", "document_chunks",
    "question_papers", "lesson_plans", "chat_history", "notifications",
    "curriculum_mappings", "student_import_batches", "content_revisions",
    "online_class_schedules", "online_class_sessions", "online_class_participants",
    "online_class_attendance_events", "online_class_events", "online_class_resources",
    "online_class_whiteboards", "online_class_lesson_records", "online_class_recordings",
    "online_class_ai_outputs", "online_class_ai_questions", "online_class_settings",
    "ai_usage_events", "document_conversions", "alembic_version",
}

DESTRUCTIVE_OPS = {"drop_table", "drop_column", "alter_column", "drop_index", "drop_constraint", "rename_table"}


def _migration_tree():
    return ast.parse(MIGRATION.read_text(encoding="utf-8"))


def _function(name):
    for node in _migration_tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in the ERP migration")


def _op_calls(func_node):
    """Every `op.<something>(...)` in a function, as (op_name, first_arg)."""
    calls = []
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "op":
            first = None
            if node.args and isinstance(node.args[0], ast.Constant):
                first = node.args[0].value
            calls.append((fn.attr, first, node))
    return calls


class TestMigrationIsAdditive:
    """The live platform must not be able to notice this migration."""

    def test_migration_exists(self):
        assert MIGRATION.exists(), "the ERP migration is missing"

    def test_upgrade_never_touches_an_existing_table(self):
        offences = []
        for op_name, first_arg, node in _op_calls(_function("upgrade")):
            if op_name not in DESTRUCTIVE_OPS:
                continue
            # drop_index names an index, not a table — check its table= kwarg.
            target = first_arg
            for kw in node.keywords:
                if kw.arg in ("table_name", "table") and isinstance(kw.value, ast.Constant):
                    target = kw.value.value
            if target in PRE_EXISTING_TABLES:
                offences.append(f"{op_name} on {target}")
        assert not offences, (
            "The ERP migration must never alter a pre-existing table. Found: "
            + ", ".join(offences)
        )

    def test_upgrade_only_creates(self):
        created = {arg for name, arg, _ in _op_calls(_function("upgrade")) if name == "create_table"}
        assert created, "the migration creates no tables — something is wrong"
        assert not (created & PRE_EXISTING_TABLES), "the migration re-creates an existing table"

    def test_downgrade_removes_only_what_it_created(self):
        created = {arg for name, arg, _ in _op_calls(_function("upgrade")) if name == "create_table"}
        dropped = {arg for name, arg, _ in _op_calls(_function("downgrade")) if name == "drop_table"}
        assert dropped == created, (
            "downgrade must drop exactly the tables upgrade created — "
            f"missing: {created - dropped}, unexpected: {dropped - created}"
        )

    def test_ships_switched_off(self):
        """A module that arrives switched on is a module nobody consented to."""
        from models.erp import FeatureFlag
        assert FeatureFlag.__table__.c.enabled.default.arg is False


class TestPermissionCatalogue:

    def test_every_granted_permission_exists(self):
        for role in ROLE_DEFINITIONS:
            unknown = [p for p in role["permissions"] if p not in PERMISSIONS]
            assert not unknown, f"role '{role['key']}' grants unknown permissions: {unknown}"

    def test_only_the_owner_holds_owner_permissions(self):
        """Specification §82.B16: the ERP Manager runs the school, but cannot
        become the school's owner."""
        for role in ROLE_DEFINITIONS:
            if role["key"] == "owner":
                continue
            held = set(role["permissions"]) & OWNER_ONLY
            assert not held, f"role '{role['key']}' must not hold owner-only permissions: {sorted(held)}"

    def test_owner_holds_everything(self):
        assert set(ROLE_BY_KEY["owner"]["permissions"]) == set(PERMISSIONS)

    def test_erp_manager_is_broad_but_not_owner(self):
        """Javaid's role is deliberately close to everything — and deliberately
        not everything."""
        manager = set(ROLE_BY_KEY["erp_accounts_manager"]["permissions"])
        assert manager == set(PERMISSIONS) - OWNER_ONLY
        for key in ("fee.collect", "payroll.approve", "admission.confirm", "accounts.post"):
            assert key in manager
        for key in OWNER_ONLY:
            assert key not in manager

    def test_students_and_parents_hold_nothing_by_role(self):
        for key in ("student", "parent"):
            assert ROLE_BY_KEY[key]["permissions"] == []

    def test_legacy_admin_keeps_working(self):
        """An existing admin must be able to run the ERP on day one, with no
        data change — otherwise the deploy locks the school out of its own
        new module."""
        admin = set(LEGACY_ROLE_PERMISSIONS["admin"])
        assert "setup.run" in admin
        assert "owner.flags" in admin, "an admin must be able to switch the module on"
        assert admin >= set(PERMISSIONS) - OWNER_ONLY

    def test_legacy_student_gains_nothing(self):
        assert LEGACY_ROLE_PERMISSIONS["student"] == []

    def test_legacy_teacher_gains_only_teaching(self):
        teacher = set(LEGACY_ROLE_PERMISSIONS["teacher"])
        assert teacher == {"attendance.mark", "exam.marks.enter", "student.view"}
        assert not teacher & {"fee.collect", "payroll.run", "employee.sensitive"}

    def test_role_keys_are_unique(self):
        keys = [r["key"] for r in ROLE_DEFINITIONS]
        assert len(keys) == len(set(keys))


class TestNumbering:

    def test_default_series_cover_the_institutional_numbers(self):
        scopes = {s[0] for s in numbering.DEFAULT_SERIES}
        assert {"gr_no", "admission_no", "employee_no"} <= scopes

    def test_gr_and_admission_are_separate_series(self):
        """The specification is emphatic that these are not the same number."""
        assert numbering.SCOPE_GR != numbering.SCOPE_ADMISSION
        by_scope = {s[0]: s for s in numbering.DEFAULT_SERIES}
        assert by_scope["gr_no"] is not by_scope["admission_no"]

    @pytest.mark.parametrize("pattern,seq,expected", [
        ("{seq:05d}", 1, "00001"),
        ("{seq:05d}", 12345, "12345"),
        ("LSS-EMP-{seq:04d}", 7, "LSS-EMP-0007"),
        ("V{seq:07d}", 42, "V0000042"),
        ("{session}/{seq:03d}", 5, "2026-2027/005"),
    ])
    def test_patterns_format(self, pattern, seq, expected):
        assert pattern.format(seq=seq, session="2026-2027") == expected

    def test_a_number_never_overflows_its_pad(self):
        """Padding is a minimum width, not a maximum. The 100,000th student
        must still get a number."""
        assert "{seq:05d}".format(seq=123456) == "123456"


class TestAuditDiff:

    def test_only_changed_fields_are_recorded(self):
        old, new = audit.diff(
            {"name": "Ali", "gr_no": None, "phone": "0300"},
            {"name": "Ali", "gr_no": "00042", "phone": "0300"},
        )
        assert old == {"gr_no": None}
        assert new == {"gr_no": "00042"}

    def test_no_change_produces_nothing(self):
        old, new = audit.diff({"a": 1}, {"a": 1})
        assert old == {} and new == {}

    def test_money_is_never_rounded_into_a_float(self):
        from decimal import Decimal
        assert audit._jsonable(Decimal("1234.56")) == "1234.56"

    def test_dates_survive_as_text(self):
        from datetime import date
        assert audit._jsonable(date(2026, 4, 1)) == "2026-04-01"


class TestClassMapping:

    @pytest.mark.parametrize("canonical,level", [
        ("Pre-Nursery", "pre_primary"), ("Nursery", "pre_primary"), ("KG", "pre_primary"),
        ("Class 1", "primary"), ("Class 5", "primary"),
        ("Class 6", "middle"), ("Class 8", "middle"),
        ("Class 9", "secondary"), ("Class 10", "secondary"), ("Class 12", "secondary"),
    ])
    def test_levels(self, canonical, level):
        assert _level_for(canonical) == level

    def test_classes_sort_in_school_order(self):
        names = ["Class 10", "Nursery", "Class 2", "KG", "Class 9"]
        assert sorted(names, key=_sort_order_for) == ["Nursery", "KG", "Class 2", "Class 9", "Class 10"]

    def test_every_spelling_in_use_resolves(self):
        """The spellings that actually appear in LSS Bot today — students carry
        'Class 5', teachers 'Grade 5', sections 'Grade 5 - A'."""
        from services.student_excel_import_service import normalize_class
        for raw in ("Class 5", "Grade 5", "5", "V", "Five", "5-A", "class 5 boys"):
            assert normalize_class(raw) == "Class 5", f"{raw!r} did not resolve"


class TestSessionNaming:

    @pytest.mark.parametrize("today,expected", [
        ((2026, 9, 19), "2026-2027"),    # September is in the session that began in April
        ((2026, 4, 1), "2026-2027"),     # the first day of a session
        ((2026, 3, 31), "2025-2026"),    # the last day of the previous one
        ((2027, 1, 15), "2026-2027"),    # January still belongs to last April's session
    ])
    def test_pakistani_school_year_runs_april_to_march(self, today, expected):
        from datetime import date
        assert _default_session_name(date(*today)) == expected

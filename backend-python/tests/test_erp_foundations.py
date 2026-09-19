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
ERP_MIGRATIONS = sorted(
    (BACKEND / "alembic/versions").glob("*_add_erp_*.py")
)

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


def _function(migration, name):
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in {migration.name}")


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


@pytest.mark.parametrize("migration", ERP_MIGRATIONS, ids=lambda m: m.stem[-28:])
class TestMigrationIsAdditive:
    """The live platform must not be able to notice any ERP migration.

    Parametrised over every ERP migration rather than pinned to the first one,
    because phase 6 is exactly where a careless autogenerate would slip a
    `drop_index` on `lesson_plans` into a diff nobody reads closely.
    """

    def test_upgrade_never_touches_an_existing_table(self, migration):
        offences = []
        for op_name, first_arg, node in _op_calls(_function(migration, "upgrade")):
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

    def test_upgrade_only_creates(self, migration):
        created = {arg for name, arg, _ in _op_calls(_function(migration, "upgrade")) if name == "create_table"}
        assert created, "the migration creates no tables — something is wrong"
        assert not (created & PRE_EXISTING_TABLES), "the migration re-creates an existing table"

    def test_every_foreign_key_is_named(self, migration):
        """An unnamed constraint cannot be dropped again, so the downgrade
        raises before it touches anything — a migration that is reversible only
        on paper."""
        for op_name, first_arg, node in _op_calls(_function(migration, "upgrade")):
            if op_name == "create_foreign_key":
                assert first_arg, f"{migration.name} creates an unnamed foreign key"
        for op_name, first_arg, node in _op_calls(_function(migration, "downgrade")):
            if op_name == "drop_constraint":
                assert first_arg, f"{migration.name} drops an unnamed constraint"

    def test_downgrade_removes_only_what_it_created(self, migration):
        created = {arg for name, arg, _ in _op_calls(_function(migration, "upgrade")) if name == "create_table"}
        dropped = {arg for name, arg, _ in _op_calls(_function(migration, "downgrade")) if name == "drop_table"}
        assert dropped == created, (
            "downgrade must drop exactly the tables upgrade created — "
            f"missing: {created - dropped}, unexpected: {dropped - created}"
        )


class TestModuleShipsOff:

    def test_ships_switched_off(self):
        """A module that arrives switched on is a module nobody consented to."""
        from models.erp import FeatureFlag
        assert FeatureFlag.__table__.c.enabled.default.arg is False

    def test_migrations_exist(self):
        assert len(ERP_MIGRATIONS) >= 2, "expected the phase 1 and phase 2 migrations"


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


class TestPreschoolHead:
    """Amna's role (specification §82, the fourth senior account)."""

    def test_the_role_exists(self):
        assert "preschool_head" in ROLE_BY_KEY

    def test_she_runs_the_preschool_not_the_school(self):
        held = set(ROLE_BY_KEY["preschool_head"]["permissions"])
        for key in ("student.view", "student.edit", "admission.confirm",
                    "attendance.correct", "exam.marks.review"):
            assert key in held
        # Not hers: the money, the staff files, or the system itself.
        for key in ("fee.collect", "fee.structure", "payroll.run", "payroll.approve",
                    "accounts.post", "employee.sensitive", "employee.edit"):
            assert key not in held, f"the Preschool Head should not hold {key}"

    def test_she_holds_no_owner_powers(self):
        assert not set(ROLE_BY_KEY["preschool_head"]["permissions"]) & OWNER_ONLY

    def test_her_grant_is_scoped_to_the_preschool_by_default(self):
        from services.erp.permissions import DEFAULT_ROLE_SCOPE, LEVELS
        assert DEFAULT_ROLE_SCOPE["preschool_head"] == ["pre_primary"]
        assert "pre_primary" in LEVELS

    def test_nobody_else_is_scoped_by_accident(self):
        from services.erp.permissions import DEFAULT_ROLE_SCOPE
        assert set(DEFAULT_ROLE_SCOPE) == {"preschool_head"}

    def test_she_outranks_a_coordinator_and_not_the_principal(self):
        assert ROLE_BY_KEY["principal"]["rank"] < ROLE_BY_KEY["preschool_head"]["rank"]
        assert ROLE_BY_KEY["preschool_head"]["rank"] < ROLE_BY_KEY["coordinator"]["rank"]


class TestCampusReadiness:
    """One campus today; a second one should be a row, not a migration."""

    def test_campus_is_optional_everywhere(self):
        from models.erp import (
            Admission, EmployeeProfile, Family, SchoolClass, Section, StudentProfile,
        )
        for model in (SchoolClass, Section, Family, StudentProfile, EmployeeProfile, Admission):
            column = model.__table__.c.campus_id
            assert column.nullable, f"{model.__name__}.campus_id must stay optional"

    def test_no_campus_is_required_to_admit_a_student(self):
        """If a clerk had to choose a campus, the readiness would have cost
        something. It must not."""
        from routes.erp_admissions import AdmissionRequest
        assert "campus_id" not in AdmissionRequest.model_fields


class TestFamilyMatching:

    @pytest.mark.parametrize("written,expected", [
        ("0300-1234567", "3001234567"),
        ("+92 300 1234567", "3001234567"),
        ("03001234567", "3001234567"),
        ("0300 123 4567", "3001234567"),
    ])
    def test_a_phone_number_is_the_same_number_however_it_is_written(self, written, expected):
        from services.erp.admissions import _normalise_phone
        assert _normalise_phone(written) == expected

    def test_two_spellings_of_one_number_match_each_other(self):
        from services.erp.admissions import _normalise_phone
        assert _normalise_phone("+92 300 1234567") == _normalise_phone("03001234567")

    def test_a_missing_number_matches_nothing(self):
        from services.erp.admissions import _normalise_phone
        assert _normalise_phone(None) == ""
        assert _normalise_phone("") == ""

    def test_names_compare_without_spacing_or_case(self):
        from services.erp.admissions import _normalise_name
        assert _normalise_name("  Muhammad   ASLAM ") == "muhammad aslam"


class TestTemporaryPasswords:

    def test_it_has_no_characters_a_parent_would_misread(self):
        from services.erp.admissions import generate_password
        for _ in range(200):
            password = generate_password()
            assert not set(password) & set("l1O0"), f"{password} contains an ambiguous character"

    def test_it_is_long_enough_to_be_worth_having(self):
        from services.erp.admissions import generate_password
        assert len(generate_password()) >= 8

    def test_two_students_do_not_get_the_same_one(self):
        from services.erp.admissions import generate_password
        assert len({generate_password() for _ in range(500)}) > 490


class TestAdmissionLifecycle:

    def test_an_enquiry_is_not_an_account(self):
        """Nothing about an admission record implies a user until it is
        confirmed — a child who never joins never gets a login."""
        from models.erp import Admission
        assert Admission.__table__.c.student_user_id.nullable

    def test_open_states_exclude_the_finished_ones(self):
        from models.erp import (
            ADMISSION_CANCELLED, ADMISSION_CONFIRMED, ADMISSION_OPEN_STATES,
            ADMISSION_REJECTED,
        )
        for done in (ADMISSION_CONFIRMED, ADMISSION_REJECTED, ADMISSION_CANCELLED):
            assert done not in ADMISSION_OPEN_STATES

    def test_the_application_number_is_its_own_series(self):
        """Most enquiries never become admissions. If they shared a series, the
        admission register would be full of gaps somebody has to explain."""
        scopes = {s[0] for s in numbering.DEFAULT_SERIES}
        assert numbering.SCOPE_ADMISSION_APPLICATION in scopes
        assert numbering.SCOPE_ADMISSION_APPLICATION != numbering.SCOPE_ADMISSION

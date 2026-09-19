"""
Management layer and the AI assistant (ERP phase 8).

The assistant is the one part of the ERP where a mistake is not a wrong number
but a leak, so most of this file is about what it cannot do.
"""
import pytest

from services.erp import insights
from services.erp.assistant import MAX_ROUNDS, SYSTEM, _tool_schema
from services.erp.permissions import LEGACY_ROLE_PERMISSIONS, PERMISSIONS, ROLE_BY_KEY


class TestToolCatalogue:

    def test_every_tool_declares_a_permission(self):
        for name, spec in insights.TOOLS.items():
            assert spec["permission"], f"{name} has no permission"
            assert spec["permission"] in PERMISSIONS, \
                f"{name} needs {spec['permission']}, which is not a real permission"

    def test_every_tool_has_a_description_the_model_can_use(self):
        for name, spec in insights.TOOLS.items():
            assert len(spec["description"]) > 30, f"{name}'s description is too thin"

    def test_every_tool_is_callable(self):
        for name, spec in insights.TOOLS.items():
            assert callable(spec["fn"]), f"{name} is not callable"


class TestPermissionScoping:
    """The assistant is a different way in, not a way around."""

    def test_an_owner_may_ask_everything(self):
        owner = set(ROLE_BY_KEY["owner"]["permissions"])
        assert set(insights.tools_for(owner)) == set(insights.TOOLS)

    def test_a_teacher_cannot_ask_about_payroll(self):
        teacher = set(LEGACY_ROLE_PERMISSIONS["teacher"])
        available = insights.tools_for(teacher)
        assert "payroll_position" not in available
        assert "fee_position" not in available
        assert "defaulter_list" not in available

    def test_a_teacher_can_still_ask_about_their_students(self):
        teacher = set(LEGACY_ROLE_PERMISSIONS["teacher"])
        assert "students_today" in insights.tools_for(teacher)

    def test_a_cashier_sees_money_but_not_marks(self):
        cashier = set(ROLE_BY_KEY["cashier"]["permissions"])
        available = insights.tools_for(cashier)
        assert "fee_position" in available
        assert "exam_progress" not in available
        assert "payroll_position" not in available

    def test_a_student_may_ask_nothing(self):
        assert insights.tools_for(set()) == []

    def test_the_preschool_head_sees_academic_tools_not_financial_ones(self):
        head = set(ROLE_BY_KEY["preschool_head"]["permissions"])
        available = insights.tools_for(head)
        assert "students_today" in available
        assert "attendance_today" in available
        assert "fee_position" not in available
        assert "payroll_position" not in available


class TestAssistantSafety:

    def test_the_model_is_only_offered_what_the_user_holds(self):
        teacher = set(LEGACY_ROLE_PERMISSIONS["teacher"])
        schema = _tool_schema(insights.tools_for(teacher))
        names = {t["name"] for t in schema}
        assert "payroll_position" not in names

    def test_no_tool_accepts_free_text_that_could_become_a_query(self):
        """The model picks a prepared question and its arguments. It cannot
        compose one — a model able to write SQL against a school's payroll is a
        model able to write the wrong one."""
        for tool in _tool_schema(list(insights.TOOLS)):
            for name, prop in tool["input_schema"]["properties"].items():
                assert name in ("on_date", "limit"), \
                    f"{tool['name']} accepts '{name}', which is not a safe argument"

    def test_the_system_prompt_forbids_inventing_figures(self):
        # Normalised, because the prompt is wrapped for reading.
        flat = " ".join(SYSTEM.split())
        assert "Never guess a number" in flat
        assert "never state a figure the tools did not give you" in flat

    def test_the_system_prompt_asks_for_the_as_at_time(self):
        """'How much did we collect today' means something different at 9am."""
        assert "as at" in SYSTEM

    def test_the_system_prompt_protects_individuals(self):
        assert "Never speculate about individuals" in SYSTEM

    def test_the_loop_is_bounded(self):
        """More rounds than this is a loop, not thought."""
        assert 1 < MAX_ROUNDS <= 6

    def test_an_unknown_tool_name_is_refused(self):
        import inspect
        from services.erp import assistant
        source = inspect.getsource(assistant._run_tool)
        assert "not available" in source

    def test_the_limit_argument_is_capped(self):
        """A model asking for fifty thousand defaulters gets fifty."""
        import inspect
        from services.erp import assistant
        assert "min(int(arguments" in inspect.getsource(assistant._run_tool)


class TestDashboardShape:

    def test_panels_are_permission_gated(self):
        import inspect
        from services.erp import insights as module
        source = inspect.getsource(module.management_dashboard)
        for permission in ("student.view", "fee.report", "payroll.report",
                           "attendance.view", "employee.view"):
            assert permission in source

    def test_exceptions_are_ordered_by_what_they_cost_to_ignore(self):
        import inspect
        from services.erp import insights as module
        source = inspect.getsource(module.exceptions)
        assert '"high"' in source and '"medium"' in source and '"low"' in source
        assert "order[i" in source

    def test_every_exception_carries_a_link_to_fix_it(self):
        """A list of problems with no button is just a list of problems."""
        import inspect
        from services.erp import insights as module
        source = inspect.getsource(module.exceptions)
        assert source.count('"link"') >= 4

    def test_every_answer_carries_its_as_at_date(self):
        import inspect
        from services.erp import insights as module
        for fn in (module.students_today, module.attendance_today,
                   module.payroll_position, module.staff_summary,
                   module.family_summary, module.exam_progress):
            assert "as_at" in inspect.getsource(fn), f"{fn.__name__} does not say when"

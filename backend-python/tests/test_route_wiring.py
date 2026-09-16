"""
Route wiring tests.

Every other test in this suite calls handlers directly, which proves the logic
inside them. It does not prove that FastAPI can deliver a request to them — and
that is exactly how the Online Classes launch broke in production: `START CLASS`
returned 422 before a single line of `start_class()` ran, because FastAPI had
decided the request body was a query parameter.

The cause is a two-part trap:

  1. `from __future__ import annotations` turns every annotation in a module
     into a plain string.
  2. `@limiter.limit(...)` wraps the endpoint via `functools.wraps`, which
     copies `__name__`, `__doc__` and `__wrapped__` — but *cannot* copy
     `__globals__`, since that attribute is read-only on a function object.

FastAPI then resolves those strings against the wrapper's `__globals__`, which
belong to `slowapi.extension`. `StartClassRequest` does not exist there, the
annotation stays unresolved, and an unresolved annotation is not recognised as
a Pydantic model — so it is treated as a query parameter. Every POST to that
route fails validation with `{"loc": ["query", "body"], "msg": "Field required"}`
no matter what the client sends, and `/openapi.json` returns 500.

Nothing about that is visible by reading the handler, so it is pinned here.
"""
import ast
import inspect
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from pydantic import BaseModel

ROUTES_DIR = Path(__file__).resolve().parent.parent / "routes"
FUTURE_IMPORT = "from __future__ import annotations"


def _rate_limited_route_modules():
    """Route modules with at least one rate-limited endpoint."""
    return sorted(
        path for path in ROUTES_DIR.glob("*.py")
        if "@limiter.limit" in path.read_text(encoding="utf-8")
    )


RATE_LIMITED_MODULES = _rate_limited_route_modules()


class TestRateLimitedModulesResolveTheirAnnotations:
    def test_the_scan_actually_finds_modules(self):
        """Guard the guard: a rename of the decorator must not quietly empty it."""
        assert RATE_LIMITED_MODULES, f"no @limiter.limit endpoints found under {ROUTES_DIR}"

    @pytest.mark.parametrize("path", RATE_LIMITED_MODULES, ids=lambda p: p.name)
    def test_module_does_not_defer_annotations(self, path):
        # Parsed, not grepped: these modules carry a comment explaining the rule,
        # and a comment about the import is not the import.
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defers = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in ast.walk(tree)
        )
        assert not defers, (
            f"{path.name} rate-limits an endpoint and defers its annotations. "
            "Those two are incompatible: slowapi's wrapper cannot carry this "
            "module's globals, so FastAPI resolves the annotation strings in "
            "slowapi's namespace, fails, and demotes request bodies to query "
            "parameters — every POST to this module then returns 422. Remove "
            f"'{FUTURE_IMPORT}'."
        )


class TestTheFrameworkBehaviourThatCausedIt:
    """Reproduce the trap on a throwaway app, so the rule above is evidence-based.

    If a future FastAPI or slowapi release closes this hole, this test fails and
    the source-level guard can be reconsidered — rather than being carried
    forever as folklore.
    """

    def test_deferred_annotations_lose_the_request_body(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # slowapi reads ./.env at construction
        from slowapi import Limiter
        from slowapi.util import get_remote_address

        limiter = Limiter(key_func=get_remote_address)

        class Payload(BaseModel):
            name: str

        app = FastAPI()

        @app.post("/resolved")
        @limiter.limit("5/minute")
        async def resolved(request: Request, body: Payload):  # real classes
            return {}

        # Exactly what `from __future__ import annotations` produces.
        @app.post("/deferred")
        @limiter.limit("5/minute")
        async def deferred(request: "Request", body: "Payload"):
            return {}

        def locations(path):
            route = next(r for r in app.routes if getattr(r, "path", None) == path)
            return (
                [p.name for p in route.dependant.body_params],
                [p.name for p in route.dependant.query_params],
            )

        assert locations("/resolved") == (["body"], []), (
            "a rate-limited endpoint with real annotations must still read its body"
        )
        assert locations("/deferred") == ([], ["body"]), (
            "deferred annotations under slowapi are expected to demote the body "
            "to a query parameter; if this now passes cleanly, the framework has "
            "been fixed and TestRateLimitedModulesResolveTheirAnnotations can go"
        )


class TestTheRealApp:
    """The app-wide check. Needs the full runtime, so it runs in the container
    (`docker compose exec backend pytest`) and skips on a bare checkout."""

    @staticmethod
    def _app():
        main = pytest.importorskip(
            "main", reason="full backend runtime not installed (run inside the backend image)"
        )
        return main.app

    @staticmethod
    def _annotation(field):
        return getattr(getattr(field, "field_info", None), "annotation", None) or getattr(field, "type_", None)

    def test_no_route_expects_a_pydantic_model_in_the_query_string(self):
        """A model in `query_params` is always the bug above — a client cannot
        satisfy it, so the endpoint is dead on arrival."""
        offenders = []
        for route in self._app().routes:
            for field in getattr(getattr(route, "dependant", None), "query_params", []):
                annotation = self._annotation(field)
                if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
                    offenders.append(f"{sorted(route.methods)} {route.path} → {field.name}")
        assert not offenders, "request bodies demoted to query parameters:\n  " + "\n  ".join(offenders)

    def test_every_declared_request_body_is_reachable(self):
        """The same fault stated positively: a POST/PUT/PATCH route whose handler
        takes a Pydantic parameter must expose it as a body parameter."""
        unreachable = []
        for route in self._app().routes:
            dependant = getattr(route, "dependant", None)
            if dependant is None or not (route.methods & {"POST", "PUT", "PATCH"}):
                continue
            declared = {
                name for name, parameter in inspect.signature(route.endpoint).parameters.items()
                if inspect.isclass(parameter.annotation) and issubclass(parameter.annotation, BaseModel)
            }
            carried = {field.name for field in dependant.body_params}
            for name in declared - carried:
                unreachable.append(f"{sorted(route.methods)} {route.path} → {name}")
        assert not unreachable, "handlers whose request body never arrives:\n  " + "\n  ".join(unreachable)

    def test_the_openapi_schema_can_be_generated(self):
        """`/openapi.json` returned 500 while the wiring was broken — an
        unresolvable annotation has no schema. It is a free canary."""
        schema = self._app().openapi()
        assert schema["paths"]["/api/online-classes/start"]["post"]["requestBody"], (
            "START CLASS must declare a request body"
        )

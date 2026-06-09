"""Route error-CONTRACT guardrail (correctness, not just presence).

`scripts/check_route_metadata.py` enforces that every route DECLARES
`description`/`responses`/`response_model`. It cannot tell whether the declared
HTTP error codes are CORRECT. This test derives the *mechanically-checkable*
reachable error codes for every route and fails when a reachable code is not
declared (or a response shape regresses).

What it derives (high-signal, low false-positive):
  1. Auth-gate dependencies (router- and endpoint-level) -> 401/403.
  2. AST of the handler body (and one level into helpers defined in the same
     module): literal ``raise HTTPException(status_code=N)``, ``raise <Mapped
     DomainException>(...)`` (mapped via EXCEPTION_MAP) and ``validate_permission
     (...)`` calls (-> 403).
  3. Response-shape traps: ``422`` listed in ``responses`` (overrides FastAPI's
     HTTPValidationError); ``response_model=None`` while the return annotation is
     a Pydantic model / TypedDict (erases the success schema).

What it deliberately does NOT do: trace error codes raised deep inside services
/repositories the handler delegates to (e.g. a repo ``UniqueException`` -> 400).
Those need a periodic manual audit / behavioural tests; see
``docs/route-error-contract-plan.md``.

Rollout is a shrink-only ratchet: ``route_error_contract_baseline.json`` records
the currently-tolerated violations so the test is green today and only blocks
NEW (or regressed) routes. Regenerate it with::

    ENEO_ROUTE_CONTRACT_WRITE_BASELINE=1 uv run pytest \
        tests/unit/test_route_error_contract.py -q

The baseline can only shrink: if a baselined route is fixed, the test fails
until the stale entry is removed (regenerate, or set
``ENEO_ROUTE_CONTRACT_ALLOW_STALE=1`` for a mid-burndown commit).
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import textwrap
import typing
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute
from pydantic import BaseModel

from intric.main.exceptions import EXCEPTION_MAP

BASELINE_PATH = Path(__file__).with_name("route_error_contract_baseline.json")

# Dependency __name__ (or require_permission's inner qualname) -> required code.
# These raise HTTPException/UnauthorizedException/AuthenticationException directly
# and are NOT in EXCEPTION_MAP.
AUTH_DEP_CODES: dict[str, int] = {
    "authenticate_super_api_key": 401,
    "authenticate_super_duper_api_key": 401,
    "require_user_for_creation": 403,
    "require_user_identity": 403,
    "require_session_auth": 403,
}
# NOTE: API-key scope/resource/permission deps (_scope_check_dep,
# _resource_permission_dep, _api_key_permission_dep, _stash) are intentionally
# NOT mapped here: some self-filter instead of raising 403, and their contract
# is already covered by the api-key matrix tests. Adding them would create false
# positives. Their 403 behaviour stays out of this guardrail.
# require_permission(...) returns an inner `_dep`; match on qualname to avoid
# colliding with any other generic `_dep`.
REQUIRE_PERMISSION_QUALNAME_FRAGMENT = "require_permission.<locals>"

# Domain exception class name -> HTTP status (from the single source of truth).
EXCEPTION_NAME_TO_CODE: dict[str, int] = {
    exc.__name__: spec[0] for exc, spec in EXCEPTION_MAP.items()
}

# Codes excluded from the declared/required comparison: 2xx successes and 422
# (FastAPI auto-documents validation as HTTPValidationError).
_SUCCESS_AND_VALIDATION = {200, 201, 202, 203, 204, 422}


def _routes() -> list[APIRoute]:
    from intric.server.routers import router

    out: list[APIRoute] = []
    for route in router.routes:
        if isinstance(route, APIRoute) and route.path and route.path != "/":
            out.append(route)
    return out


def _identity(route: APIRoute, method: str) -> str:
    return f"{method} {route.path}"


def _declared_codes(route: APIRoute) -> set[int]:
    codes: set[int] = set()
    for key in route.responses or {}:
        if isinstance(key, int):
            codes.add(key)
        elif isinstance(key, str) and key.isdigit():
            codes.add(int(key))
    return {c for c in codes if c not in _SUCCESS_AND_VALIDATION}


def _dep_callables(route: APIRoute) -> list[Any]:
    callables: list[Any] = []
    for dep in route.dependencies or []:
        fn = getattr(dep, "dependency", None)
        if fn is not None:
            callables.append(fn)

    def walk(dependant: Any) -> None:
        if dependant is None:
            return
        call = getattr(dependant, "call", None)
        if call is not None:
            callables.append(call)
        for sub in getattr(dependant, "dependencies", []) or []:
            walk(sub)

    walk(route.dependant)
    return callables


def _auth_required_codes(route: APIRoute) -> set[int]:
    required: set[int] = set()
    for fn in _dep_callables(route):
        name = getattr(fn, "__name__", "")
        qualname = getattr(fn, "__qualname__", "")
        if REQUIRE_PERMISSION_QUALNAME_FRAGMENT in qualname:
            required.add(403)
        elif name in AUTH_DEP_CODES:
            required.add(AUTH_DEP_CODES[name])
    return required


def _status_const_to_int(node: ast.AST) -> int | None:
    """Resolve a status_code AST node to an int literal if possible."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    # status.HTTP_403_FORBIDDEN -> 403
    if isinstance(node, ast.Attribute) and node.attr.startswith("HTTP_"):
        parts = node.attr.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])
    return None


def _ast_required_codes_from_func(func: Any, *, seen: set[str]) -> set[int]:
    """Codes a function literally raises in its own body, plus one level of
    helper calls into functions defined in the SAME module."""
    required: set[int] = set()
    try:
        src = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(src)
    except (OSError, TypeError, SyntaxError):
        return required

    module = inspect.getmodule(func)
    module_globals = getattr(module, "__dict__", {})
    module_name = getattr(func, "__module__", None)

    helper_calls: set[str] = set()

    for node in ast.walk(tree):
        # raise HTTPException(status_code=...) / raise <DomainException>(...)
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            fn = node.exc.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if fname == "HTTPException":
                for kw in node.exc.keywords:
                    if kw.arg == "status_code":
                        code = _status_const_to_int(kw.value)
                        if code is not None and code not in _SUCCESS_AND_VALIDATION:
                            required.add(code)
            elif fname in EXCEPTION_NAME_TO_CODE:
                code = EXCEPTION_NAME_TO_CODE[fname]
                if code not in _SUCCESS_AND_VALIDATION:
                    required.add(code)
        # validate_permission(...) / validate_permissions(...) -> 403
        if isinstance(node, ast.Call):
            fn = node.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if fname in ("validate_permission", "validate_permissions"):
                required.add(403)
            elif isinstance(fn, ast.Name):
                helper_calls.add(fn.id)

    # One level into same-module helpers (no recursion past this).
    for name in helper_calls:
        target = module_globals.get(name)
        if target is None or name in seen:
            continue
        if not (inspect.isfunction(target) or inspect.iscoroutinefunction(target)):
            continue
        if getattr(target, "__module__", None) != module_name:
            continue
        seen.add(name)
        required |= _ast_required_codes_from_func(target, seen=set(seen))
    return required


def _unwrap_optional(annotation: Any) -> list[Any]:
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(origin) == "types.UnionType":
        return [a for a in typing.get_args(annotation) if a is not type(None)]
    return [annotation]


def _is_model_type(annotation: Any) -> bool:
    for ann in _unwrap_optional(annotation):
        try:
            if isinstance(ann, type) and issubclass(ann, BaseModel):
                return True
        except TypeError:
            pass
        if typing.is_typeddict(ann):
            return True
    return False


def _shape_violations(route: APIRoute) -> list[str]:
    violations: list[str] = []
    if 422 in {k if isinstance(k, int) else None for k in (route.responses or {})}:
        violations.append("forbidden_422_declared")

    if route.response_model is None and (route.status_code or 200) != 204:
        try:
            hints = typing.get_type_hints(route.endpoint)
        except Exception:
            hints = {}
        ret = hints.get("return")
        if ret is not None and _is_model_type(ret):
            violations.append("response_model_none_with_model_return")
    return violations


def _route_violations(route: APIRoute, method: str) -> list[str]:
    declared = _declared_codes(route)
    required = _auth_required_codes(route)
    required |= _ast_required_codes_from_func(route.endpoint, seen=set())

    # 500 is the implicit server-error and is conventionally left undeclared
    # (every broad `except Exception -> HTTPException(500)` would otherwise flag),
    # so it is not required even when a handler raises it literally.
    missing = (required - declared) - {500}
    violations = [f"missing_declared_code:{c}" for c in sorted(missing)]
    violations += _shape_violations(route)
    return sorted(violations)


def _compute_all() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for route in _routes():
        for method in sorted(route.methods or set()):
            if method in ("HEAD", "OPTIONS"):
                continue
            v = _route_violations(route, method)
            if v:
                result[_identity(route, method)] = v
    return result


def _load_baseline() -> dict[str, list[str]]:
    if not BASELINE_PATH.exists():
        return {}
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _write_baseline(current: dict[str, list[str]]) -> None:
    payload: dict[str, Any] = {
        "_comment": (
            "Generated by test_route_error_contract. Each key is 'METHOD /path'; "
            "the list is the tolerated rule-ids for that route. Regenerate with "
            "ENEO_ROUTE_CONTRACT_WRITE_BASELINE=1. Shrink-only: do not add by hand."
        )
    }
    for key in sorted(current):
        payload[key] = current[key]
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_route_error_contract() -> None:
    current = _compute_all()

    if os.environ.get("ENEO_ROUTE_CONTRACT_WRITE_BASELINE"):
        _write_baseline(current)
        return

    baseline = _load_baseline()

    new_violations: dict[str, list[str]] = {}
    for ident, rules in current.items():
        tolerated = set(baseline.get(ident, []))
        fresh = sorted(set(rules) - tolerated)
        if fresh:
            new_violations[ident] = fresh

    stale: dict[str, list[str]] = {}
    if not os.environ.get("ENEO_ROUTE_CONTRACT_ALLOW_STALE"):
        for ident, rules in baseline.items():
            current_rules = set(current.get(ident, []))
            gone = sorted(set(rules) - current_rules)
            if gone:
                stale[ident] = gone

    messages: list[str] = []
    if new_violations:
        messages.append(
            "New route error-contract violations (declare these codes, or fix the "
            "handler):\n"
            + "\n".join(
                f"  {k}: {', '.join(v)}" for k, v in sorted(new_violations.items())
            )
        )
    if stale:
        messages.append(
            "Stale baseline entries (these routes were fixed — regenerate the "
            "baseline with ENEO_ROUTE_CONTRACT_WRITE_BASELINE=1):\n"
            + "\n".join(f"  {k}: {', '.join(v)}" for k, v in sorted(stale.items()))
        )
    assert not messages, "\n\n".join(messages)

from __future__ import annotations

import ast
from pathlib import Path


API_V2_CRITICAL_MODULES = [
    "assistants",
    "apps",
    "files",
    "spaces",
    "groups_legacy",
    "group_chat",
    "conversations",
    "authentication",
    "users",
]

API_V2_DEBT_MODULES = [
    "websites",
    "collections",
    "info_blobs",
    "services",
    "prompts",
    "integration",
    "mcp_servers",
]

# Current debt baseline in non-critical modules; this test prevents regressions
# while we migrate those surfaces to actionable UnauthorizedException payloads.
MAX_BARE_UNAUTHORIZED_DEBT = 30


def _intric_src() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "intric"


def _iter_module_files() -> list[Path]:
    src = _intric_src()
    files: list[Path] = []
    for module in API_V2_CRITICAL_MODULES:
        base = src / module
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def _iter_debt_module_files() -> list[Path]:
    src = _intric_src()
    files: list[Path] = []
    for module in API_V2_DEBT_MODULES:
        base = src / module
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.py")))
    return files


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_http_exception_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _is_name(node.func, "HTTPException")


def test_no_bare_unauthorized_raises_in_critical_modules():
    violations: list[str] = []

    for file_path in _iter_module_files():
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise):
                continue

            if _is_name(node.exc, "UnauthorizedException"):
                violations.append(
                    f"{file_path}:{node.lineno} raise UnauthorizedException (class)"
                )
                continue

            if isinstance(node.exc, ast.Call) and _is_name(
                node.exc.func, "UnauthorizedException"
            ):
                if len(node.exc.args) == 0 and len(node.exc.keywords) == 0:
                    violations.append(
                        f"{file_path}:{node.lineno} raise UnauthorizedException()"
                    )

    assert not violations, (
        "Found non-actionable UnauthorizedException raises in API v2 critical modules:\n"
        + "\n".join(violations)
    )


def test_no_return_http_exception_antipattern_in_critical_modules():
    violations: list[str] = []

    for file_path in _iter_module_files():
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Return) and _is_http_exception_call(node.value):
                violations.append(f"{file_path}:{node.lineno} return HTTPException(...)")

    assert not violations, (
        "Found `return HTTPException(...)` anti-pattern in API v2 critical modules:\n"
        + "\n".join(violations)
    )


def test_bare_unauthorized_debt_budget_not_increased_in_noncritical_modules():
    violations: list[str] = []

    for file_path in _iter_debt_module_files():
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise):
                continue

            if _is_name(node.exc, "UnauthorizedException"):
                violations.append(
                    f"{file_path}:{node.lineno} raise UnauthorizedException (class)"
                )
                continue

            if isinstance(node.exc, ast.Call) and _is_name(
                node.exc.func, "UnauthorizedException"
            ):
                if len(node.exc.args) == 0 and len(node.exc.keywords) == 0:
                    violations.append(
                        f"{file_path}:{node.lineno} raise UnauthorizedException()"
                    )

    assert len(violations) <= MAX_BARE_UNAUTHORIZED_DEBT, (
        "Bare UnauthorizedException debt increased in non-critical modules "
        f"({len(violations)} > {MAX_BARE_UNAUTHORIZED_DEBT}).\n"
        + "\n".join(violations)
    )

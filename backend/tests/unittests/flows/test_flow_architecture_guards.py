from __future__ import annotations

import ast
from pathlib import Path

FLOW_SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "intric" / "flows"
FLOW_API_PACKAGES = {"api", "ai_builder"}


def _flow_non_api_python_files() -> list[Path]:
    return [
        path
        for path in FLOW_SOURCE_ROOT.rglob("*.py")
        if path.relative_to(FLOW_SOURCE_ROOT).parts[0] not in FLOW_API_PACKAGES
    ]


def _fastapi_http_exception_aliases(
    tree: ast.AST,
) -> tuple[set[str], set[str], list[int]]:
    imported_names: set[str] = set()
    fastapi_modules: set[str] = set()
    import_lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
            for alias in node.names:
                if alias.name == "HTTPException":
                    imported_names.add(alias.asname or alias.name)
                    import_lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fastapi":
                    fastapi_modules.add(alias.asname or alias.name)
    return imported_names, fastapi_modules, import_lines


def _raises_http_exception(
    node: ast.Raise,
    *,
    imported_names: set[str],
    fastapi_modules: set[str],
) -> bool:
    expression = node.exc
    if isinstance(expression, ast.Call):
        expression = expression.func
    if isinstance(expression, ast.Name):
        return expression.id in imported_names
    if (
        isinstance(expression, ast.Attribute)
        and expression.attr == "HTTPException"
        and isinstance(expression.value, ast.Name)
    ):
        return expression.value.id in fastapi_modules
    return False


def test_flow_non_api_modules_do_not_raise_fastapi_http_exception():
    """Flow application/runtime code should raise EXCEPTION_MAP-registered errors."""
    offenders: list[str] = []
    for path in _flow_non_api_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        imported_names, fastapi_modules, import_lines = _fastapi_http_exception_aliases(
            tree
        )
        for lineno in import_lines:
            offenders.append(f"{path.relative_to(FLOW_SOURCE_ROOT)}:{lineno}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and _raises_http_exception(
                node,
                imported_names=imported_names,
                fastapi_modules=fastapi_modules,
            ):
                offenders.append(f"{path.relative_to(FLOW_SOURCE_ROOT)}:{node.lineno}")

    assert offenders == []

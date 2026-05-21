from __future__ import annotations

import ast
from pathlib import Path

AI_BUILDER_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "intric" / "flows" / "ai_builder"
)
EXCEPTION_NAMES = {"BadRequestException", "NotFoundException", "UnauthorizedException"}
EXCLUDED_FILES = {"ai_builder_error_contract.py"}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_ai_builder_public_exceptions_use_canonical_error_code_enum() -> None:
    violations: list[str] = []
    for path in sorted(AI_BUILDER_SOURCE.glob("*.py")):
        if path.name in EXCLUDED_FILES:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or _call_name(node) not in EXCEPTION_NAMES
            ):
                continue
            for keyword in node.keywords:
                if keyword.arg != "code":
                    continue
                if isinstance(keyword.value, ast.Constant) and isinstance(
                    keyword.value.value, str
                ):
                    violations.append(
                        f"{path.relative_to(AI_BUILDER_SOURCE)}:{keyword.value.lineno}"
                    )

    assert not violations, (
        "AI Builder public exception codes must come from AIBuilderErrorCode, "
        f"not bare strings: {violations}"
    )

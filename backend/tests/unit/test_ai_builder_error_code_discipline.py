from __future__ import annotations

import ast
from pathlib import Path

AI_BUILDER_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "eneo" / "flows" / "ai_builder"
)
RAW_EXCEPTION_NAMES = {
    "BadRequestException",
    "NotFoundException",
    "UnauthorizedException",
}
TYPED_EXCEPTION_NAMES = {
    "AIBuilderBadRequestException",
    "AIBuilderNotFoundException",
    "AIBuilderUnauthorizedException",
}
EXCLUDED_FILES = {"ai_builder_error_contract.py"}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _is_ai_builder_error_code_member(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "AIBuilderErrorCode"
    )


def _is_value_attribute(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "value"


def test_ai_builder_public_exceptions_use_typed_error_classes() -> None:
    violations: list[str] = []
    for path in sorted(AI_BUILDER_SOURCE.glob("*.py")):
        if path.name in EXCLUDED_FILES:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or _call_name(node) not in RAW_EXCEPTION_NAMES | TYPED_EXCEPTION_NAMES
            ):
                continue
            call_name = _call_name(node)
            if call_name in RAW_EXCEPTION_NAMES:
                violations.append(
                    f"{path.relative_to(AI_BUILDER_SOURCE)}:{node.lineno}: "
                    f"raise {call_name}; use typed AI Builder exception"
                )
                continue
            code_keyword = next(
                (keyword for keyword in node.keywords if keyword.arg == "code"),
                None,
            )
            if code_keyword is None:
                violations.append(
                    f"{path.relative_to(AI_BUILDER_SOURCE)}:{node.lineno}: "
                    f"{call_name} missing code="
                )
                continue
            code_value = code_keyword.value
            if isinstance(code_value, ast.Constant):
                violations.append(
                    f"{path.relative_to(AI_BUILDER_SOURCE)}:{code_value.lineno}: "
                    f"{call_name} code must be AIBuilderErrorCode member"
                )
                continue
            if _is_value_attribute(code_value) or not _is_ai_builder_error_code_member(
                code_value
            ):
                violations.append(
                    f"{path.relative_to(AI_BUILDER_SOURCE)}:{code_value.lineno}: "
                    f"{call_name} code must be AIBuilderErrorCode member"
                )
                continue
            for keyword in node.keywords:
                if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                    violations.append(
                        f"{path.relative_to(AI_BUILDER_SOURCE)}:{keyword.value.lineno}: "
                        f"{call_name} code must not be literal"
                    )

    assert not violations, (
        "AI Builder public exceptions must use typed AI Builder exception classes "
        f"with AIBuilderErrorCode members: {violations}"
    )

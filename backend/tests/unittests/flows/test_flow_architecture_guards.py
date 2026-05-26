"""AST guards keep Flow architecture ownership rules from drifting.

The guards cover output-axis dispatch, outbox delivery vocabulary, and
container-provider wiring that must stay behind canonical owners.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from intric.database.tables.flow_tables import (
    FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES,
    FLOW_RUN_WEBHOOK_DELIVERY_STATUS_VALUES,
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRunWebhookDeliveries,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
FLOW_SOURCE_ROOT = BACKEND_ROOT / "src" / "intric" / "flows"
FLOW_RUNTIME_ROOT = FLOW_SOURCE_ROOT / "runtime"
FLOW_API_ROOT = FLOW_SOURCE_ROOT / "api"
FLOW_TASKS_PATH = FLOW_RUNTIME_ROOT / "tasks.py"
FLOW_API_PACKAGES = {"api", "ai_builder"}
OUTPUT_FORMATS_ROOT = FLOW_RUNTIME_ROOT / "output_formats"
DATA_RETENTION_ROOT = BACKEND_ROOT / "src" / "intric" / "data_retention"
PYRIGHT_REPORT_UNKNOWN_MEMBER_IGNORE_RE = re.compile(
    r"#\s*pyright\s*:\s*ignore\s*\[\s*[^\]]*\breportUnknownMemberType\b[^\]]*\]"
)

_OUTPUT_AXIS_ENUMS = {
    "output_mode": "FlowOutputMode",
    "output_type": "FlowOutputType",
}


@dataclass(frozen=True, order=True)
class _OutputAxisBranch:
    axis: str
    relative_path: str
    function: str
    expression: str


ALLOWED_OUTPUT_MODE_BRANCHES = frozenset(
    {
        _OutputAxisBranch(
            axis="output_mode",
            relative_path="step_input_resolution.py",
            function="resolve_step_input",
            expression="step.output_mode == 'transcribe_only'",
        ),
        _OutputAxisBranch(
            axis="output_mode",
            relative_path="step_definition_parser.py",
            function="_parse_output_fields",
            expression="output_mode not in ALLOWED_OUTPUT_MODES",
        ),
        _OutputAxisBranch(
            axis="output_mode",
            relative_path="step_definition_parser.py",
            function="_parse_output_config",
            expression="output_mode == 'template_fill'",
        ),
        _OutputAxisBranch(
            axis="output_mode",
            relative_path="step_definition_parser.py",
            function="parse_runtime_steps",
            expression="output_fields.output_mode == 'transcribe_only'",
        ),
        _OutputAxisBranch(
            axis="output_mode",
            relative_path="executor.py",
            function="_build_attempt_provenance",
            expression="step.output_mode == 'http_post'",
        ),
        _OutputAxisBranch(
            axis="output_mode",
            relative_path="executor.py",
            function="_build_step_handler",
            expression="match mode using FlowOutputMode",
        ),
    }
)
ALLOWED_OUTPUT_TYPE_BRANCHES = frozenset(
    {
        _OutputAxisBranch(
            axis="output_type",
            relative_path="step_definition_parser.py",
            function="_parse_output_fields",
            expression="output_type not in ALLOWED_OUTPUT_TYPES",
        ),
        _OutputAxisBranch(
            axis="output_type",
            relative_path="step_definition_parser.py",
            function="_parse_output_config",
            expression="output_type != 'docx'",
        ),
        _OutputAxisBranch(
            axis="output_type",
            relative_path="step_execution_runtime.py",
            function="citation_mode_for_step",
            expression="output_type is not FlowOutputType.TEXT",
        ),
    }
)
MAX_OUTPUT_MODE_BRANCH_ALLOWLIST_SIZE = 6
MAX_OUTPUT_TYPE_BRANCH_ALLOWLIST_SIZE = 3
_REMOVED_TYPED_OUTPUT_HELPERS = frozenset(
    {
        "augment_prompt_for_typed_output",
        "_should_request_native_json_object_mode",
        "_schema_prefers_object_value",
    }
)
_REMOVED_INLINE_WEBHOOK_EXECUTOR_FUNCTIONS = frozenset(
    {
        "_deliver_step_webhook",
        "_handle_webhook_delivery_failure",
        "_mark_webhook_delivery_success",
        "_deliver_webhook",
    }
)
OUTBOX_DELIVERY_STATUS_SOURCE_FILES = (
    FLOW_SOURCE_ROOT,
    DATA_RETENTION_ROOT,
)
OUTBOX_DELIVERY_STATUS_OWNER_NAMES = frozenset(
    {
        "FlowOutboxDeliveryStatus",
        "FlowRunAuditOutbox",
        "FlowRunWebhookDeliveries",
    }
)
FORBIDDEN_API_MANUAL_CONSTRUCTION_CLASS_NAMES = frozenset(
    {
        "FlowFileUploadService",
        "FlowRunContractService",
    }
)


def _flow_non_api_python_files() -> list[Path]:
    return [
        path
        for path in FLOW_SOURCE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and path.relative_to(FLOW_SOURCE_ROOT).parts[0] not in FLOW_API_PACKAGES
    ]


def _flow_runtime_python_files() -> list[Path]:
    return [
        path
        for path in FLOW_RUNTIME_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _flow_api_python_files() -> list[Path]:
    return [
        path for path in FLOW_API_ROOT.rglob("*.py") if "__pycache__" not in path.parts
    ]


def _relative_runtime_path(path: Path) -> str:
    return path.relative_to(FLOW_RUNTIME_ROOT).as_posix()


def _node_references_outbox_delivery_status_owner(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in OUTBOX_DELIVERY_STATUS_OWNER_NAMES
    return (
        isinstance(node, ast.Attribute)
        and node.attr in OUTBOX_DELIVERY_STATUS_OWNER_NAMES
    )


def _outbox_delivery_status_source_files() -> list[Path]:
    files: list[Path] = []
    for root in OUTBOX_DELIVERY_STATUS_SOURCE_FILES:
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            if any(
                _node_references_outbox_delivery_status_owner(node)
                for node in ast.walk(tree)
            ):
                files.append(path)
    return sorted(files)


def _is_container_provider_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "container"
    )


def _contains_container_provider_call(node: ast.AST) -> bool:
    return any(_is_container_provider_call(child) for child in ast.walk(node))


def _container_provider_any_erasure_offenders(path: Path) -> list[str]:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "cast":
            continue
        if len(node.args) < 2:
            continue
        type_arg = node.args[0]
        if (
            isinstance(type_arg, ast.Name)
            and type_arg.id == "Any"
            and _contains_container_provider_call(node.args[1])
        ):
            offenders.append(f"cast(Any):{node.lineno}")

    container_provider_lines = {
        node.lineno for node in ast.walk(tree) if _is_container_provider_call(node)
    }
    for line_number, line in enumerate(source.splitlines(), start=1):
        if PYRIGHT_REPORT_UNKNOWN_MEMBER_IGNORE_RE.search(line) and any(
            provider_line <= line_number <= provider_line + 2
            for provider_line in container_provider_lines
        ):
            offenders.append(f"pyright-ignore:{line_number}")

    return offenders


def _is_docstring_expression(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _container_provider_passthrough_name(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> str | None:
    if not node.name.startswith("_"):
        return None
    if not any(arg.arg == "container" for arg in node.args.args):
        return None

    body = [
        statement for statement in node.body if not _is_docstring_expression(statement)
    ]
    if len(body) != 1:
        return None
    statement = body[0]
    if not isinstance(statement, ast.Return):
        return None

    value = statement.value
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "container"
        and not value.args
        and not value.keywords
    ):
        return value.func.attr
    return None


def _should_scan_path_for_axis(path: Path, *, axis: str) -> bool:
    return axis != "output_type" or OUTPUT_FORMATS_ROOT not in path.parents


def _node_references_axis(node: ast.AST, *, axis: str) -> bool:
    enum_name = _OUTPUT_AXIS_ENUMS[axis]
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == axis:
            return True
        if not isinstance(child, ast.Attribute):
            continue
        if child.attr == axis:
            return True
        if isinstance(child.value, ast.Name) and child.value.id == enum_name:
            return True
    return False


def _pattern_references_enum(pattern: ast.pattern, *, enum_name: str) -> bool:
    for child in ast.walk(pattern):
        if (
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == enum_name
        ):
            return True
    return False


class _OutputAxisBranchVisitor(ast.NodeVisitor):
    def __init__(self, *, relative_path: str):
        self._relative_path = relative_path
        self._function_stack: list[str] = []
        self.branches: set[_OutputAxisBranch] = set()

    @property
    def _function_name(self) -> str:
        return ".".join(self._function_stack) or "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._function_stack.append(node.name)
        self.generic_visit(node)
        self._function_stack.pop()

    def visit_Compare(self, node: ast.Compare) -> None:
        operands = (node.left, *node.comparators)
        for axis in _OUTPUT_AXIS_ENUMS:
            if not any(
                _node_references_axis(operand, axis=axis) for operand in operands
            ):
                continue
            self.branches.add(
                _OutputAxisBranch(
                    axis=axis,
                    relative_path=self._relative_path,
                    function=self._function_name,
                    expression=ast.unparse(node),
                )
            )
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        for axis, enum_name in _OUTPUT_AXIS_ENUMS.items():
            if not (
                _node_references_axis(node.subject, axis=axis)
                or any(
                    _pattern_references_enum(case.pattern, enum_name=enum_name)
                    for case in node.cases
                )
            ):
                continue
            self.branches.add(
                _OutputAxisBranch(
                    axis=axis,
                    relative_path=self._relative_path,
                    function=self._function_name,
                    expression=f"match {ast.unparse(node.subject)} using {enum_name}",
                )
            )
        self.generic_visit(node)


def _output_axis_branches_in_tree(
    tree: ast.AST, *, relative_path: str
) -> frozenset[_OutputAxisBranch]:
    visitor = _OutputAxisBranchVisitor(relative_path=relative_path)
    visitor.visit(tree)
    return frozenset(visitor.branches)


def _runtime_output_axis_branches(*, axis: str) -> frozenset[_OutputAxisBranch]:
    branches: set[_OutputAxisBranch] = set()
    for path in _flow_runtime_python_files():
        if not _should_scan_path_for_axis(path, axis=axis):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        branches.update(
            branch
            for branch in _output_axis_branches_in_tree(
                tree, relative_path=_relative_runtime_path(path)
            )
            if branch.axis == axis
        )
    return frozenset(branches)


def _format_branches(branches: Iterable[_OutputAxisBranch]) -> str:
    return "\n".join(
        f"- {branch.relative_path}::{branch.function}::{branch.expression}"
        for branch in sorted(branches)
    )


def _first_branch(branches: frozenset[_OutputAxisBranch]) -> _OutputAxisBranch:
    return next(iter(sorted(branches)))


def _assert_axis_branches_are_allowed(
    *,
    axis: str,
    allowed: frozenset[_OutputAxisBranch],
    max_allowed: int,
    canonical_owner: str,
    allowlist_name: str,
) -> None:
    found = _runtime_output_axis_branches(axis=axis)
    unexpected = found - allowed
    stale = allowed - found
    example = _first_branch(allowed)
    guidance = (
        f"{canonical_owner} is the canonical owner for new {axis} policy. "
        f"If this is a legitimate exception, add it to {allowlist_name} with a "
        "narrow function/expression and reason. Example existing exception: "
        f"{example.relative_path}::{example.function}."
    )
    assert not unexpected, (
        f"Unexpected {axis} branches:\n{_format_branches(unexpected)}\n{guidance}"
    )
    assert not stale, (
        f"Stale {axis} allowlist entries:\n{_format_branches(stale)}\n"
        f"Remove stale entries from {allowlist_name}; do not keep compatibility "
        "exceptions after the source branch is gone."
    )
    assert len(allowed) <= max_allowed, (
        f"{allowlist_name} has {len(allowed)} entries, expected at most "
        f"{max_allowed}. Prefer moving logic to {canonical_owner} instead of "
        "growing the exception list."
    )


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


def test_output_mode_literal_branches_only_appear_in_allowlisted_call_sites():
    _assert_axis_branches_are_allowed(
        axis="output_mode",
        allowed=ALLOWED_OUTPUT_MODE_BRANCHES,
        max_allowed=MAX_OUTPUT_MODE_BRANCH_ALLOWLIST_SIZE,
        canonical_owner="runtime/step_handlers",
        allowlist_name="ALLOWED_OUTPUT_MODE_BRANCHES",
    )


def test_output_type_literal_branches_only_appear_in_allowlisted_call_sites():
    _assert_axis_branches_are_allowed(
        axis="output_type",
        allowed=ALLOWED_OUTPUT_TYPE_BRANCHES,
        max_allowed=MAX_OUTPUT_TYPE_BRANCH_ALLOWLIST_SIZE,
        canonical_owner="runtime/output_formats",
        allowlist_name="ALLOWED_OUTPUT_TYPE_BRANCHES",
    )


def test_output_mode_branch_scanner_reports_forbidden_call_site():
    tree = ast.parse(
        "def execute(step):\n"
        "    if step.output_mode == 'http_post':\n"
        "        return True\n"
    )

    assert _OutputAxisBranch(
        axis="output_mode",
        relative_path="new_runtime.py",
        function="execute",
        expression="step.output_mode == 'http_post'",
    ) in _output_axis_branches_in_tree(tree, relative_path="new_runtime.py")


def test_output_mode_guard_scans_output_format_modules():
    output_format_path = OUTPUT_FORMATS_ROOT / "new_format.py"

    assert _should_scan_path_for_axis(output_format_path, axis="output_mode")
    assert not _should_scan_path_for_axis(output_format_path, axis="output_type")


def test_output_type_branch_scanner_reports_forbidden_call_site():
    tree = ast.parse(
        "def render(step):\n"
        "    if step.output_type in ('pdf', 'docx'):\n"
        "        return True\n"
    )

    assert _OutputAxisBranch(
        axis="output_type",
        relative_path="new_runtime.py",
        function="render",
        expression="step.output_type in ('pdf', 'docx')",
    ) in _output_axis_branches_in_tree(tree, relative_path="new_runtime.py")


def test_removed_typed_output_helpers_do_not_reappear():
    offenders: list[str] = []
    for path in _flow_runtime_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name in _REMOVED_TYPED_OUTPUT_HELPERS:
                offenders.append(f"{_relative_runtime_path(path)}::{node.name}")

    assert offenders == [], (
        "Typed output prompt/native JSON-mode policy belongs in "
        "runtime/output_formats. Do not reintroduce removed helper owners: "
        + ", ".join(offenders)
    )


def test_executor_does_not_own_webhook_delivery_side_effects():
    executor_path = FLOW_RUNTIME_ROOT / "executor.py"
    tree = ast.parse(executor_path.read_text(), filename=str(executor_path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name in _REMOVED_INLINE_WEBHOOK_EXECUTOR_FUNCTIONS
        ):
            offenders.append(f"function:{node.name}:{node.lineno}")
        if isinstance(node, ast.Call) and isinstance(
            node.func, ast.Attribute | ast.Name
        ):
            name = (
                node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            )
            if name in _REMOVED_INLINE_WEBHOOK_EXECUTOR_FUNCTIONS:
                offenders.append(f"call:{name}:{node.lineno}")

    assert offenders == [], (
        "Webhook HTTP side effects belong to the durable outbox worker, not "
        "FlowRunExecutor inline delivery: " + ", ".join(offenders)
    )


def test_flow_outbox_delivery_status_vocabulary_is_canonical():
    expected = tuple(item.value for item in FlowOutboxDeliveryStatus)

    assert FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES == expected
    assert FLOW_RUN_WEBHOOK_DELIVERY_STATUS_VALUES == expected


def test_flow_outbox_delivery_status_sql_text_matches_vocabulary():
    expected = {item.value for item in FlowOutboxDeliveryStatus}
    sql_texts: list[str] = []
    for table in (
        FlowRunAuditOutbox.__table__,
        FlowRunWebhookDeliveries.__table__,
    ):
        for constraint in table.constraints:
            constraint_sql_text = getattr(constraint, "sqltext", None)
            if constraint_sql_text is None:
                continue
            constraint_sql = str(constraint_sql_text)
            if "delivery_status" in constraint_sql:
                sql_texts.append(constraint_sql)
        for index in table.indexes:
            index_where = index.dialect_options["postgresql"]["where"]
            if index_where is None:
                continue
            index_sql = str(index_where)
            if "delivery_status" in index_sql:
                sql_texts.append(index_sql)

    sql_status_values = set(re.findall(r"'([^']+)'", "\n".join(sql_texts)))

    assert sql_status_values == expected


def test_container_provider_erasure_detector_catches_report_unknown_member_spacing(
    tmp_path: Path,
):
    source_path = tmp_path / "provider_wiring.py"
    source_path.write_text(
        "\n".join(
            [
                "from typing import Any, cast",
                "",
                "def sample(container):",
                "    one = container.flow_service()  # pyright:ignore[reportUnknownMemberType]",
                "    two = container.flow_run_service()  # pyright: ignore[reportUnknownMemberType]",
                "    three = container.flow_version_repo()",
                "    # pyright:  ignore [ reportUnknownMemberType ]",
                "    four = container.space_service()",
                "    # pyright: ignore[reportGeneralTypeIssues, reportUnknownMemberType]",
                "    no_provider_nearby = object()",
                "    still_no_provider_nearby = object()",
                "    # pyright: ignore[reportUnknownMemberType]",
                "    # pyright: ignore[reportUnknownMemberType]",
                "    five = container.tenant_repo()",
                "    erased = cast(Any, container.actor_manager())",
            ]
        )
    )

    offenders = _container_provider_any_erasure_offenders(source_path)
    assert set(offenders) == {
        "cast(Any):15",
        "pyright-ignore:4",
        "pyright-ignore:5",
        "pyright-ignore:7",
        "pyright-ignore:9",
    }


def test_flow_outbox_delivery_status_literals_use_canonical_vocabulary():
    status_values = {item.value for item in FlowOutboxDeliveryStatus}
    offenders: list[str] = []

    for path in _outbox_delivery_status_source_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in status_values:
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")

    assert offenders == [], (
        "Outbox delivery status comparisons must use FlowOutboxDeliveryStatus "
        "from flow_tables.py, not raw string literals: " + ", ".join(offenders)
    )


def test_flow_celery_task_provider_wiring_is_not_erased_to_any():
    offenders = _container_provider_any_erasure_offenders(FLOW_TASKS_PATH)

    assert offenders == [], (
        "Flow Celery task wiring must preserve typed Container provider "
        "contracts instead of erasing them to Any: " + ", ".join(offenders)
    )


def test_flow_api_provider_wiring_uses_typed_container_providers():
    offenders: list[str] = []

    for path in _flow_api_python_files():
        relative_path = path.relative_to(BACKEND_ROOT)
        offenders.extend(
            f"{relative_path}:{offender}"
            for offender in _container_provider_any_erasure_offenders(path)
        )

        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                provider_name = _container_provider_passthrough_name(node)
                if provider_name is not None:
                    offenders.append(
                        f"{relative_path}:helper:{node.name}:{provider_name}:{node.lineno}"
                    )
                continue
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in FORBIDDEN_API_MANUAL_CONSTRUCTION_CLASS_NAMES
            ):
                offenders.append(
                    f"{relative_path}:manual-construction:{node.func.id}:{node.lineno}"
                )

    assert offenders == [], (
        "Flow API provider wiring must use typed Container providers: no "
        "cast(Any, container...), no provider reportUnknownMemberType ignores, "
        "no private provider pass-through helpers, and no direct Flow service "
        "construction: " + ", ".join(offenders)
    )

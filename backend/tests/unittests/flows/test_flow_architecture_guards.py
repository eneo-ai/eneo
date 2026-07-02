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

import pytest
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table

from eneo.database.tables.flow_tables import (
    FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES,
    FLOW_RUN_WEBHOOK_DELIVERY_STATUS_VALUES,
    FlowOutboxDeliveryStatus,
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRunWebhookDeliveries,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
FLOW_SOURCE_ROOT = BACKEND_ROOT / "src" / "eneo" / "flows"
FLOW_RUNTIME_ROOT = FLOW_SOURCE_ROOT / "runtime"
FLOW_API_ROOT = FLOW_SOURCE_ROOT / "api"
FLOW_TASKS_PATH = FLOW_RUNTIME_ROOT / "tasks.py"
FLOW_API_PACKAGES = {"api", "ai_builder"}
OUTPUT_FORMATS_ROOT = FLOW_RUNTIME_ROOT / "output_formats"
DATA_RETENTION_ROOT = BACKEND_ROOT / "src" / "eneo" / "data_retention"
PYRIGHT_REPORT_UNKNOWN_MEMBER_IGNORE_RE = re.compile(
    r"#\s*pyright\s*:\s*ignore\s*\[\s*[^\]]*\breportUnknownMemberType\b[^\]]*\]"
)
LOCAL_JSON_ALIAS_NAME_RE = re.compile(r"^Json[A-Z]")
FILES_CONTENT_COLUMNS = frozenset({"blob", "text", "transcription"})
FILES_CONTENT_LIFECYCLE_GUARD_MESSAGE = (
    "Data retention must not null principal-owned "
    "Files.blob/text/transcription until run-private file lifecycle ownership exists."
)
GENERATED_ARTIFACT_RETENTION_GUARD_MESSAGE = (
    "Data retention must not schedule generated-artifact cleanup work while no "
    "run-private Flow file lifecycle owner exists."
)
FLOW_TRANSCRIBE_CACHE_GUARD_MESSAGE = (
    "Flow runtime owns transcript content through run/step/evidence payloads, "
    "not the shared Files.transcription cache."
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


@dataclass(frozen=True, order=True)
class _LocalJsonAliasException:
    relative_path: str
    name: str


@dataclass(frozen=True, order=True)
class _LocalJsonAliasDefinition:
    relative_path: str
    name: str
    line: int


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
ALLOWED_LOCAL_JSON_ALIAS_DEFINITIONS = frozenset(
    {
        _LocalJsonAliasException(
            relative_path="ai_builder/ai_builder_conversation_metadata.py",
            name="JsonScalar",
        ),
        _LocalJsonAliasException(
            relative_path="ai_builder/ai_builder_error_contract.py",
            name="JsonScalar",
        ),
        _LocalJsonAliasException(
            relative_path="ai_builder/ai_builder_event_models.py",
            name="JsonScalar",
        ),
    }
)
MAX_LOCAL_JSON_ALIAS_ALLOWLIST_SIZE = 3
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
FLOW_RUN_STEP_ATTEMPT_KEY_COLUMNS = ("flow_run_id", "step_id", "attempt_no")
FLOW_RUN_STEP_ATTEMPT_CHILD_FK_POLICIES = {
    FlowRunReviewCheckpoints.__table__.name: (
        "fk_flow_run_review_checkpoints_step_attempt",
        "RESTRICT",
    ),
    FlowRunStepResultFiles.__table__.name: (
        "fk_flow_run_step_result_files_step_attempt",
        "CASCADE",
    ),
    FlowRunWebhookDeliveries.__table__.name: (
        "fk_flow_run_webhook_deliveries_step_attempt",
        "RESTRICT",
    ),
}
FLOW_RUN_PRE_ATTEMPT_INPUT_PROJECTION_TABLES = frozenset(
    {FlowRunStepInputFiles.__table__.name}
)
FLOW_RUN_STEP_INPUT_FILES_POSITIVE_ATTEMPT_CONSTRAINT = (
    "ck_flow_run_step_input_files_attempt_no_positive"
)
FLOW_RUN_STEP_INPUT_FILES_REMOVED_INITIAL_ATTEMPT_CONSTRAINT = (
    "ck_flow_run_step_input_files_attempt_no_initial"
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
        "FlowRuntimeFileService",
        "FlowRunContractService",
    }
)
FLOW_RUN_REPOSITORY_PLATFORM_EXCEPTION_IMPORT_BAN = frozenset(
    {
        "infrastructure/flow_run_repo.py",
        "infrastructure/flow_run_rerun_repo.py",
        "infrastructure/flow_run_review_checkpoint_repo.py",
    }
)


def _flow_non_api_python_files() -> list[Path]:
    return [
        path
        for path in FLOW_SOURCE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and path.relative_to(FLOW_SOURCE_ROOT).parts[0] not in FLOW_API_PACKAGES
    ]


def _flow_python_files() -> list[Path]:
    return [
        path
        for path in FLOW_SOURCE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
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


def _data_retention_python_files() -> list[Path]:
    return [
        path
        for path in DATA_RETENTION_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _relative_runtime_path(path: Path) -> str:
    return path.relative_to(FLOW_RUNTIME_ROOT).as_posix()


def _relative_flow_path(path: Path) -> str:
    return path.relative_to(FLOW_SOURCE_ROOT).as_posix()


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


def _flow_run_tables_with_step_attempt_key() -> list[Table]:
    metadata = FlowRunStepInputFiles.__table__.metadata
    return sorted(
        [
            table
            for table in metadata.tables.values()
            if table.name.startswith("flow_run_")
            and set(FLOW_RUN_STEP_ATTEMPT_KEY_COLUMNS).issubset(table.columns.keys())
        ],
        key=lambda table: table.name,
    )


def _foreign_key_constraints(table: Table) -> list[ForeignKeyConstraint]:
    return [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]


def _foreign_key_constraint_by_name(
    table: Table,
    name: str,
) -> ForeignKeyConstraint | None:
    for constraint in _foreign_key_constraints(table):
        if constraint.name == name:
            return constraint
    return None


def _check_constraint_sql_by_name(table: Table, name: str) -> str | None:
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name == name:
            return str(constraint.sqltext)
    return None


def _targets_flow_step_attempt_natural_key(
    constraint: ForeignKeyConstraint,
) -> bool:
    return (
        tuple(element.column.table.name for element in constraint.elements)
        == ("flow_step_attempts",) * len(FLOW_RUN_STEP_ATTEMPT_KEY_COLUMNS)
        and tuple(element.column.name for element in constraint.elements)
        == FLOW_RUN_STEP_ATTEMPT_KEY_COLUMNS
    )


def _call_chain_root(call: ast.Call) -> ast.Call:
    current = call
    while isinstance(current.func, ast.Attribute) and isinstance(
        current.func.value, ast.Call
    ):
        current = current.func.value
    return current


def _is_files_table_update_call(call: ast.Call) -> bool:
    if len(call.args) != 1:
        return False
    target = call.args[0]
    if not isinstance(target, ast.Name) or target.id != "Files":
        return False
    if isinstance(call.func, ast.Name):
        return call.func.id == "update"
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "update"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "sa"
    )


def _none_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _files_content_nulling_columns(values_call: ast.Call) -> frozenset[str]:
    columns: set[str] = set()
    for keyword in values_call.keywords:
        if (
            keyword.arg in FILES_CONTENT_COLUMNS
            and keyword.arg is not None
            and _none_literal(keyword.value)
        ):
            columns.add(keyword.arg)
    for arg in values_call.args:
        if not isinstance(arg, ast.Dict):
            continue
        for key, value in zip(arg.keys, arg.values, strict=True):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value in FILES_CONTENT_COLUMNS
                and _none_literal(value)
            ):
                columns.add(key.value)
    return frozenset(columns)


def _files_content_nulling_update_offenders(
    tree: ast.AST, *, relative_path: str
) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Attribute)
            or node.func.attr != "values"
        ):
            continue
        columns = _files_content_nulling_columns(node)
        if not columns:
            continue
        if _is_files_table_update_call(_call_chain_root(node)):
            offenders.append(
                f"{relative_path}:{node.lineno}:{','.join(sorted(columns))}"
            )
    return offenders


def _format_files_content_lifecycle_guard_failure(offenders: list[str]) -> str:
    return FILES_CONTENT_LIFECYCLE_GUARD_MESSAGE + " Offenders: " + ", ".join(offenders)


def _is_generated_artifact_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "generated_artifact"


def _retention_for_generated_artifact_call(call: ast.Call) -> bool:
    if not isinstance(call.func, ast.Attribute):
        return False
    if call.func.attr != "retention_for_class":
        return False
    if call.args and _is_generated_artifact_literal(call.args[0]):
        return True
    return any(
        keyword.arg == "data_class" and _is_generated_artifact_literal(keyword.value)
        for keyword in call.keywords
    )


def _generated_artifact_retention_schedule_offenders(
    tree: ast.AST, *, relative_path: str
) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == "_cleanup_old_generated_flow_artifacts"
        ):
            offenders.append(f"{relative_path}:{node.lineno}:cleanup-helper")
        elif isinstance(node, ast.Call) and _retention_for_generated_artifact_call(
            node
        ):
            offenders.append(f"{relative_path}:{node.lineno}:retention_for_class")
    return offenders


def _format_generated_artifact_retention_guard_failure(offenders: list[str]) -> str:
    return (
        GENERATED_ARTIFACT_RETENTION_GUARD_MESSAGE
        + " Offenders: "
        + ", ".join(offenders)
    )


def _false_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _flow_transcribe_cache_bypass_offenders(
    tree: ast.AST, *, relative_path: str
) -> list[str]:
    """Catches direct .transcribe(...); aliases and wrappers are forbidden by convention."""
    offenders: list[str] = []
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Attribute)
            or node.func.attr != "transcribe"
        ):
            continue

        has_cache_bypass = False
        for keyword in node.keywords:
            if keyword.arg is None:
                offenders.append(f"{relative_path}:{node.lineno}:kwargs-bypass")
                continue
            if keyword.arg != "persist_cache_to_file":
                continue
            has_cache_bypass = True
            if not _false_literal(keyword.value):
                offenders.append(
                    f"{relative_path}:{node.lineno}:persist_cache_to_file-not-false"
                )

        if not has_cache_bypass:
            offenders.append(
                f"{relative_path}:{node.lineno}:missing-persist_cache_to_file-false"
            )
    return offenders


def _format_flow_transcribe_cache_guard_failure(offenders: list[str]) -> str:
    return FLOW_TRANSCRIBE_CACHE_GUARD_MESSAGE + " Offenders: " + ", ".join(offenders)


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


def _module_level_name_target(node: ast.Assign | ast.AnnAssign) -> ast.Name | None:
    if isinstance(node, ast.AnnAssign):
        target = node.target
    elif len(node.targets) == 1:
        target = node.targets[0]
    else:
        return None
    if isinstance(target, ast.Name):
        return target
    return None


def _local_json_alias_definitions_in_tree(
    tree: ast.AST,
    *,
    relative_path: str,
) -> frozenset[_LocalJsonAliasDefinition]:
    if not isinstance(tree, ast.Module):
        return frozenset()
    definitions: set[_LocalJsonAliasDefinition] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        target = _module_level_name_target(node)
        if target is None or not LOCAL_JSON_ALIAS_NAME_RE.match(target.id):
            continue
        definitions.add(
            _LocalJsonAliasDefinition(
                relative_path=relative_path,
                name=target.id,
                line=node.lineno,
            )
        )
    return frozenset(definitions)


def _flow_local_json_alias_definitions() -> frozenset[_LocalJsonAliasDefinition]:
    definitions: set[_LocalJsonAliasDefinition] = set()
    for path in _flow_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        definitions.update(
            _local_json_alias_definitions_in_tree(
                tree,
                relative_path=_relative_flow_path(path),
            )
        )
    return frozenset(definitions)


def _format_local_json_alias_definitions(
    definitions: Iterable[_LocalJsonAliasDefinition],
) -> str:
    return "\n".join(
        f"- {definition.relative_path}:{definition.line}:{definition.name}"
        for definition in sorted(definitions)
    )


def _format_local_json_alias_exceptions(
    exceptions: Iterable[_LocalJsonAliasException],
) -> str:
    return "\n".join(
        f"- {exception.relative_path}:{exception.name}"
        for exception in sorted(exceptions)
    )


def _local_json_alias_exception(
    definition: _LocalJsonAliasDefinition,
) -> _LocalJsonAliasException:
    return _LocalJsonAliasException(
        relative_path=definition.relative_path,
        name=definition.name,
    )


def _assert_local_json_alias_definitions_are_allowed(
    found: frozenset[_LocalJsonAliasDefinition],
    *,
    allowed: frozenset[_LocalJsonAliasException] = ALLOWED_LOCAL_JSON_ALIAS_DEFINITIONS,
) -> None:
    found_exceptions = frozenset(
        _local_json_alias_exception(definition) for definition in found
    )
    unexpected = frozenset(
        definition
        for definition in found
        if _local_json_alias_exception(definition) not in allowed
    )
    stale = allowed - found_exceptions
    guidance = (
        "eneo.json_types is the canonical owner for strict Json* aliases in "
        "Flow code. Import the platform alias, rename domain-specific aliases "
        "outside the Json* namespace, or add a narrow documented exception."
    )
    assert not unexpected, (
        "Unexpected local Flow Json* alias definitions:\n"
        f"{_format_local_json_alias_definitions(unexpected)}\n{guidance}"
    )
    assert not stale, (
        "Stale local Flow Json* alias allowlist entries:\n"
        f"{_format_local_json_alias_exceptions(stale)}\n"
        "Remove stale entries instead of keeping compatibility exceptions."
    )
    assert len(allowed) <= MAX_LOCAL_JSON_ALIAS_ALLOWLIST_SIZE, (
        "Prefer moving aliases to eneo.json_types instead of growing the allowlist."
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


def _imports_platform_exception_module(
    tree: ast.AST,
) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "eneo.main.exceptions"
            or alias.name.startswith("eneo.main.exceptions.")
            for alias in node.names
        ):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "eneo.main.exceptions":
                lines.append(node.lineno)
            elif node.module == "eneo.main" and any(
                alias.name == "exceptions" for alias in node.names
            ):
                lines.append(node.lineno)
    return lines


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


def test_flow_local_json_aliases_are_platform_owned_or_allowlisted():
    _assert_local_json_alias_definitions_are_allowed(
        _flow_local_json_alias_definitions()
    )


def test_local_json_alias_scanner_reports_module_aliases():
    tree = ast.parse(
        "JsonObject = dict[str, object]\n"
        "JsonValue: TypeAlias = object\n"
        "NOT_JSON = object\n"
        "def nested():\n"
        "    JsonScalar = str\n"
    )

    definitions = _local_json_alias_definitions_in_tree(
        tree,
        relative_path="sample.py",
    )

    assert definitions == frozenset(
        {
            _LocalJsonAliasDefinition(
                relative_path="sample.py",
                name="JsonObject",
                line=1,
            ),
            _LocalJsonAliasDefinition(
                relative_path="sample.py",
                name="JsonValue",
                line=2,
            ),
        }
    )


def test_local_json_alias_guard_rejects_stale_allowlist_entries():
    allowed = frozenset(
        {
            _LocalJsonAliasException(
                relative_path="sample.py",
                name="JsonObject",
            )
        }
    )

    with pytest.raises(AssertionError, match="Stale local Flow Json"):
        _assert_local_json_alias_definitions_are_allowed(
            frozenset(),
            allowed=allowed,
        )


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


def test_platform_exception_module_import_scanner_detects_banned_import_forms():
    tree = ast.parse(
        "import eneo.main.exceptions\n"
        "import eneo.main.exceptions as platform_exceptions\n"
        "from eneo.main import exceptions\n"
        "from eneo.main import exceptions as exc\n"
        "from eneo.main.exceptions import NotFoundException\n"
        "from eneo.main.exceptions import BadRequestException as BadRequest\n"
        "from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError\n"
    )

    assert _imports_platform_exception_module(tree) == [1, 2, 3, 4, 5, 6]


def test_flow_run_repositories_do_not_import_platform_exception_module():
    offenders: list[str] = []
    for relative_path in sorted(FLOW_RUN_REPOSITORY_PLATFORM_EXCEPTION_IMPORT_BAN):
        path = FLOW_SOURCE_ROOT / relative_path
        tree = ast.parse(path.read_text(), filename=str(path))
        for lineno in _imports_platform_exception_module(tree):
            offenders.append(f"{relative_path}:{lineno}")

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


def test_flow_run_step_attempt_key_tables_have_explicit_ownership_policy():
    expected_tables = tuple(
        sorted(
            [
                *FLOW_RUN_STEP_ATTEMPT_CHILD_FK_POLICIES,
                *FLOW_RUN_PRE_ATTEMPT_INPUT_PROJECTION_TABLES,
            ]
        )
    )
    tables = _flow_run_tables_with_step_attempt_key()

    assert tuple(table.name for table in tables) == expected_tables

    for table in tables:
        if table.name in FLOW_RUN_PRE_ATTEMPT_INPUT_PROJECTION_TABLES:
            attempt_fks = [
                constraint.name
                for constraint in _foreign_key_constraints(table)
                if _targets_flow_step_attempt_natural_key(constraint)
            ]
            assert attempt_fks == [], (
                f"{table.name} stores initial and queued-rerun input projections "
                "before step attempts exist; changing this requires moving "
                "projection writes into attempt creation."
            )
            assert (
                _check_constraint_sql_by_name(
                    table,
                    FLOW_RUN_STEP_INPUT_FILES_POSITIVE_ATTEMPT_CONSTRAINT,
                )
                == "attempt_no >= 1"
            )
            assert (
                _check_constraint_sql_by_name(
                    table,
                    FLOW_RUN_STEP_INPUT_FILES_REMOVED_INITIAL_ATTEMPT_CONSTRAINT,
                )
                is None
            )
            continue

        expected_policy = FLOW_RUN_STEP_ATTEMPT_CHILD_FK_POLICIES.get(table.name)
        assert expected_policy is not None
        expected_fk_name, expected_ondelete = expected_policy
        constraint = _foreign_key_constraint_by_name(table, expected_fk_name)

        assert constraint is not None
        assert tuple(element.parent.name for element in constraint.elements) == (
            FLOW_RUN_STEP_ATTEMPT_KEY_COLUMNS
        )
        assert _targets_flow_step_attempt_natural_key(constraint)
        assert constraint.ondelete == expected_ondelete


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


def test_data_retention_does_not_null_files_content_directly():
    offenders: list[str] = []
    for path in _data_retention_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders.extend(
            _files_content_nulling_update_offenders(
                tree,
                relative_path=path.relative_to(BACKEND_ROOT).as_posix(),
            )
        )

    assert offenders == [], _format_files_content_lifecycle_guard_failure(offenders)


def test_data_retention_does_not_schedule_generated_artifact_cleanup():
    offenders: list[str] = []
    for path in _data_retention_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders.extend(
            _generated_artifact_retention_schedule_offenders(
                tree,
                relative_path=path.relative_to(BACKEND_ROOT).as_posix(),
            )
        )

    assert offenders == [], _format_generated_artifact_retention_guard_failure(
        offenders
    )


def test_flow_transcribe_calls_bypass_shared_file_transcription_cache():
    offenders: list[str] = []
    for path in _flow_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        offenders.extend(
            _flow_transcribe_cache_bypass_offenders(
                tree,
                relative_path=path.relative_to(FLOW_SOURCE_ROOT).as_posix(),
            )
        )

    assert offenders == [], _format_flow_transcribe_cache_guard_failure(offenders)


def test_generated_artifact_retention_guard_reports_forbidden_scheduler():
    tree = ast.parse(
        "class Cleanup:\n"
        "    async def _cleanup_old_generated_flow_artifacts(self):\n"
        "        return None\n"
        "    def schedule(self, policy):\n"
        "        policy.retention_for_class('generated_artifact')\n"
        "        policy.retention_for_class(data_class='generated_artifact')\n"
    )

    offenders = _generated_artifact_retention_schedule_offenders(
        tree,
        relative_path="sample.py",
    )
    message = _format_generated_artifact_retention_guard_failure(offenders)

    assert offenders == [
        "sample.py:2:cleanup-helper",
        "sample.py:5:retention_for_class",
        "sample.py:6:retention_for_class",
    ]
    assert "run-private Flow file lifecycle owner" in message
    assert "T124" not in message
    assert "T128" not in message


def test_files_content_nulling_guard_reports_forbidden_update():
    tree = ast.parse(
        "def cleanup():\n"
        "    sa.update(Files).where(Files.id == file_id).values(blob=None)\n"
        "    update(Files).values({'text': None})\n"
    )

    offenders = _files_content_nulling_update_offenders(
        tree,
        relative_path="sample.py",
    )
    message = _format_files_content_lifecycle_guard_failure(offenders)

    assert offenders == ["sample.py:2:blob", "sample.py:3:text"]
    assert "run-private file lifecycle ownership" in message
    assert "T124" not in message
    assert "file lifecycle" in message


def test_flow_transcribe_cache_guard_reports_missing_kwargs_and_true_values():
    tree = ast.parse(
        "async def ok(transcriber, file, model):\n"
        "    await transcriber.transcribe(file, model, persist_cache_to_file=False)\n"
        "    await transcriber.transcribe_from_filepath('input.wav')\n"
        "async def missing(transcriber, file, model):\n"
        "    await transcriber.transcribe(file, model)\n"
        "async def true_value(transcriber, file, model):\n"
        "    await transcriber.transcribe(file, model, persist_cache_to_file=True)\n"
        "async def hidden(transcriber, file, model, kwargs):\n"
        "    await transcriber.transcribe(file, model, persist_cache_to_file=False, **kwargs)\n"
    )

    offenders = _flow_transcribe_cache_bypass_offenders(
        tree,
        relative_path="sample.py",
    )
    message = _format_flow_transcribe_cache_guard_failure(offenders)

    assert offenders == [
        "sample.py:5:missing-persist_cache_to_file-false",
        "sample.py:7:persist_cache_to_file-not-false",
        "sample.py:9:kwargs-bypass",
    ]
    assert "transcribe_from_filepath" not in message
    assert "Files.transcription cache" in message


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

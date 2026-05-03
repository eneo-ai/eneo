from __future__ import annotations

import ast
import importlib.util
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
from intric.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.flow_capability_manifest import (
    resolve_capability_for_tuple,
    validate_step_chain,
)


class CoverageSurface(str, Enum):
    CREATE = "create"
    EDIT = "edit"
    REGISTRY_BRIDGE = "registry_bridge"


class CoverageConcern(str, Enum):
    FCM_CHAIN = "fcm_chain"
    FORM_FIELD_CHAIN = "form_field_chain"
    PATTERN_REGISTRY = "pattern_registry"


@dataclass(frozen=True, slots=True)
class MatrixStep:
    step_order: int
    input_source: FlowInputSource
    input_type: FlowInputType
    output_type: FlowOutputType
    output_mode: FlowOutputMode = FlowOutputMode.PASS_THROUGH


@dataclass(frozen=True, slots=True)
class EditParityException:
    reason: str
    retire_when: str


@dataclass(frozen=True, slots=True)
class GoldenCoverageRow:
    row_id: str
    owner_module: str
    test_name: str
    surface: CoverageSurface
    concerns: frozenset[CoverageConcern]
    pattern_ids: frozenset[str]
    fcm_steps: tuple[MatrixStep, ...]
    edit_twin_id: str | None = None
    edit_exception: EditParityException | None = None


LIFECYCLE_MODULE = (
    "tests.unittests.flows.ai_builder.test_ai_builder_form_field_lifecycle"
)
BRIDGE_MODULE = (
    "tests.unittests.flows.ai_builder.test_ai_builder_materialization_bridge"
)

FORM_FIELD_CHAIN_STEPS = (
    MatrixStep(
        step_order=1,
        input_source=FlowInputSource.FLOW_INPUT,
        input_type=FlowInputType.TEXT,
        output_type=FlowOutputType.JSON,
    ),
    MatrixStep(
        step_order=2,
        input_source=FlowInputSource.PREVIOUS_STEP,
        input_type=FlowInputType.JSON,
        output_type=FlowOutputType.TEXT,
    ),
)

MUNICIPALITY_ONLY_TOKENS = frozenset(
    {
        "beslutsunderlag",
        "brukare",
        "handläggning",
        "ibic",
        "nämnd",
        "remiss",
        "tjänsteskrivelse",
        "ärendenummer",
    }
)

RETIRE_WHEN_PLACEHOLDERS = frozenset({"eventually", "later", "someday", "tbd"})
MIN_EDIT_ROW_PERCENTAGE = 20
MIN_FORM_FIELD_CHAIN_PERCENTAGE = 30

MATRIX_ROWS: tuple[GoldenCoverageRow, ...] = (
    GoldenCoverageRow(
        row_id="create_form_field_declare_only",
        owner_module=LIFECYCLE_MODULE,
        test_name="test_declared_input_field_without_step_use_attaches_to_final_step",
        surface=CoverageSurface.CREATE,
        concerns=frozenset({CoverageConcern.FORM_FIELD_CHAIN}),
        pattern_ids=frozenset({"form_field_runtime_inputs"}),
        fcm_steps=FORM_FIELD_CHAIN_STEPS,
        edit_exception=EditParityException(
            reason="Edit mode patches target steps and does not infer unreferenced fields.",
            retire_when="Remove when edit-mode form-field inference can attach fields to a selected target step.",
        ),
    ),
    GoldenCoverageRow(
        row_id="create_form_field_intermediate_chain",
        owner_module=LIFECYCLE_MODULE,
        test_name="test_intermediate_form_field_use_flows_through_structured_previous_field",
        surface=CoverageSurface.CREATE,
        concerns=frozenset({CoverageConcern.FORM_FIELD_CHAIN}),
        pattern_ids=frozenset({"form_field_runtime_inputs"}),
        fcm_steps=FORM_FIELD_CHAIN_STEPS,
        edit_exception=EditParityException(
            reason="Edit mode patches existing steps instead of re-materializing create-time chains.",
            retire_when="Remove when edit mode can materialize create-time intermediate form-field chains.",
        ),
    ),
    GoldenCoverageRow(
        row_id="create_form_field_multi_reference",
        owner_module=LIFECYCLE_MODULE,
        test_name="test_one_input_field_can_feed_two_step_bindings_once_each",
        surface=CoverageSurface.CREATE,
        concerns=frozenset({CoverageConcern.FORM_FIELD_CHAIN}),
        pattern_ids=frozenset({"form_field_runtime_inputs"}),
        fcm_steps=FORM_FIELD_CHAIN_STEPS,
        edit_twin_id="edit_form_field_multi_reference",
    ),
    GoldenCoverageRow(
        row_id="edit_form_field_multi_reference",
        owner_module=LIFECYCLE_MODULE,
        test_name="test_edit_form_field_multi_reference_feeds_two_step_bindings_once_each",
        surface=CoverageSurface.EDIT,
        concerns=frozenset({CoverageConcern.FORM_FIELD_CHAIN}),
        pattern_ids=frozenset({"form_field_runtime_inputs"}),
        fcm_steps=FORM_FIELD_CHAIN_STEPS,
    ),
    GoldenCoverageRow(
        row_id="pattern_registry_materialization_bridge",
        owner_module=BRIDGE_MODULE,
        test_name="TestArchetypeCoverage.test_every_positive_pattern_has_a_fixture",
        surface=CoverageSurface.REGISTRY_BRIDGE,
        concerns=frozenset(
            {CoverageConcern.FCM_CHAIN, CoverageConcern.PATTERN_REGISTRY}
        ),
        pattern_ids=frozenset(),
        fcm_steps=(),
    ),
)


def test_matrix_row_ids_are_unique() -> None:
    row_ids = [row.row_id for row in MATRIX_ROWS]

    assert len(row_ids) == len(set(row_ids))


def test_owner_tests_exist_without_importing_sibling_test_modules() -> None:
    for row in MATRIX_ROWS:
        assert _ast_has_test(row.owner_module, row.test_name), (
            f"{row.row_id} references missing owner {row.owner_module}.{row.test_name}"
        )


def test_pattern_ids_resolve_to_pattern_registry() -> None:
    known_pattern_ids = frozenset(PATTERN_REGISTRY)

    for row in MATRIX_ROWS:
        assert row.pattern_ids <= known_pattern_ids, (
            f"{row.row_id} references unknown pattern ids "
            f"{sorted(row.pattern_ids - known_pattern_ids)}"
        )


def test_fcm_step_tuples_and_chains_are_legal() -> None:
    for row in MATRIX_ROWS:
        for step in row.fcm_steps:
            assert (
                resolve_capability_for_tuple(
                    input_source=step.input_source,
                    input_type=step.input_type,
                    output_type=step.output_type,
                    output_mode=step.output_mode,
                )
                is not None
            ), f"{row.row_id} has unsupported FCM tuple {step}"
        assert validate_step_chain(row.fcm_steps) == ()


def test_create_rows_have_edit_twins_or_retiring_exceptions() -> None:
    rows_by_id = {row.row_id: row for row in MATRIX_ROWS}

    for row in MATRIX_ROWS:
        if row.surface is not CoverageSurface.CREATE:
            continue
        has_twin = row.edit_twin_id is not None
        has_exception = row.edit_exception is not None
        assert has_twin ^ has_exception, (
            f"{row.row_id} needs exactly one edit twin or retiring exception"
        )
        if row.edit_twin_id is not None:
            twin = rows_by_id[row.edit_twin_id]
            assert twin.surface is CoverageSurface.EDIT
            assert twin.concerns >= row.concerns
        if row.edit_exception is not None:
            _assert_retiring_exception(row.edit_exception)


def test_edit_and_form_field_ratios_hold() -> None:
    edit_rows = [row for row in MATRIX_ROWS if row.surface is CoverageSurface.EDIT]
    form_field_rows = [
        row for row in MATRIX_ROWS if CoverageConcern.FORM_FIELD_CHAIN in row.concerns
    ]

    assert len(edit_rows) * 100 >= len(MATRIX_ROWS) * MIN_EDIT_ROW_PERCENTAGE
    assert (
        len(form_field_rows) * 100 >= len(MATRIX_ROWS) * MIN_FORM_FIELD_CHAIN_PERCENTAGE
    )


def test_matrix_metadata_stays_domain_neutral() -> None:
    for row in MATRIX_ROWS:
        haystack = " ".join(_metadata_fragments(row)).lower()
        hits = {token for token in MUNICIPALITY_ONLY_TOKENS if token in haystack}

        assert not hits, f"{row.row_id} metadata contains {sorted(hits)}"


def _ast_has_test(module_name: str, test_name: str) -> bool:
    module_ast = _module_ast(module_name)
    parts = test_name.split(".")
    if len(parts) == 1:
        return any(
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == parts[0]
            for node in module_ast.body
        )
    if len(parts) == 2:
        class_name, method_name = parts
        for node in module_ast.body:
            if not isinstance(node, ast.ClassDef) or node.name != class_name:
                continue
            return any(
                isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                and child.name == method_name
                for child in node.body
            )
    return False


def _module_ast(module_name: str) -> ast.Module:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, f"Cannot resolve module {module_name}"
    assert spec.origin is not None, f"Module {module_name} has no source path"
    return ast.parse(Path(spec.origin).read_text())


def _assert_retiring_exception(exception: EditParityException) -> None:
    assert exception.reason.strip()
    retire_when = exception.retire_when.strip()
    assert len(retire_when) >= 20
    words = set(re.findall(r"[a-z]+", retire_when.lower()))
    assert words.isdisjoint(RETIRE_WHEN_PLACEHOLDERS)


def _metadata_fragments(row: GoldenCoverageRow) -> tuple[str, ...]:
    twin_fragments: tuple[str, ...] = ()
    if row.edit_twin_id is not None:
        twin_fragments = (row.edit_twin_id,)
    exception_fragments: tuple[str, ...] = ()
    if row.edit_exception is not None:
        exception_fragments = (
            row.edit_exception.reason,
            row.edit_exception.retire_when,
        )
    return (
        row.row_id,
        row.owner_module,
        row.test_name,
        row.surface.value,
        *(concern.value for concern in row.concerns),
        *row.pattern_ids,
        *twin_fragments,
        *exception_fragments,
    )

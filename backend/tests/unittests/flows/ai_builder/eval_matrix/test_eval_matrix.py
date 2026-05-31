"""Deterministic coverage fence for the Flow AI Builder capability matrix.

The matrix pairs a capability taxonomy (what kind of flow) with a composition
taxonomy (how steps compose). Goldens are real `FlowDraftSpecCore` instances:
each one is the authorability proof (the AI Builder authoring enums reject
shapes the builder cannot emit) and the regression fence (each must pass the
critic without an architecture blocker and resolve every declared form field).

Capabilities the builder cannot author yet (HTTP) are recorded as explicit
`KnownCapabilityGap` entries rather than faked into coverage. The matrix-state
ratchet keeps that honest: every row is classified `buildable`, `gap`, or
`planned`, and a gap that silently becomes authorable fails the suite.

LLM-output quality (prompt-token cost, edit/revise behaviour on real planner
output) is not asserted here; that signal lives in the local live-eval runner
(`scripts/flow_ai_builder_live_eval.py`), which needs a running API and model.
"""

from __future__ import annotations

import pytest

from intric.flows.enums import (
    AIBuilderInputSource,
    AIBuilderOutputMode,
    FlowOutputType,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputType,
    StepSpec,
)

from .derivation import (
    architecture_blockers,
    derive_composition_columns,
    unused_form_fields,
)
from .golden_cases import (
    GOLDEN_CASES,
    KNOWN_GAPS,
    BuildableGoldenCase,
    KnownCapabilityGap,
)
from .taxonomy import (
    MATRIX_ROW_STATES,
    CapabilityRow,
    CompositionColumn,
    expected_state,
)

_BUILDABLE_ROWS = {row for row in CapabilityRow if expected_state(row) == "buildable"}
_GAP_ROWS = {row for row in CapabilityRow if expected_state(row) == "gap"}
_PLANNED_ROWS = {row for row in CapabilityRow if expected_state(row) == "planned"}

_GOLDEN_ROWS = {case.capability_row for case in GOLDEN_CASES}
_GAP_ROWS_WITH_EVIDENCE = {gap.capability_row for gap in KNOWN_GAPS}


def test_every_capability_row_has_exactly_one_matrix_state() -> None:
    classified = _BUILDABLE_ROWS | _GAP_ROWS | _PLANNED_ROWS
    assert classified == set(CapabilityRow)
    # Partition, not overlap: a row cannot be two states at once.
    assert len(_BUILDABLE_ROWS) + len(_GAP_ROWS) + len(_PLANNED_ROWS) == len(
        set(CapabilityRow)
    )
    for row in CapabilityRow:
        assert expected_state(row) in MATRIX_ROW_STATES


def test_buildable_rows_each_have_a_golden() -> None:
    missing = _BUILDABLE_ROWS - _GOLDEN_ROWS
    assert not missing, f"rows marked buildable but missing a golden: {sorted(missing)}"


def test_gap_rows_have_evidence_and_no_golden() -> None:
    assert _GAP_ROWS_WITH_EVIDENCE == _GAP_ROWS
    leaked = _GAP_ROWS & _GOLDEN_ROWS
    assert not leaked, f"gap rows must not have buildable goldens: {sorted(leaked)}"


def test_planned_rows_are_pending_not_covered() -> None:
    # Planned rows are visible, enforced debt: not yet seeded and not a gap.
    assert not (_PLANNED_ROWS & _GOLDEN_ROWS)
    assert not (_PLANNED_ROWS & _GAP_ROWS_WITH_EVIDENCE)


def test_no_golden_targets_a_planned_or_gap_row() -> None:
    # A golden may only exist for a row the matrix declares buildable; adding one
    # for a planned row without promoting the row would be silent drift.
    assert _GOLDEN_ROWS <= _BUILDABLE_ROWS


def test_http_gap_is_not_silently_authorable() -> None:
    # The ratchet: HTTP rows are gaps only because the authoring enums cannot
    # express them. If HTTP authoring is ever added, this fails and forces the
    # gap rows to be promoted to buildable with real goldens.
    builder_sources = {source.value for source in AIBuilderInputSource}
    builder_modes = {mode.value for mode in AIBuilderOutputMode}
    assert "http_get" not in builder_sources
    assert "http_post" not in builder_sources
    assert "http_post" not in builder_modes


@pytest.mark.parametrize("gap", KNOWN_GAPS, ids=lambda gap: gap.capability_row.value)
def test_known_gaps_runtime_support_is_real_but_not_authorable(
    gap: KnownCapabilityGap,
) -> None:
    # The gap must claim some runtime capability (typed Flow enum members) and
    # every claimed member must be absent from the AI Builder authoring enums.
    assert gap.runtime_input_sources or gap.runtime_output_modes
    builder_sources = {source.value for source in AIBuilderInputSource}
    builder_modes = {mode.value for mode in AIBuilderOutputMode}
    for source in gap.runtime_input_sources:
        assert source.value not in builder_sources
    for mode in gap.runtime_output_modes:
        assert mode.value not in builder_modes
    assert gap.why_not_authorable.strip()
    assert gap.product_decision.strip()


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
def test_each_golden_has_no_architecture_blockers(case: BuildableGoldenCase) -> None:
    # Draft preflight only (no materializer run): the spec is buildable on its
    # own terms. End-to-end materialization stays the live-eval runner's job.
    blockers = architecture_blockers(case.spec)
    assert not blockers, (
        f"{case.case_id}: critic reports architecture blockers {blockers}"
    )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
def test_each_golden_resolves_its_form_fields(case: BuildableGoldenCase) -> None:
    unused = unused_form_fields(case.spec)
    assert not unused, (
        f"{case.case_id}: declared form fields never referenced: {unused}"
    )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
def test_declared_columns_match_derived(case: BuildableGoldenCase) -> None:
    derived = derive_composition_columns(case)
    assert derived == case.declared_columns, (
        f"{case.case_id}: declared {sorted(c.value for c in case.declared_columns)} "
        f"but spec shape derives {sorted(c.value for c in derived)}"
    )


def test_docx_fill_and_create_are_distinct_shapes() -> None:
    fill = _single_golden(CapabilityRow.DOCUMENT_TO_DOCX_TEMPLATE)
    create = _single_golden(CapabilityRow.DOCUMENT_TO_DOCX_CREATE)
    fill_modes = {step.output_mode for step in fill.spec.steps if _is_docx(step)}
    create_modes = {step.output_mode for step in create.spec.steps if _is_docx(step)}
    assert fill_modes == {AIBuilderOutputMode.TEMPLATE_FILL}
    assert create_modes == {AIBuilderOutputMode.PASS_THROUGH}
    assert fill.spec.spec_hash() != create.spec.spec_hash()


def test_golden_case_ids_are_unique() -> None:
    ids = [case.case_id for case in GOLDEN_CASES]
    assert len(ids) == len(set(ids))


def _derive(
    steps: list[StepSpec],
    *,
    form_fields: list[FormFieldSpec] | None = None,
    via_edit: bool = False,
) -> frozenset[CompositionColumn]:
    case = BuildableGoldenCase(
        case_id="derivation_probe",
        capability_row=CapabilityRow.SUMMARIZE_TEXT,
        spec=FlowDraftSpecCore(flow_name="probe", steps=steps, form_fields=form_fields),
        declared_columns=frozenset(),
        via_edit=via_edit,
    )
    return derive_composition_columns(case)


def _probe_step(
    ref: str,
    instructions: str,
    *,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=ref,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
    )


def test_two_step_flow_is_not_advanced_multi_capability() -> None:
    # Three flattened FCM capability ids (input_document, input_text,
    # output_mode_pass_through) but only two steps: not advanced composition.
    columns = _derive(
        [
            _probe_step("step_a", "Läs dokument.", input_type=InputType.DOCUMENT),
            _probe_step(
                "step_b",
                "Skriv text från {{step_a.output.text}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ]
    )
    assert CompositionColumn.ADVANCED_MULTI_CAPABILITY not in columns


def test_chain_without_a_combining_step_is_not_form_fields_chain() -> None:
    # step_a uses a form field, step_b consumes step_a but no later step combines
    # a form field with prior output: this is not the chain shape.
    columns = _derive(
        [
            _probe_step("step_a", "Sammanställ {{topic}}."),
            _probe_step(
                "step_b",
                "Utveckla {{step_a.output.text}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
        form_fields=[FormFieldSpec(name="topic", type="text", label="Ämne")],
    )
    assert CompositionColumn.FORM_FIELDS_CHAIN not in columns


def test_declare_only_not_derived_when_a_later_step_uses_a_form_field() -> None:
    columns = _derive(
        [
            _probe_step("step_a", "Sammanställ {{topic}}."),
            _probe_step(
                "step_b",
                "Lägg till mer om {{topic}}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
        form_fields=[FormFieldSpec(name="topic", type="text", label="Ämne")],
    )
    assert CompositionColumn.FORM_FIELDS_DECLARE_ONLY not in columns


def _single_golden(row: CapabilityRow) -> BuildableGoldenCase:
    matches = [case for case in GOLDEN_CASES if case.capability_row == row]
    assert len(matches) == 1, f"expected exactly one golden for {row.value}"
    return matches[0]


def _is_docx(step: object) -> bool:
    return getattr(step, "output_type", None) == FlowOutputType.DOCX

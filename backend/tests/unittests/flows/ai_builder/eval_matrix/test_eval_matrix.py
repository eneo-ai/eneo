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

Canonical command preparation and deterministic create-mode materialization are
asserted here; LLM-output quality (prompt-token cost, edit/revise behaviour on
real planner output) lives in the local live-eval runner
(`scripts/flow_ai_builder_live_eval.py`), which needs a running API and model.
"""

from __future__ import annotations

import pytest

from intric.flows.ai_builder.pattern_registry import PATTERN_REGISTRY
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
from tests.unittests.flows.ai_builder.authoring_command_assertions import (
    assert_create_spec_materializes_through_authoring_command_async,
    assert_create_spec_prepares_through_authoring_command,
)

from .coverage import (
    composition_ratio,
    distinct_rows_per_column,
    http_required_goldens,
    http_threshold_violations,
    not_applicable_violations,
    unsatisfied_required_columns,
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
    MatrixRowState,
    expected_state,
    row_complexity_policy,
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
    # Draft preflight checks architecture blockers before the canonical
    # authoring/materialization assertion below exercises the execution boundary.
    blockers = architecture_blockers(
        case.spec, aggregation_intent=case.aggregation_intent
    )
    assert not blockers, (
        f"{case.case_id}: critic reports architecture blockers {blockers}"
    )


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
def test_buildable_golden_prepares_through_canonical_authoring_command(
    case: BuildableGoldenCase,
) -> None:
    assert_create_spec_prepares_through_authoring_command(case.spec)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
async def test_buildable_golden_materializes_through_canonical_authoring_command(
    case: BuildableGoldenCase,
) -> None:
    await assert_create_spec_materializes_through_authoring_command_async(case.spec)


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
    fills = [
        c
        for c in GOLDEN_CASES
        if c.capability_row == CapabilityRow.DOCUMENT_TO_DOCX_TEMPLATE
    ]
    creates = [
        c
        for c in GOLDEN_CASES
        if c.capability_row == CapabilityRow.DOCUMENT_TO_DOCX_CREATE
    ]
    assert fills and creates
    fill_modes = {
        step.output_mode for c in fills for step in c.spec.steps if _is_docx(step)
    }
    create_modes = {
        step.output_mode for c in creates for step in c.spec.steps if _is_docx(step)
    }
    # Fill always uses TEMPLATE_FILL; create always generates via PASS_THROUGH.
    assert fill_modes == {AIBuilderOutputMode.TEMPLATE_FILL}
    assert create_modes == {AIBuilderOutputMode.PASS_THROUGH}
    fill_hashes = {c.spec.spec_hash() for c in fills}
    create_hashes = {c.spec.spec_hash() for c in creates}
    assert fill_hashes.isdisjoint(create_hashes)


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


def _is_docx(step: StepSpec) -> bool:
    return step.output_type is FlowOutputType.DOCX


# --- Row complexity policy (REQUIRED / ALLOWED / NOT_APPLICABLE) ---


def test_required_complexity_columns_are_covered() -> None:
    unsatisfied = unsatisfied_required_columns()
    assert not unsatisfied, (
        "rows missing a golden for a REQUIRED complexity column: "
        + ", ".join(
            f"{row.value}:{[c.value for c in cols]}"
            for row, cols in unsatisfied.items()
        )
    )


def test_no_golden_derives_a_not_applicable_column() -> None:
    violations = not_applicable_violations()
    assert not violations, (
        "goldens deriving a NOT_APPLICABLE complexity column: "
        + ", ".join(f"{case_id}:{col.value}" for case_id, col in violations)
    )


def test_not_applicable_violation_is_detected() -> None:
    # A single-step golden on an inherently-multi-step row derives
    # basic_single_step, which its policy marks NOT_APPLICABLE.
    degenerate = BuildableGoldenCase(
        case_id="degenerate_quality_chain",
        capability_row=CapabilityRow.MULTI_STEP_QUALITY_CHAIN,
        spec=FlowDraftSpecCore(
            flow_name="probe",
            steps=[_probe_step("step_a", "Gör allt i ett steg.")],
        ),
        declared_columns=frozenset(),
    )
    violations = not_applicable_violations([degenerate])
    assert (
        "degenerate_quality_chain",
        CompositionColumn.BASIC_SINGLE_STEP,
    ) in violations


def test_composition_ratio_uses_buildable_denominator() -> None:
    basic = BuildableGoldenCase(
        case_id="basic_probe",
        capability_row=CapabilityRow.SUMMARIZE_TEXT,
        spec=FlowDraftSpecCore(
            flow_name="probe", steps=[_probe_step("step_a", "Sammanfatta texten.")]
        ),
        declared_columns=frozenset(),
    )
    multi = BuildableGoldenCase(
        case_id="multi_probe",
        capability_row=CapabilityRow.SUMMARIZE_TEXT,
        spec=FlowDraftSpecCore(
            flow_name="probe",
            steps=[
                _probe_step("step_a", "Steg ett över texten."),
                _probe_step(
                    "step_b",
                    "Bygg vidare på {{step_a.output.text}}.",
                    input_source=InputSource.PREVIOUS_STEP,
                ),
            ],
        ),
        declared_columns=frozenset(),
    )
    # One of two goldens is single-step: the denominator is the golden count.
    assert composition_ratio(CompositionColumn.BASIC_SINGLE_STEP, [basic, multi]) == 0.5


def test_http_threshold_is_deferred_while_gap_and_reactivates() -> None:
    for row in (CapabilityRow.HTTP_POST_CALL, CapabilityRow.HTTP_GET_CALL):
        assert expected_state(row) == "gap"
    # Deferred to zero while the row is a gap; the obligation returns the moment
    # the row is promoted to buildable.
    assert http_required_goldens("gap") == 0
    assert http_required_goldens("buildable") == 2


def test_only_buildable_rows_have_a_complexity_policy() -> None:
    for row in CapabilityRow:
        policy = row_complexity_policy(row)
        if expected_state(row) == "buildable":
            assert policy is not None, f"{row.value} is buildable but has no policy"
        else:
            assert policy is None, (
                f"{row.value} is {expected_state(row)} but carries a policy"
            )


def _probe_golden(
    case_id: str, row: CapabilityRow, instructions: str
) -> BuildableGoldenCase:
    return BuildableGoldenCase(
        case_id=case_id,
        capability_row=row,
        spec=FlowDraftSpecCore(
            flow_name="probe", steps=[_probe_step("step_a", instructions)]
        ),
        declared_columns=frozenset(),
    )


def test_http_threshold_violations_gap_undercoverage_satisfied() -> None:
    # Gap: requirement deferred to zero, so no violations against the real matrix.
    assert http_threshold_violations() == []

    def post_is_buildable(row: CapabilityRow) -> MatrixRowState:
        return "buildable" if row is CapabilityRow.HTTP_POST_CALL else "gap"

    one = [
        _probe_golden("http_1", CapabilityRow.HTTP_POST_CALL, "Anropa ett externt API.")
    ]
    assert CapabilityRow.HTTP_POST_CALL in http_threshold_violations(
        one, state_of=post_is_buildable
    )

    two = one + [
        _probe_golden("http_2", CapabilityRow.HTTP_POST_CALL, "Anropa ett annat API.")
    ]
    assert CapabilityRow.HTTP_POST_CALL not in http_threshold_violations(
        two, state_of=post_is_buildable
    )


def test_distinct_rows_per_column_counts_rows_not_cases() -> None:
    same_row = [
        _probe_golden("a", CapabilityRow.SUMMARIZE_TEXT, "Sammanfatta första texten."),
        _probe_golden("b", CapabilityRow.SUMMARIZE_TEXT, "Sammanfatta andra texten."),
    ]
    counts = distinct_rows_per_column(same_row)
    # Two single-step cases on one row count as one row for the column.
    assert counts[CompositionColumn.BASIC_SINGLE_STEP] == 1


# --- Hard global coverage thresholds ---

_MIN_ROWS_PER_COLUMN = 3
_MIN_CHAIN_SHARE = 0.30
_MIN_EDIT_SHARE = 0.20


def test_every_composition_column_spans_at_least_three_rows() -> None:
    counts = distinct_rows_per_column()
    for column in CompositionColumn:
        assert counts.get(column, 0) >= _MIN_ROWS_PER_COLUMN, (
            f"{column.value} is covered by only {counts.get(column, 0)} rows"
        )


def test_form_fields_chain_meets_minimum_share() -> None:
    share = composition_ratio(CompositionColumn.FORM_FIELDS_CHAIN)
    assert share >= _MIN_CHAIN_SHARE, (
        f"form_fields_chain share {share:.2f} is below {_MIN_CHAIN_SHARE}"
    )


def test_edit_path_meets_minimum_share() -> None:
    share = composition_ratio(CompositionColumn.EDIT_PATH)
    assert share >= _MIN_EDIT_SHARE, (
        f"edit_path share {share:.2f} is below {_MIN_EDIT_SHARE}"
    )


def test_no_http_threshold_violations() -> None:
    assert http_threshold_violations() == []


# --- Anti-slop quality + Pattern Registry grounding ---

# Municipality / case-management vocabulary the matrix must stay free of: the
# builder is general-purpose, so goldens use domain-neutral scenarios.
_BANNED_DOMAIN_TERMS: tuple[str, ...] = (
    "tjänsteskrivelse",
    "tjansteskrivelse",
    "nämnd",
    "remiss",
    "ärende",
    "arende",
    "beslutsunderlag",
    "handläggare",
    "handlaggare",
)

_MIN_INSTRUCTION_CHARS = 15

# Capability rows that intentionally have no direct Pattern Registry archetype:
# DOCX create is the pass-through variant of the docx_template pattern, HTTP is a
# runtime-only gap, and underlag_till_text is a composition concept rather than a
# single archetype. Anything else must map to a registered pattern id.
_ROWS_WITHOUT_DIRECT_PATTERN: frozenset[CapabilityRow] = frozenset(
    {
        CapabilityRow.DOCUMENT_TO_DOCX_CREATE,
        CapabilityRow.HTTP_POST_CALL,
        CapabilityRow.HTTP_GET_CALL,
        CapabilityRow.UNDERLAG_TILL_TEXT,
    }
)


def _quality_violations(case: BuildableGoldenCase) -> list[str]:
    problems: list[str] = []
    if len(case.spec.flow_name.strip()) < 6:
        problems.append(f"{case.case_id}: flow_name is too short to be meaningful")
    blob = case.spec.flow_name.casefold()
    for step in case.spec.steps:
        instructions = step.assistant_spec.instructions.strip()
        if len(instructions) < _MIN_INSTRUCTION_CHARS:
            problems.append(
                f"{case.case_id}/{step.plan_step_ref}: instructions too thin"
            )
        if instructions.casefold() in {
            step.plan_step_ref.casefold(),
            step.name.casefold(),
        }:
            problems.append(
                f"{case.case_id}/{step.plan_step_ref}: instructions restate the name"
            )
        blob += " " + instructions.casefold() + " " + step.name.casefold()
    for term in _BANNED_DOMAIN_TERMS:
        if term in blob:
            problems.append(f"{case.case_id}: uses domain-specific term {term!r}")
    return problems


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda case: case.case_id)
def test_golden_instructions_meet_quality_standards(case: BuildableGoldenCase) -> None:
    problems = _quality_violations(case)
    assert not problems, "; ".join(problems)


def test_every_capability_row_grounds_to_a_pattern_or_known_exception() -> None:
    pattern_ids = set(PATTERN_REGISTRY.keys())
    for row in CapabilityRow:
        assert row.value in pattern_ids or row in _ROWS_WITHOUT_DIRECT_PATTERN, (
            f"{row.value} is neither a registered pattern nor a known exception"
        )
    # A stale exception (a row that has since gained a pattern) must be removed.
    for row in _ROWS_WITHOUT_DIRECT_PATTERN:
        assert row.value not in pattern_ids, (
            f"{row.value} now has a Pattern Registry archetype; drop the exception"
        )

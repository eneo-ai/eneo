from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_domain_models import (
    FlowDraftSpecCore,
    StepSpec,
)
from intric.flows.enums import (
    AIBuilderInputSource,
    AIBuilderInputType,
    AIBuilderOutputMode,
    FlowInputType,
    FlowOutputType,
)
from tests.integration.flows.ai_builder.benchmark.cases import ReliabilityCorpusCase

DERIVATION_RULES_VERSION = 1


@dataclass(frozen=True, slots=True)
class PlanObservedMechanics:
    first_runtime_input_type: str | None
    terminal_output_type: str | None
    terminal_output_mode: str | None
    step_count: int
    step_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanDerivedMechanics:
    derivation_rules_version: int
    has_transcription_step: bool | None
    has_sectioning_step: bool | None
    has_source_grounding_step: bool | None
    has_docx_template_fill: bool | None
    uses_underlag_till_text_correctly: bool | None
    uses_runtime_input_fields_correctly: bool | None
    all_step_input_output_pairs_compatible: bool | None
    revision_preserved_unrelated_mechanics: bool | None
    revision_applied_requested_change: bool | None


@dataclass(frozen=True, slots=True)
class PlanMechanicsScore:
    observed: PlanObservedMechanics
    derived: PlanDerivedMechanics
    typed_pass_count: int
    typed_fail_count: int
    typed_failures: tuple[str, ...]


def score_plan_mechanics(
    *,
    spec: FlowDraftSpecCore,
    corpus_case: ReliabilityCorpusCase,
) -> PlanMechanicsScore:
    observed = observe_plan_mechanics(spec)
    underlag_correct = uses_underlag_till_text_correctly(spec)
    runtime_fields_correct = uses_runtime_input_fields_correctly(
        spec,
        expected_secondary_field_names=(
            corpus_case.expected_secondary_runtime_field_names
        ),
    )
    derived = PlanDerivedMechanics(
        derivation_rules_version=DERIVATION_RULES_VERSION,
        has_transcription_step=any(_is_transcription_step(step) for step in spec.steps),
        has_sectioning_step=_has_sectioning_step(spec.steps),
        has_source_grounding_step=_has_source_grounding_step(spec.steps),
        has_docx_template_fill=any(
            step.output_mode == AIBuilderOutputMode.TEMPLATE_FILL for step in spec.steps
        ),
        uses_underlag_till_text_correctly=underlag_correct,
        uses_runtime_input_fields_correctly=runtime_fields_correct,
        all_step_input_output_pairs_compatible=all_step_input_output_pairs_compatible(
            spec.steps
        ),
        revision_preserved_unrelated_mechanics=None,
        revision_applied_requested_change=None,
    )
    check_results = _typed_check_results(
        observed=observed,
        derived=derived,
        corpus_case=corpus_case,
    )
    failures = [check_name for check_name, passed in check_results if not passed]
    return PlanMechanicsScore(
        observed=observed,
        derived=derived,
        typed_pass_count=len(check_results) - len(failures),
        typed_fail_count=len(failures),
        typed_failures=tuple(failures),
    )


def observe_plan_mechanics(spec: FlowDraftSpecCore) -> PlanObservedMechanics:
    first_runtime_step = next(
        (
            step
            for step in spec.steps
            if step.input_source == AIBuilderInputSource.FLOW_INPUT
        ),
        None,
    )
    terminal_step = spec.steps[-1] if spec.steps else None
    return PlanObservedMechanics(
        first_runtime_input_type=(
            first_runtime_step.input_type.value if first_runtime_step else None
        ),
        terminal_output_type=terminal_step.output_type.value if terminal_step else None,
        terminal_output_mode=terminal_step.output_mode.value if terminal_step else None,
        step_count=len(spec.steps),
        step_roles=tuple(_step_role(step) for step in spec.steps),
    )


def uses_underlag_till_text_correctly(spec: FlowDraftSpecCore) -> bool | None:
    required_boundaries = list(_source_material_boundaries(spec.steps))
    if not required_boundaries:
        return None
    return all(
        _question_mentions_immediate_structured(step, previous_step)
        and _question_mentions_prior_text_source(step, prior_text_steps)
        for step, previous_step, prior_text_steps in required_boundaries
    )


def uses_runtime_input_fields_correctly(
    spec: FlowDraftSpecCore,
    *,
    expected_secondary_field_names: Iterable[str],
) -> bool | None:
    form_fields = tuple(spec.form_fields or ())
    if not form_fields:
        return True
    expected_fields = {
        field_name.casefold() for field_name in expected_secondary_field_names
    }
    actual_fields = {field.name.casefold() for field in form_fields}
    if actual_fields & _primary_runtime_field_names():
        return False
    return actual_fields <= expected_fields


def all_step_input_output_pairs_compatible(steps: Sequence[StepSpec]) -> bool:
    for previous_step, step in zip(steps, steps[1:], strict=False):
        if step.input_source != AIBuilderInputSource.PREVIOUS_STEP:
            continue
        if _question_binding(step):
            continue
        if step.input_type.value != previous_step.output_type.value:
            return False
    return True


def _typed_check_results(
    *,
    observed: PlanObservedMechanics,
    derived: PlanDerivedMechanics,
    corpus_case: ReliabilityCorpusCase,
) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    expected_shape = corpus_case.expected_flow_shape
    checks.append(
        (
            "first_runtime_input_type",
            observed.first_runtime_input_type == expected_shape.runtime_input.value,
        )
    )
    checks.append(
        (
            "terminal_output_type",
            observed.terminal_output_type == expected_shape.terminal_output.value,
        )
    )
    checks.append(
        ("minimum_step_count", observed.step_count >= len(expected_shape.steps))
    )
    if derived.all_step_input_output_pairs_compatible is not None:
        checks.append(
            (
                "all_step_input_output_pairs_compatible",
                derived.all_step_input_output_pairs_compatible,
            )
        )
    if derived.uses_underlag_till_text_correctly is not None:
        checks.append(
            (
                "uses_underlag_till_text_correctly",
                derived.uses_underlag_till_text_correctly,
            )
        )
    if derived.uses_runtime_input_fields_correctly is not None:
        checks.append(
            (
                "uses_runtime_input_fields_correctly",
                derived.uses_runtime_input_fields_correctly,
            )
        )
    if expected_shape.runtime_input == FlowInputType.AUDIO:
        checks.append(
            ("has_transcription_step", derived.has_transcription_step is True)
        )
    if expected_shape.terminal_output == FlowOutputType.DOCX:
        checks.append(("render_docx_step", "render_docx" in observed.step_roles))
    elif expected_shape.terminal_output == FlowOutputType.PDF:
        checks.append(("render_pdf_step", "render_pdf" in observed.step_roles))
    return checks


def _source_material_boundaries(
    steps: Sequence[StepSpec],
) -> Iterable[tuple[StepSpec, StepSpec, tuple[StepSpec, ...]]]:
    for index, step in enumerate(steps):
        if index == 0 or step.input_source != AIBuilderInputSource.PREVIOUS_STEP:
            continue
        previous_step = steps[index - 1]
        if previous_step.output_type != FlowOutputType.JSON:
            continue
        prior_text_steps = tuple(
            prior_step
            for prior_step in steps[:index]
            if prior_step.output_type == FlowOutputType.TEXT
        )
        if not prior_text_steps:
            continue
        yield step, previous_step, prior_text_steps


def _question_mentions_immediate_structured(
    step: StepSpec,
    previous_step: StepSpec,
) -> bool:
    question = _question_binding(step)
    if question is None:
        return False
    return f"{{{{ {previous_step.plan_step_ref}.output.structured }}}}" in question


def _question_mentions_prior_text_source(
    step: StepSpec,
    prior_text_steps: Sequence[StepSpec],
) -> bool:
    question = _question_binding(step)
    if question is None:
        return False
    return any(
        f"{{{{ {prior_step.plan_step_ref}.output.text }}}}" in question
        for prior_step in prior_text_steps
    )


def _question_binding(step: StepSpec) -> str | None:
    if not isinstance(step.input_bindings, dict):
        return None
    question = step.input_bindings.get("question")
    return question if isinstance(question, str) and question.strip() else None


def _is_transcription_step(step: StepSpec) -> bool:
    return step.output_mode == AIBuilderOutputMode.TRANSCRIBE_ONLY


def _has_source_grounding_step(steps: Sequence[StepSpec]) -> bool:
    return any(
        question is not None
        and "{{ step_" in question
        and (".output.text" in question or ".output.structured" in question)
        for question in (_question_binding(step) for step in steps)
    )


def _has_sectioning_step(steps: Sequence[StepSpec]) -> bool:
    return any(_json_schema_contains_array(step.output_contract) for step in steps)


def _step_role(step: StepSpec) -> str:
    if step.output_mode == AIBuilderOutputMode.TRANSCRIBE_ONLY:
        return "transcribe"
    if step.output_mode == AIBuilderOutputMode.TEMPLATE_FILL:
        return "fill_docx_template"
    if step.output_type == FlowOutputType.JSON:
        return "extract"
    if step.output_type == FlowOutputType.DOCX:
        return "render_docx"
    if step.output_type == FlowOutputType.PDF:
        return "render_pdf"
    if (
        step.input_type == AIBuilderInputType.JSON
        and step.output_type == FlowOutputType.TEXT
    ):
        return "compose_text"
    return f"{step.input_type.value}_to_{step.output_type.value}"


def _primary_runtime_field_names() -> frozenset[str]:
    upload_input_values = {
        input_type.value
        for input_type in FlowInputType
        if input_type
        not in {
            FlowInputType.ANY,
            FlowInputType.JSON,
            FlowInputType.TEXT,
        }
    }
    return frozenset(
        field_name
        for input_value in upload_input_values
        for field_name in (input_value, f"{input_value}s")
    )


def _json_schema_contains_array(schema: object) -> bool:
    if isinstance(schema, dict):
        if schema.get("type") == "array":
            return True
        return any(_json_schema_contains_array(value) for value in schema.values())
    if isinstance(schema, list):
        return any(_json_schema_contains_array(value) for value in schema)
    return False

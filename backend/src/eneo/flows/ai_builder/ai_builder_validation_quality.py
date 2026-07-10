from __future__ import annotations

import json

from eneo.flows.ai_builder.ai_builder_domain_models import (
    LintSeverity,
)
from eneo.flows.ai_builder.ai_builder_form_field_usage import (
    find_unused_form_fields,
)
from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    top_level_schema_property_names,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding
from eneo.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
    referenced_step_refs,
)

_VAGUE_NAMES = {"steg", "step", "bearbeta", "process", "hantera", "handle"}
_MULTI_GOAL_INDICATORS = [
    " och sedan ",
    " and then ",
    " därefter ",
    " followed by ",
]


def lint_all_previous_steps_overuse(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    count = sum(
        1 for s in spec.steps if s.input_source == InputSource.ALL_PREVIOUS_STEPS
    )
    if count > 1:
        result.add_warning(
            step_ref=None,
            code="all_previous_overuse",
            message=(
                f"{count} steps use 'all_previous_steps'. "
                "This increases token usage. Consider using 'previous_step' where possible."
            ),
        )


def lint_vague_step_names(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for step in spec.steps:
        normalized = step.name.strip().casefold()
        if normalized in _VAGUE_NAMES or len(normalized) < 3:
            result.add_warning(
                step_ref=step.plan_step_ref,
                code="vague_step_name",
                message=f"Step name '{step.name}' is vague. Use a more descriptive name.",
                severity=LintSeverity.INFO,
            )


def lint_multi_goal_prompts(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    document_body_writer_refs = frozenset(spec.document_body_writer_step_refs or ())
    for step in spec.steps:
        is_model_document_body_writer = (
            step.plan_step_ref in document_body_writer_refs
            and step.output_mode is OutputMode.PASS_THROUGH
            and step.output_type is OutputType.TEXT
        )
        if is_model_document_body_writer:
            continue
        if _should_warn_multi_goal_prompt(step):
            result.add_warning(
                step_ref=step.plan_step_ref,
                code="multi_goal_prompt",
                message=(
                    "Step instructions may contain multiple goals. "
                    "Consider splitting into separate steps for better results."
                ),
            )


def _should_warn_multi_goal_prompt(step: StepSpec) -> bool:
    instructions = step.assistant_spec.instructions
    if len(instructions) <= 300:
        return False
    instructions_lower = instructions.casefold()
    return any(indicator in instructions_lower for indicator in _MULTI_GOAL_INDICATORS)


def lint_single_step_flow(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    if len(spec.steps) == 1:
        result.add_warning(
            step_ref=None,
            code="single_step_flow",
            message=(
                "Single-step flows work but don't leverage flow chaining. "
                "Consider whether a regular assistant would suffice."
            ),
            severity=LintSeverity.INFO,
        )


def lint_json_output_without_contract(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for index, step in enumerate(spec.steps):
        # Keep simple terminal JSON flows lightweight. A contract becomes high-value
        # once another step needs to build on the structured output.
        has_downstream_steps = index < len(spec.steps) - 1
        if (
            step.output_type == OutputType.JSON
            and step.output_contract is None
            and has_downstream_steps
        ):
            result.add_warning(
                step_ref=step.plan_step_ref,
                code="json_output_no_contract",
                message=(
                    "Step has output_type 'json' but no output_contract. "
                    "Adding one enables structured variable access for downstream steps."
                ),
                severity=LintSeverity.INFO,
            )


def lint_contract_instruction_alignment(
    spec: FlowDraftSpecCore,
    result: SpecValidationResult,
) -> None:
    for step in spec.steps:
        contract = step.output_contract
        if not isinstance(contract, dict):
            continue
        property_names = top_level_schema_property_names(contract)
        instructions = step.assistant_spec.instructions.casefold()
        if not property_names:
            continue
        missing = [
            name for name in property_names if name.casefold() not in instructions
        ]
        if len(missing) == len(property_names):
            result.add_warning(
                step_ref=step.plan_step_ref,
                code="contract_instruction_mismatch",
                message=(
                    "Instructions do not mention any declared output_contract fields. "
                    "Name the expected fields explicitly to improve JSON reliability."
                ),
            )


def lint_unused_form_fields(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for field_name in find_unused_form_fields(spec):
        result.add_warning(
            step_ref=None,
            code="unused_form_field",
            message=f"Form field '{field_name}' is declared but never referenced in any step.",
            severity=LintSeverity.INFO,
        )


def lint_shadowed_form_field_bare_references(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    form_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    if not form_fields:
        return

    step_refs = {step.plan_step_ref: index + 1 for index, step in enumerate(spec.steps)}
    warned: set[tuple[str, str]] = set()
    for step in spec.steps:
        for template in _iter_step_templates(step):
            refs = analyze_template(
                template, step_refs=step_refs, form_field_names=form_fields
            )
            for reference in refs:
                if (
                    reference.kind is TemplateReferenceKind.RUNTIME
                    and reference.head in form_fields
                    and not reference.tail
                ):
                    warning_key = (step.plan_step_ref, reference.head)
                    if warning_key in warned:
                        continue
                    warned.add(warning_key)
                    result.add_warning(
                        step_ref=step.plan_step_ref,
                        code="shadowed_form_field_bare_reference",
                        message=(
                            f"Variable '{{{{{reference.head}}}}}' resolves to an Eneo "
                            f"runtime value. Use '{{{{flow_input.{reference.head}}}}}' "
                            "to read the form field."
                        ),
                        severity=LintSeverity.INFO,
                    )


def lint_all_previous_with_specific_refs(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    step_refs = {step.plan_step_ref: index + 1 for index, step in enumerate(spec.steps)}
    form_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    for step in spec.steps:
        if step.input_source != InputSource.ALL_PREVIOUS_STEPS:
            continue
        question = effective_question_binding(step.input_bindings)
        if question is None:
            continue
        refs = analyze_template(
            question, step_refs=step_refs, form_field_names=form_fields
        )
        referenced = referenced_step_refs(refs)
        if 0 < len(referenced) <= 2:
            result.add_warning(
                step_ref=step.plan_step_ref,
                code="all_previous_with_specific_refs",
                message=(
                    "Step uses 'all_previous_steps' but the underlag only targets a small number "
                    "of explicit step references. Consider a narrower chaining/input-binding design "
                    "to reduce duplication and token usage."
                ),
                severity=LintSeverity.INFO,
            )


def lint_unfiltered_structured_interpolation(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    step_refs = {step.plan_step_ref: index + 1 for index, step in enumerate(spec.steps)}
    form_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    json_producing_refs = {
        step.plan_step_ref for step in spec.steps if step.output_type == OutputType.JSON
    }
    json_orders = {
        index + 1
        for index, step in enumerate(spec.steps)
        if step.output_type == OutputType.JSON
    }

    for step in spec.steps:
        question = effective_question_binding(step.input_bindings)
        if question is None:
            continue
        refs = analyze_template(
            question, step_refs=step_refs, form_field_names=form_fields
        )
        if any(
            reference.kind is TemplateReferenceKind.STEP
            and reference.tail == "output.text"
            and (
                (reference.step_ref in json_producing_refs)
                or (reference.step_order in json_orders)
            )
            for reference in refs
        ):
            result.add_warning(
                step_ref=step.plan_step_ref,
                code="json_output_text_interpolation",
                message=(
                    "Underlag interpolates output.text from a JSON-producing step. "
                    "Prefer output.structured.<field> when only specific fields are needed."
                ),
                severity=LintSeverity.INFO,
            )


def _iter_step_templates(step: StepSpec) -> list[str]:
    templates = [step.assistant_spec.instructions]
    for payload in (step.input_bindings, step.output_config):
        if payload is not None:
            templates.append(json.dumps(payload, ensure_ascii=False))
    return templates

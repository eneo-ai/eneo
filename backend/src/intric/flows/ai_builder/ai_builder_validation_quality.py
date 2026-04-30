from __future__ import annotations

import json
from typing import cast

from intric.flows.ai_builder.ai_builder_domain_models import JsonObject
from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    InputSource,
    LintSeverity,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.template_reference_analyzer import (
    TemplateReference,
    TemplateReferenceKind,
    analyze_template,
    referenced_form_fields,
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
    for step in spec.steps:
        instructions_lower = step.assistant_spec.instructions.lower()
        for indicator in _MULTI_GOAL_INDICATORS:
            if (
                indicator in instructions_lower
                and len(step.assistant_spec.instructions) > 300
            ):
                result.add_warning(
                    step_ref=step.plan_step_ref,
                    code="multi_goal_prompt",
                    message=(
                        "Step instructions may contain multiple goals. "
                        "Consider splitting into separate steps for better results."
                    ),
                )
                break


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


def lint_contract_fields_without_descriptions(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    for step in spec.steps:
        contract = step.output_contract
        if not contract:
            continue
        props = contract.get("properties")
        if not isinstance(props, dict):
            continue
        property_map = cast(dict[str, object], props)
        missing = [
            key
            for key, value in property_map.items()
            if isinstance(value, dict) and "description" not in value
        ]
        if missing:
            result.add_warning(
                step_ref=step.plan_step_ref,
                code="contract_missing_descriptions",
                message=(
                    f"Output contract fields without descriptions: {', '.join(missing[:3])}. "
                    "Add descriptions for the variable picker."
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
        properties = cast(dict[str, object], contract).get("properties")
        if not isinstance(properties, dict) or not properties:
            continue
        property_map = cast(dict[str, object], properties)

        instructions = step.assistant_spec.instructions.casefold()
        property_names = list(property_map.keys())
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
    declared_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    if not declared_fields:
        return

    used_fields: set[str] = set()
    step_refs = {step.plan_step_ref: index + 1 for index, step in enumerate(spec.steps)}
    for step in spec.steps:
        for template in _iter_step_templates(step):
            refs = analyze_template(
                template,
                step_refs=step_refs,
                form_field_names=declared_fields,
            )
            used_fields.update(referenced_form_fields(refs))

    for field_name in sorted(declared_fields - used_fields):
        result.add_warning(
            step_ref=None,
            code="unused_form_field",
            message=f"Form field '{field_name}' is declared but never referenced in any step.",
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
        question = _question_binding(step.input_bindings)
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
        question = _question_binding(step.input_bindings)
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


def lint_previous_step_binding_without_previous_source(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    step_refs = {step.plan_step_ref: index + 1 for index, step in enumerate(spec.steps)}
    form_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    for step in spec.steps:
        if step.input_source != InputSource.PREVIOUS_STEP:
            continue
        question = _question_binding(step.input_bindings)
        if question is None:
            continue
        refs = analyze_template(
            question, step_refs=step_refs, form_field_names=form_fields
        )
        if _references_previous_source(refs):
            continue
        result.add_warning(
            step_ref=step.plan_step_ref,
            code="previous_step_binding_without_previous_source",
            message=(
                "Step uses input_source 'previous_step' but its input_bindings.question "
                "does not reference the previous step. Because input_bindings.question "
                "replaces the implicit previous-step input at runtime, this can drop "
                "the transcript or structured output from the prior step."
            ),
        )


def _references_previous_source(references: list[TemplateReference]) -> bool:
    return any(
        reference.kind is TemplateReferenceKind.STEP
        or reference.head == "föregående_steg"
        for reference in references
    )


def _iter_step_templates(step: StepSpec) -> list[str]:
    templates = [step.assistant_spec.instructions]
    for payload in (step.input_bindings, step.output_config):
        if payload is None:
            continue
        if isinstance(payload, str):
            templates.append(payload)
        else:
            templates.append(json.dumps(payload, ensure_ascii=False))
    return templates


def _question_binding(input_bindings: JsonObject | None) -> str | None:
    if not isinstance(input_bindings, dict):
        return None
    question = input_bindings.get("question")
    if isinstance(question, str) and question.strip():
        return question
    return None

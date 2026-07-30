from __future__ import annotations

import json

from eneo.flows.ai_builder.ai_builder_domain_models import (
    LintSeverity,
)
from eneo.flows.ai_builder.ai_builder_form_field_usage import (
    find_unused_form_fields,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputType,
    StepSpec,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding
from eneo.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
)

_VAGUE_NAMES = {"steg", "step", "bearbeta", "process", "hantera", "handle"}


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

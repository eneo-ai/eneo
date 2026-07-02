from __future__ import annotations

import json
from difflib import get_close_matches
from typing import Any

from eneo.flows.ai_builder.ai_builder_json_schema_paths import (
    missing_structured_output_path,
    schema_property_names,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_variable_definitions import RESERVED_RUNTIME_VARIABLES
from eneo.flows.template_reference_analyzer import (
    TemplateReference,
    TemplateReferenceKind,
    analyze_template,
)
from eneo.flows.variable_resolver import iter_template_expressions


def validate_variable_references(
    spec: FlowDraftSpecCore, result: SpecValidationResult
) -> None:
    steps_by_order = {index + 1: step for index, step in enumerate(spec.steps)}
    steps_by_plan_ref = {
        step.plan_step_ref: (index + 1, step) for index, step in enumerate(spec.steps)
    }
    allowed_roots = {
        *RESERVED_RUNTIME_VARIABLES,
        *(
            field.name.strip()
            for field in (spec.form_fields or [])
            if field.name.strip()
        ),
    }
    form_field_names = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }

    for index, step in enumerate(spec.steps, start=1):
        for expression in _iter_step_template_expressions(step):
            reference = _parse_reference_expression(
                expression,
                steps_by_plan_ref,
                allowed_roots=allowed_roots,
                form_field_names=form_field_names,
            )
            if reference.kind is TemplateReferenceKind.UNKNOWN:
                suggestion = _suggest_similar(
                    reference.head,
                    {*allowed_roots, *steps_by_plan_ref.keys()},
                )
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="unknown_variable_reference",
                    message=(
                        f"Unknown variable reference '{reference.head}' in template expression. "
                        "Use a form field, a reserved runtime variable, or an earlier step reference."
                        f"{suggestion}"
                    ),
                )
                continue
            if reference.path_error_code is not None:
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="invalid_runtime_variable_path",
                    message=_runtime_path_error_message(reference),
                )
                continue
            if reference.kind is TemplateReferenceKind.FORM_FIELD:
                continue
            if reference.kind is TemplateReferenceKind.RUNTIME:
                continue
            if (
                reference.kind is TemplateReferenceKind.STEP
                and reference.step_order is None
            ):
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="invalid_step_reference",
                    message=f"Invalid step reference '{reference.head}' in template expression.",
                )
                continue

            referenced_order = reference.step_order
            if referenced_order is None:
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="invalid_step_reference",
                    message=f"Unknown step reference '{reference.head}' in template expression.",
                )
                continue

            if referenced_order >= index:
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="future_step_reference",
                    message="Variables may only reference outputs from earlier steps.",
                )
                continue

            referenced_step = steps_by_order.get(referenced_order)
            if referenced_step is None:
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="invalid_step_reference",
                    message=f"Unknown step order '{referenced_order}' in template expression.",
                )
                continue

            if not _has_supported_step_output_path(reference):
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="invalid_step_reference_path",
                    message=(
                        f"Variable '{expression}' uses an unsupported step reference path. "
                        f"Use {{{{ {reference.head}.output.text }}}} or "
                        f"{{{{ {reference.head}.output.structured.<field> }}}}."
                    ),
                )
                continue

            if not _uses_structured_output(reference):
                continue

            if referenced_step.output_type != OutputType.JSON:
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="structured_access_requires_json_output",
                    message=(
                        f"Variable '{expression}' uses output.structured.* but "
                        f"'{reference.head}' does not produce JSON output."
                    ),
                )
                continue

            if (
                referenced_step.output_contract is None
                or reference.structured_path is None
            ):
                continue

            missing_path = missing_structured_output_path(
                referenced_step.output_contract,
                ".".join(reference.structured_path),
            )
            if missing_path is not None:
                properties = schema_property_names(referenced_step.output_contract)
                suggestion = _suggest_similar(
                    missing_path.rsplit(".", maxsplit=1)[-1], properties
                )
                result.add_error(
                    step_ref=step.plan_step_ref,
                    code="unknown_output_contract_field",
                    message=(
                        f"Variable '{expression}' references '{missing_path}', "
                        f"which is not declared in {reference.head}'s output_contract."
                        f"{suggestion}"
                    ),
                )


def _iter_step_template_expressions(step: StepSpec) -> list[str]:
    expressions: list[str] = []
    expressions.extend(iter_template_expressions(step.assistant_spec.instructions))

    for payload in (step.input_bindings, step.output_config):
        if payload is None:
            continue
        expressions.extend(
            iter_template_expressions(_stringify_template_payload(payload))
        )

    return expressions


def _has_supported_step_output_path(reference: TemplateReference) -> bool:
    return (
        reference.tail == "output.text"
        or reference.tail == "output.structured"
        or reference.tail.startswith("output.structured.")
    )


def _uses_structured_output(reference: TemplateReference) -> bool:
    return reference.tail == "output.structured" or reference.tail.startswith(
        "output.structured."
    )


def _stringify_template_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)


def _parse_reference_expression(
    expression: str,
    steps_by_plan_ref: dict[str, tuple[int, StepSpec]],
    *,
    allowed_roots: set[str],
    form_field_names: set[str],
) -> TemplateReference:
    return analyze_template(
        f"{{{{ {expression} }}}}",
        step_refs={root: order for root, (order, _) in steps_by_plan_ref.items()},
        form_field_names=form_field_names,
    )[0]


def _runtime_path_error_message(reference: TemplateReference) -> str:
    if reference.path_error_code == "runtime_scalar_nested_access":
        return (
            f"Variable '{reference.expression}' uses nested access on '{reference.head}', "
            "which is a scalar runtime variable."
        )
    if reference.path_error_code == "runtime_sequence_non_numeric_index":
        return (
            f"Variable '{reference.expression}' uses a non-numeric index on '{reference.head}'. "
            "Sequence runtime variables require numeric indexes."
        )
    if reference.path_error_code == "unknown_step_input_key":
        known_keys = ()
        if reference.path_error_context is not None:
            raw_known_keys = reference.path_error_context.get("known_keys", ())
            if isinstance(raw_known_keys, (list, tuple, set, frozenset)):
                known_key_items: list[object] = [*raw_known_keys]
                known_keys = tuple(str(key) for key in known_key_items)
        suggestion = _suggest_similar(
            reference.tail.split(".", maxsplit=1)[0],
            set(known_keys),
        )
        return (
            f"Variable '{reference.expression}' references an unknown step_input key."
            f"{suggestion}"
        )
    if reference.path_error_code == "step_input_key_required":
        return (
            f"Variable '{reference.expression}' must reference a concrete step_input key such as "
            "{{ step_input.text }} or {{ step_input.file_ids.0 }}."
        )
    if reference.path_error_code == "invalid_step_reference_format":
        return f"Invalid step reference '{reference.head}' in template expression."
    return f"Invalid runtime variable path in '{reference.expression}'."


def _suggest_similar(target: str, candidates: set[str]) -> str:
    candidate_names = sorted(candidates)
    matches = get_close_matches(target, candidate_names, n=3, cutoff=0.6)
    if not matches:
        return ""
    return f" Did you mean: {', '.join(matches)}?"

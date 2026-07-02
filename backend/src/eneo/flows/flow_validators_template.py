from __future__ import annotations

import re
from typing import cast
from uuid import UUID

from eneo.flows.domain.flow_step_validation import (
    FlowStepValidationError,
    FlowStepValidationView,
)

_STEP_REFERENCE_PATTERN = re.compile(r"^step_(\d+)$")
_EXACT_TEMPLATE_EXPRESSION_PATTERN = re.compile(r"^\s*\{\{\s*([^{}]+)\s*\}\}\s*$")
TEMPLATE_FILL_RESOURCE_CONFIG_KEYS = frozenset(
    {"template_asset_id", "template_file_id"}
)


def has_template_fill_resource_reference(output_config: object) -> bool:
    if not isinstance(output_config, dict):
        return False
    return any(key in output_config for key in TEMPLATE_FILL_RESOURCE_CONFIG_KEYS)


def validate_template_fill_output_config(
    *,
    step: FlowStepValidationView,
    available_orders: set[int],
    require_complete_config: bool,
) -> None:
    if step.output_type != "docx":
        raise FlowStepValidationError(
            f"Step {step.step_order}: template_fill requires output_type 'docx'.",
            step_order=step.step_order,
        )
    output_config = step.output_config
    if output_config is None:
        if require_complete_config:
            raise FlowStepValidationError(
                f"Step {step.step_order}: output_config must be an object for output_mode 'template_fill'.",
                step_order=step.step_order,
            )
        return

    if output_config.get("template_file_id") not in (None, ""):
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_config.template_file_id is not supported; use template_asset_id.",
            step_order=step.step_order,
        )

    template_asset_id = output_config.get("template_asset_id")
    if template_asset_id in (None, ""):
        if require_complete_config:
            raise FlowStepValidationError(
                f"Step {step.step_order}: output_config.template_asset_id must be a UUID.",
                step_order=step.step_order,
            )
    else:
        try:
            UUID(str(template_asset_id))
        except Exception as exc:
            raise FlowStepValidationError(
                f"Step {step.step_order}: output_config.template_asset_id must be a UUID.",
                step_order=step.step_order,
            ) from exc

    bindings_obj = output_config.get("bindings")
    if bindings_obj is None:
        if require_complete_config:
            raise FlowStepValidationError(
                f"Step {step.step_order}: output_config.bindings must be an object.",
                step_order=step.step_order,
            )
        return
    if not isinstance(bindings_obj, dict):
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_config.bindings must be an object.",
            step_order=step.step_order,
        )
    bindings = cast(dict[object, object], bindings_obj)

    for placeholder, binding in bindings.items():
        if not isinstance(placeholder, str) or not placeholder.strip():
            raise FlowStepValidationError(
                f"Step {step.step_order}: output_config.bindings keys must be non-empty strings.",
                step_order=step.step_order,
            )
        if not isinstance(binding, str):
            raise FlowStepValidationError(
                f"Step {step.step_order}: binding '{placeholder}' must be a string template expression.",
                step_order=step.step_order,
            )
        if not binding.strip():
            continue
        match = _EXACT_TEMPLATE_EXPRESSION_PATTERN.match(binding)
        if match is None:
            raise FlowStepValidationError(
                f"Step {step.step_order}: binding '{placeholder}' must be a single template expression like {{{{step_1.output.text}}}}.",
                step_order=step.step_order,
            )
        validate_template_expression_reference(
            expression=match.group(1).strip(),
            current_step_order=step.step_order,
            available_orders=available_orders,
        )


def validate_template_expression_reference(
    *,
    expression: str,
    current_step_order: int,
    available_orders: set[int],
) -> None:
    if not expression.startswith("step_"):
        return
    head = expression.split(".", maxsplit=1)[0]
    step_ref = _STEP_REFERENCE_PATTERN.match(head)
    if step_ref is None:
        raise FlowStepValidationError(
            f"Invalid step reference '{head}' in template bindings.",
            step_order=current_step_order,
        )

    referenced_order = int(step_ref.group(1))
    if referenced_order >= current_step_order:
        raise FlowStepValidationError(
            "Template bindings may only reference outputs from earlier steps.",
            step_order=current_step_order,
        )
    if referenced_order not in available_orders:
        raise FlowStepValidationError(
            f"Template binding references unknown step order: {referenced_order}.",
            step_order=current_step_order,
        )

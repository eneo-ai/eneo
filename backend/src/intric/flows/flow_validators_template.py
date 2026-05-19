from __future__ import annotations

import re
from typing import cast
from uuid import UUID

from intric.flows.domain.flow import FlowStep
from intric.main.exceptions import BadRequestException

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
    step: FlowStep,
    available_orders: set[int],
    require_complete_config: bool,
) -> None:
    if step.output_type != "docx":
        raise BadRequestException(
            f"Step {step.step_order}: template_fill requires output_type 'docx'."
        )
    output_config = step.output_config
    if output_config is None:
        if require_complete_config:
            raise BadRequestException(
                f"Step {step.step_order}: output_config must be an object for output_mode 'template_fill'."
            )
        return

    template_asset_id = output_config.get("template_asset_id")
    template_file_id = output_config.get("template_file_id")
    if template_asset_id in (None, "") and template_file_id in (None, ""):
        if require_complete_config:
            raise BadRequestException(
                f"Step {step.step_order}: output_config.template_asset_id or template_file_id must be a UUID."
            )
    if template_asset_id not in (None, ""):
        try:
            UUID(str(template_asset_id))
        except Exception as exc:
            raise BadRequestException(
                f"Step {step.step_order}: output_config.template_asset_id must be a UUID."
            ) from exc
    if template_file_id not in (None, ""):
        try:
            UUID(str(template_file_id))
        except Exception as exc:
            raise BadRequestException(
                f"Step {step.step_order}: output_config.template_file_id must be a UUID."
            ) from exc

    bindings_obj = output_config.get("bindings")
    if bindings_obj is None:
        if require_complete_config:
            raise BadRequestException(
                f"Step {step.step_order}: output_config.bindings must be an object."
            )
        return
    if not isinstance(bindings_obj, dict):
        raise BadRequestException(
            f"Step {step.step_order}: output_config.bindings must be an object."
        )
    bindings = cast(dict[object, object], bindings_obj)

    for placeholder, binding in bindings.items():
        if not isinstance(placeholder, str) or not placeholder.strip():
            raise BadRequestException(
                f"Step {step.step_order}: output_config.bindings keys must be non-empty strings."
            )
        if not isinstance(binding, str):
            raise BadRequestException(
                f"Step {step.step_order}: binding '{placeholder}' must be a string template expression."
            )
        if not binding.strip():
            continue
        match = _EXACT_TEMPLATE_EXPRESSION_PATTERN.match(binding)
        if match is None:
            raise BadRequestException(
                f"Step {step.step_order}: binding '{placeholder}' must be a single template expression like {{{{step_1.output.text}}}}."
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
        raise BadRequestException(f"Invalid step reference '{head}' in template bindings.")

    referenced_order = int(step_ref.group(1))
    if referenced_order >= current_step_order:
        raise BadRequestException(
            "Template bindings may only reference outputs from earlier steps."
        )
    if referenced_order not in available_orders:
        raise BadRequestException(
            f"Template binding references unknown step order: {referenced_order}."
        )

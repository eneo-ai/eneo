from __future__ import annotations

from collections.abc import Sequence

from intric.flows.domain.flow import FlowPersistedJsonObject, FlowStep
from intric.flows.domain.flow_step_validation import (
    FlowStepValidationError,
    FlowStepValidationView,
    flow_step_validation_views_from_flow_steps,
)
from intric.flows.flow_metadata import (
    FlowFormSchemaParseMode,
    form_field_name_error,
    parse_flow_form_schema,
    validate_form_field_runtime_name,
)
from intric.flows.flow_variable_definitions import (
    RESERVED_RUNTIME_VARIABLES,
    is_reserved_runtime_variable,
    is_step_alias_variable,
)


def validate_form_schema(metadata_json: FlowPersistedJsonObject | None) -> None:
    parse_flow_form_schema(metadata_json, mode=FlowFormSchemaParseMode.WRITE)


def validate_variable_alias_collisions(
    *,
    steps: Sequence[FlowStep],
    metadata_json: FlowPersistedJsonObject | None,
) -> None:
    validate_variable_alias_collisions_for_step_graph(
        steps=flow_step_validation_views_from_flow_steps(steps),
        metadata_json=metadata_json,
    )


def validate_variable_alias_collisions_for_step_graph(
    *,
    steps: Sequence[FlowStepValidationView],
    metadata_json: FlowPersistedJsonObject | None,
) -> None:
    field_names: dict[str, str] = {}

    parsed_schema = parse_flow_form_schema(
        metadata_json, mode=FlowFormSchemaParseMode.PERSISTED_READ
    )
    if parsed_schema is not None:
        for index, field in enumerate(parsed_schema.fields):
            normalized = field.name.casefold()
            validate_form_field_runtime_name(index, field.name)
            if is_step_alias_variable(normalized):
                raise form_field_name_error(
                    message=(
                        f"Form field {index + 1} is named '{field.name}'. Names like "
                        "step_1 are reserved for flow steps. Use a descriptive field name "
                        "such as 'ärendenummer' instead."
                    ),
                    code="flow_form_field_name_step_alias",
                    index=index,
                    field_name=field.name,
                )
            field_names[normalized] = field.name

    for step in steps:
        raw_name = step.user_description
        if raw_name is None:
            continue
        normalized = raw_name.strip().casefold()
        if not normalized:
            continue
        if is_reserved_runtime_variable(normalized):
            raise FlowStepValidationError(
                f"Step {step.step_order} is named '{raw_name}', but that name is reserved "
                "for Eneo runtime variables. Rename the step to describe what it does.",
                code="flow_step_name_reserved_variable",
                context={
                    "step_order": step.step_order,
                    "step_name": raw_name,
                    "reserved_aliases": sorted(RESERVED_RUNTIME_VARIABLES),
                },
                step_order=step.step_order,
            )
        if is_step_alias_variable(normalized):
            raise FlowStepValidationError(
                f"Step {step.step_order} is named '{raw_name}'. Names like step_1 are "
                "reserved for automatic step variables. Rename the step to describe what it does.",
                code="flow_step_name_step_alias",
                context={"step_order": step.step_order, "step_name": raw_name},
                step_order=step.step_order,
            )
        if normalized in field_names:
            raise FlowStepValidationError(
                f"Step {step.step_order} name '{raw_name}' conflicts with form field name '{field_names[normalized]}'.",
                step_order=step.step_order,
            )

from __future__ import annotations

from intric.flows.domain.flow import FlowPersistedJsonObject, FlowStep
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
from intric.main.exceptions import BadRequestException


def validate_form_schema(metadata_json: FlowPersistedJsonObject | None) -> None:
    parse_flow_form_schema(metadata_json, mode=FlowFormSchemaParseMode.WRITE)


def validate_variable_alias_collisions(
    *,
    steps: list[FlowStep],
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
            raise BadRequestException(
                f"Step {step.step_order} is named '{raw_name}', but that name is reserved "
                "for Eneo runtime variables. Rename the step to describe what it does.",
                code="flow_step_name_reserved_variable",
                context={
                    "step_order": step.step_order,
                    "step_name": raw_name,
                    "reserved_aliases": sorted(RESERVED_RUNTIME_VARIABLES),
                },
            )
        if is_step_alias_variable(normalized):
            raise BadRequestException(
                f"Step {step.step_order} is named '{raw_name}'. Names like step_1 are "
                "reserved for automatic step variables. Rename the step to describe what it does.",
                code="flow_step_name_step_alias",
                context={"step_order": step.step_order, "step_name": raw_name},
            )
        if normalized in field_names:
            raise BadRequestException(
                f"Step {step.step_order} name '{raw_name}' conflicts with form field name '{field_names[normalized]}'."
            )

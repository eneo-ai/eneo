"""Active proposal tool schema."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

import jsonschema
from jsonschema.validators import validator_for

from eneo.flows.ai_builder.ai_builder_edit_tool_schema import (
    build_edit_flow_tool_schema,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    build_create_flow_tool_schema,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_requirements import (
    ConfirmedRuntimeInputRequirement,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_tool_parsing import (
    extract_assumptions,
    extract_plan_rationale,
)

if TYPE_CHECKING:
    from eneo.flows.domain.flow import FlowStep


class ProposalToolFunction(TypedDict):
    name: str
    parameters: dict[str, Any]


class ProposalToolSchema(TypedDict):
    type: Literal["function"]
    function: ProposalToolFunction


def build_propose_flow_tool_schema(
    *,
    resource_catalog: AIBuilderResourceCatalog,
    current_steps: list["FlowStep"] | None = None,
    is_pure_audio_transcription: bool = False,
    confirmed_runtime_inputs: tuple[ConfirmedRuntimeInputRequirement, ...] = (),
) -> ProposalToolSchema:
    if current_steps is None:
        return cast(
            ProposalToolSchema,
            build_create_flow_tool_schema(
                resource_catalog=resource_catalog,
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                is_pure_audio_transcription=is_pure_audio_transcription,
                confirmed_runtime_inputs=confirmed_runtime_inputs,
            ),
        )
    return cast(
        ProposalToolSchema,
        build_edit_flow_tool_schema(
            current_steps,
            resource_catalog=resource_catalog,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        ),
    )


class ProposalToolArgumentsError(ValueError):
    """The provider returned arguments outside the prepared proposal schema."""


def validate_propose_flow_tool_arguments(
    *,
    arguments: dict[str, Any],
    tool_schema: ProposalToolSchema,
) -> None:
    parameters = tool_schema["function"]["parameters"]
    validator_class = validator_for(parameters)
    validator_class.check_schema(parameters)
    error = next(validator_class(parameters).iter_errors(arguments), None)
    if error is None:
        return

    actionable_error = _actionable_validation_error(error)
    path = ".".join(str(part) for part in actionable_error.absolute_path) or "root"
    raise ProposalToolArgumentsError(
        f"{path}: {actionable_error.message} ({actionable_error.validator})"
    ) from error


def _actionable_validation_error(
    error: jsonschema.ValidationError,
) -> jsonschema.ValidationError:
    if error.validator != "oneOf" or not error.context:
        return error

    branch_index = _matching_discriminator_branch_index(error)
    branch_errors = [
        candidate
        for candidate in error.context
        if branch_index is not None
        and candidate.relative_schema_path
        and candidate.relative_schema_path[0] == branch_index
    ]
    candidates: list[jsonschema.ValidationError] = branch_errors or list(error.context)
    selected = next(
        (candidate for candidate in candidates if candidate.validator == "required"),
        None,
    ) or max(
        candidates,
        key=lambda candidate: len(tuple(candidate.absolute_path)),
        default=None,
    )
    return _actionable_validation_error(selected) if selected is not None else error


def _matching_discriminator_branch_index(
    error: jsonschema.ValidationError,
) -> int | None:
    instance_object: object = error.instance
    schema_object: object = error.schema
    if not isinstance(instance_object, dict) or not isinstance(schema_object, dict):
        return None
    instance = cast(dict[str, object], instance_object)
    schema = cast(dict[str, object], schema_object)
    raw_branches = schema.get("oneOf")
    if not isinstance(raw_branches, list):
        return None
    branches = cast(list[object], raw_branches)

    for discriminator in ("kind", "type"):
        value = instance.get(discriminator)
        if not isinstance(value, str):
            continue
        matches: list[int] = []
        for index, branch in enumerate(branches):
            if not isinstance(branch, dict):
                continue
            branch_map = cast(dict[str, object], branch)
            raw_properties = branch_map.get("properties")
            if not isinstance(raw_properties, dict):
                continue
            properties = cast(dict[str, object], raw_properties)
            raw_discriminator_schema = properties.get(discriminator)
            if not isinstance(raw_discriminator_schema, dict):
                continue
            discriminator_schema = cast(dict[str, object], raw_discriminator_schema)
            raw_values = discriminator_schema.get("enum")
            if isinstance(raw_values, list) and value in raw_values:
                matches.append(index)
        if len(matches) == 1:
            return matches[0]
    return None


__all__ = [
    "build_propose_flow_tool_schema",
    "ProposalToolArgumentsError",
    "ProposalToolSchema",
    "extract_assumptions",
    "extract_plan_rationale",
    "parse_create_flow_intent_arguments",
    "validate_propose_flow_tool_arguments",
]

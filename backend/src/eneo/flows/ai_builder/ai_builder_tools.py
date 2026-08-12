"""Active proposal tool schema."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, TypedDict, cast

import jsonschema

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
) -> ProposalToolSchema:
    if current_steps is None:
        return cast(
            ProposalToolSchema,
            build_create_flow_tool_schema(
                resource_catalog=resource_catalog,
                tool_name=PROPOSE_FLOW_TOOL_NAME,
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
    try:
        jsonschema.validate(instance=arguments, schema=parameters)
    except jsonschema.ValidationError as error:
        path = ".".join(str(part) for part in error.absolute_path) or "root"
        raise ProposalToolArgumentsError(
            f"{path}: violates the active proposal schema ({error.validator})"
        ) from error
    else:
        return


__all__ = [
    "build_propose_flow_tool_schema",
    "ProposalToolArgumentsError",
    "ProposalToolSchema",
    "extract_assumptions",
    "extract_plan_rationale",
    "parse_create_flow_intent_arguments",
    "validate_propose_flow_tool_arguments",
]

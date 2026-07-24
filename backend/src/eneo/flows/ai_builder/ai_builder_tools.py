"""Active proposal tool schema."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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


def build_propose_flow_tool_schema(
    *,
    resource_catalog: AIBuilderResourceCatalog,
    current_steps: list["FlowStep"] | None = None,
) -> dict[str, Any]:
    if current_steps is None:
        return build_create_flow_tool_schema(
            resource_catalog=resource_catalog,
            tool_name=PROPOSE_FLOW_TOOL_NAME,
        )
    return build_edit_flow_tool_schema(
        current_steps,
        resource_catalog=resource_catalog,
        tool_name=PROPOSE_FLOW_TOOL_NAME,
    )


__all__ = [
    "build_propose_flow_tool_schema",
    "extract_assumptions",
    "extract_plan_rationale",
    "parse_create_flow_intent_arguments",
]

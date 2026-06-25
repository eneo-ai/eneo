"""Active proposal tool schema and persisted AI Builder tool names."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from intric.flows.ai_builder.ai_builder_edit_tool_schema import (
    build_edit_flow_tool_schema,
)
from intric.flows.ai_builder.ai_builder_proposal_intent import (
    build_create_flow_tool_schema,
    parse_create_flow_intent_arguments,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
)
from intric.flows.ai_builder.ai_builder_tool_parsing import (
    extract_assumptions,
    extract_plan_rationale,
    extract_reasoning,
)

if TYPE_CHECKING:
    from intric.flows.domain.flow import FlowStep

ASK_STRUCTURED_QUESTION_TOOL_NAME = "ask_structured_question"
PROPOSE_FLOW_TOOL_NAME = "propose_flow"
CONFIRM_REQUIREMENTS_TOOL_NAME = "confirm_requirements"


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
    "ASK_STRUCTURED_QUESTION_TOOL_NAME",
    "CONFIRM_REQUIREMENTS_TOOL_NAME",
    "PROPOSE_FLOW_TOOL_NAME",
    "build_propose_flow_tool_schema",
    "extract_assumptions",
    "extract_plan_rationale",
    "extract_reasoning",
    "parse_create_flow_intent_arguments",
]

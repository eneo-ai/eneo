from __future__ import annotations

from intric.flows.ai_builder import ai_builder_tools as tools
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME


def test_tools_module_exposes_single_propose_flow_contract() -> None:
    assert tools.PROPOSE_FLOW_TOOL_NAME == "propose_flow"
    assert hasattr(tools, "build_propose_flow_tool_schema")
    assert not hasattr(tools, "VALIDATE_FLOW_DRAFT_TOOL_NAME")
    assert not hasattr(tools, "build_validate_flow_draft_tool_schema")
    assert not hasattr(tools, "parse_propose_flow_arguments")
    assert not hasattr(tools, "OUTLINE_FLOW_TOOL_NAME")
    assert not hasattr(tools, "EDIT_FLOW_TOOL_NAME")
    assert not hasattr(tools, "active_submission_tool_name")


def test_active_create_tool_schemas_only_expose_current_contracts() -> None:
    names = [schema["function"]["name"] for schema in tools.build_all_tool_schemas()]

    assert names == [
        PROPOSE_FLOW_TOOL_NAME,
        tools.ASK_STRUCTURED_QUESTION_TOOL_NAME,
        tools.CONFIRM_REQUIREMENTS_TOOL_NAME,
    ]

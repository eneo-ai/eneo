"""The flow chat's instructions carry the suggestion catalogue's authoring
rules, so a code cannot be added without its guidance reaching the chat."""

from __future__ import annotations

from eneo.flows.application.flow_authoring_chat import (
    AUTHORING_INSTRUCTIONS,
    tool_runtime_capabilities,
)
from eneo.flows.domain.flow_suggestions import (
    FLOW_SUGGESTION_AUTHORING_RULES,
    FlowSuggestionCode,
)
from eneo.mcp_servers.domain.capabilities import CapabilityAvailability


def _unwrapped(text: str) -> str:
    return " ".join(text.split())


def test_the_instructions_hold_every_authoring_rule() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    for code in FlowSuggestionCode:
        assert _unwrapped(FLOW_SUGGESTION_AUTHORING_RULES[code]) in instructions


def test_the_instructions_resolve_introduced_suggestions_in_the_same_turn() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "Design every step by these rules from the start" in instructions
    assert "introduced_suggestions" in instructions
    assert "Resolve each in the same turn" in instructions
    assert "unless the user explicitly asked for that shape" in instructions
    assert chr(0x2014) not in AUTHORING_INSTRUCTIONS


def test_the_instructions_turn_a_pasted_task_into_a_flow_instead_of_doing_it() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "you do not do the work a flow is for" in instructions
    assert "Never carry such a task out in the chat" in instructions
    assert "In edit mode, build it" in instructions
    assert "When edit mode is off, describe the steps" in instructions


def test_the_chat_gets_the_tool_runtime_functions_its_space_offers_and_a_provider_serves():
    states = [
        CapabilityAvailability(purpose="file_analysis", available=True),
        CapabilityAvailability(purpose="file_creation", available=True),
        CapabilityAvailability(purpose="charts", available=False, reason="no_provider"),
        CapabilityAvailability(purpose="compute", available=True),
        CapabilityAvailability(purpose="web_search", available=True),
    ]
    # Charts has no ready provider, compute is not offered by the space, and
    # web search is not a tool runtime function: none of them is given.
    assert tool_runtime_capabilities(
        ["file_creation", "charts", "file_analysis", "web_search"], states
    ) == ["file_analysis", "file_creation"]
    assert tool_runtime_capabilities([], states) == []

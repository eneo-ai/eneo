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


def test_the_instructions_ask_one_shaping_question_at_a_time() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "Ask only where the answer changes the shape of the flow" in instructions
    assert "Ask one question at a time" in instructions
    assert (
        "Never ask what the flow, an uploaded file or an earlier answer already says"
        in instructions
    )
    assert "take a reasonable first option" in instructions
    assert (
        "Permission to send data anywhere or to start a run is never assumed"
        in instructions
    )
    assert "ask before it, every time" in instructions
    assert "instructions to follow, an example of what a run gets as input" in (
        instructions
    )


def test_the_instructions_take_a_contract_from_an_example() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "derive the step's contract from it with contract_from_example" in (
        instructions
    )
    assert "the example itself is not saved" in instructions
    assert "ask for one when the wanted result is structured" in instructions


def test_the_instructions_show_the_expected_result_without_doing_the_work() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "say in a few lines what its result will look like" in instructions
    assert "mark what is not saved yet as a proposal" in instructions
    assert "Use placeholders for content" in instructions
    assert "Describing the shape of the result this way is part of building" in (
        instructions
    )
    assert "filling it with content is doing the work the flow is for" in instructions
    assert "Explaining a run the person asks about" in instructions


def test_the_instructions_carry_a_change_to_the_steps_that_read_it() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "read its readers in read_flow" in instructions
    assert "in the same update_steps call" in instructions
    assert "Leave the steps that do not read it untouched" in instructions
    assert "read a step in full (section steps) before changing it" in instructions


def test_the_instructions_tell_a_runs_kinds_of_failure_apart() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "read it with read_run first" in instructions
    assert "A transient error never changes a prompt" in instructions
    assert "correct this run's result through its review" in instructions
    assert "call a token impact an estimate" in instructions
    assert "offer it only for a transient error" in instructions
    assert "call it only after a yes" in instructions
    assert "the way is a new run once it is published, not a retry" in instructions


def test_the_instructions_keep_every_secret_out_of_the_chat() -> None:
    instructions = _unwrapped(AUTHORING_INSTRUCTIONS)

    assert "Build everything but the secret" in instructions
    assert "Never ask for a key, token or password in the chat" in instructions
    assert "never put one in a tool argument" in instructions
    assert 'so its pill offers "Anslut tjänst"' in instructions
    assert "an administrator must add the server or grant it to the space" in (
        instructions
    )
    assert "Testing a connection is the person's action in the editor" in instructions


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

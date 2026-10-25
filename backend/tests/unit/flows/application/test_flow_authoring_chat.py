"""The flow chat's instructions carry the suggestion catalogue's authoring
rules, so a code cannot be added without its guidance reaching the chat."""

from __future__ import annotations

from eneo.flows.application.flow_authoring_chat import AUTHORING_INSTRUCTIONS
from eneo.flows.domain.flow_suggestions import (
    FLOW_SUGGESTION_AUTHORING_RULES,
    FlowSuggestionCode,
)


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

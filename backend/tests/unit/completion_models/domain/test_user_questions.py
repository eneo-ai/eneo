"""The question tool: what the model may ask and how it is checked."""

from __future__ import annotations

import json

import pytest

from eneo.ai_models.completion_models.completion_model import (
    function_definition_to_tool,
)
from eneo.completion_models.domain.user_questions import (
    ASK_USER_TOOL_NAME,
    MAX_OPTIONS,
    InvalidQuestionError,
    ask_user_function_definition,
    asked_question_result,
    parse_asked_question,
    pending_question_result,
    refused_question_result,
)


def _option(label: str, description: str | None = None) -> dict[str, object]:
    return {"label": label, "description": description}


def test_the_tool_is_a_strict_function_the_model_can_call() -> None:
    tool = function_definition_to_tool(ask_user_function_definition())
    function = tool["function"]
    assert isinstance(function, dict)
    assert function["name"] == ASK_USER_TOOL_NAME
    schema = function["parameters"]
    assert isinstance(schema, dict)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"question", "header", "options", "multi_select"}
    assert "ends your turn" in str(function["description"])


def test_a_question_keeps_its_options_in_order_and_trims_the_text() -> None:
    asked = parse_asked_question(
        {
            "question": "  Vem ska läsa  PM:et? ",
            "header": "Mottagare",
            "options": [
                _option("Nämnden", "Beslutsunderlag."),
                _option("Ledningen", ""),
                _option("Allmänheten"),
            ],
            "multi_select": False,
        }
    )
    assert asked.question == "Vem ska läsa PM:et?"
    assert asked.header == "Mottagare"
    assert [(o.label, o.description) for o in asked.options] == [
        ("Nämnden", "Beslutsunderlag."),
        ("Ledningen", None),
        ("Allmänheten", None),
    ]
    assert asked.multi_select is False
    assert asked.structured_content() == {
        "question": "Vem ska läsa PM:et?",
        "header": "Mottagare",
        "options": [
            {"label": "Nämnden", "description": "Beslutsunderlag."},
            {"label": "Ledningen", "description": None},
            {"label": "Allmänheten", "description": None},
        ],
        "multi_select": False,
    }


def test_a_missing_header_is_none_and_multi_select_defaults_off() -> None:
    asked = parse_asked_question(
        {"question": "Vilka delar?", "options": [_option("A"), _option("B")]}
    )
    assert asked.header is None
    assert asked.multi_select is False


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"options": [_option("A"), _option("B")]}, "question is missing"),
        ({"question": "Q?", "options": [_option("A")]}, "between 2 and 4 options"),
        (
            {
                "question": "Q?",
                "options": [_option(str(n)) for n in range(MAX_OPTIONS + 1)],
            },
            "between 2 and 4 options",
        ),
        ({"question": "Q?", "options": "A, B"}, "options must be a list"),
        ({"question": "Q?", "options": [_option("A"), "B"]}, "must be an object"),
        (
            {"question": "Q?", "options": [_option("A"), _option(" a ")]},
            "given twice",
        ),
        (
            {"question": "Q?", "options": [_option("A"), _option("")]},
            "option label is missing",
        ),
        (
            {"question": "x" * 401, "options": [_option("A"), _option("B")]},
            "longer than 400",
        ),
        (
            {
                "question": "Q?",
                "options": [_option("A"), _option("B")],
                "multi_select": "yes",
            },
            "multi_select must be",
        ),
    ],
)
def test_a_question_the_chat_cannot_show_is_refused_with_the_reason(
    arguments: dict[str, object], reason: str
) -> None:
    with pytest.raises(InvalidQuestionError, match=reason):
        parse_asked_question(arguments)


def test_the_tool_results_tell_the_model_what_happened() -> None:
    asked = json.loads(asked_question_result())
    assert asked["asked"] is True
    assert "next message" in asked["note"]
    refused = json.loads(refused_question_result("options must be a list"))
    assert refused == {"asked": False, "error": "options must be a list"}
    pending = json.loads(pending_question_result())
    assert pending == {
        "deferred": True,
        "reason": "question_pending",
        "retryable": True,
    }

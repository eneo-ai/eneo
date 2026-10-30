"""The question an assistant may put to the person in the middle of a chat.

A built-in function tool, ``eneo_ask_user``, offered on a chat whose client
can show a question (``ConversationRequest.allow_questions``). The model
names one short question and two to four options; the adapter records the
call as a step on the built-in ``questions`` server, with the question as
its structured content, and ends the turn. The client draws the question
above its composer, and the person's pick or free text arrives as the next
user message, right after the call in the transcript. Nothing waits
server-side, so a person may answer hours later or not at all.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from eneo.ai_models.completion_models.completion_model import FunctionDefinition

ASK_USER_TOOL_NAME = "eneo_ask_user"
"""The name the model calls; what replay sends on later turns."""

QUESTIONS_SERVER_NAME = "questions"
"""The built-in server the call is shown on, like ``skills`` for activations."""

QUESTION_TOOL_NAME = "ask_user"
"""The call's display name on that server."""

MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_QUESTION_CHARS = 400
MAX_HEADER_CHARS = 24
MAX_LABEL_CHARS = 80
MAX_DESCRIPTION_CHARS = 160

_DESCRIPTION = (
    "Ask the person one question when the answer changes what you will do "
    "and the conversation does not already give it. Offer 2 to 4 short "
    "options; the person can also answer in their own words. Asking ends "
    "your turn: write what you know so far in your message, call this tool "
    "once, and stop. The answer arrives as the next user message. Never ask "
    "what the person, a file or an earlier answer already says, never ask "
    "several questions at once, and never ask for passwords or keys."
)


class InvalidQuestionError(ValueError):
    """The model's arguments do not make a question the client can show."""


@dataclass(frozen=True)
class QuestionOption:
    label: str
    description: str | None = None


@dataclass(frozen=True)
class AskedQuestion:
    question: str
    header: str | None
    options: tuple[QuestionOption, ...]
    multi_select: bool

    def structured_content(self) -> dict[str, Any]:
        """What the chat draws the question from, on the call's metadata."""
        return {
            "question": self.question,
            "header": self.header,
            "options": [
                {"label": option.label, "description": option.description}
                for option in self.options
            ],
            "multi_select": self.multi_select,
        }


def ask_user_function_definition() -> FunctionDefinition:
    """The tool as the provider sees it (a strict function schema)."""
    return FunctionDefinition(
        name=ASK_USER_TOOL_NAME,
        description=_DESCRIPTION,
        schema={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question, one sentence, in the person's language.",
                },
                "header": {
                    "type": ["string", "null"],
                    "description": (
                        "One or two words naming what the question is about "
                        "(for example 'Recipient', 'Scope'), shown as a label."
                    ),
                },
                "options": {
                    "type": "array",
                    "description": "2 to 4 options, the most likely first.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "A few words naming the option.",
                            },
                            "description": {
                                "type": ["string", "null"],
                                "description": (
                                    "One short line on what choosing it means."
                                ),
                            },
                        },
                        "required": ["label", "description"],
                        "additionalProperties": False,
                    },
                },
                "multi_select": {
                    "type": "boolean",
                    "description": "Whether several options may be picked at once.",
                },
            },
            "required": ["question", "header", "options", "multi_select"],
            "additionalProperties": False,
        },
    )


def _text(value: object, *, what: str, limit: int, required: bool) -> str | None:
    if value is None or value == "":
        if required:
            raise InvalidQuestionError(f"{what} is missing")
        return None
    if not isinstance(value, str):
        raise InvalidQuestionError(f"{what} must be text")
    text = " ".join(value.split())
    if not text:
        if required:
            raise InvalidQuestionError(f"{what} is missing")
        return None
    if len(text) > limit:
        raise InvalidQuestionError(f"{what} is longer than {limit} characters")
    return text


def parse_asked_question(arguments: Mapping[str, object]) -> AskedQuestion:
    """The question the model asked, checked the way the client needs it:
    one question, 2 to 4 distinct labelled options, short text throughout.
    Raises InvalidQuestionError, whose message goes back to the model."""
    question = _text(
        arguments.get("question"),
        what="question",
        limit=MAX_QUESTION_CHARS,
        required=True,
    )
    assert question is not None
    header = _text(
        arguments.get("header"), what="header", limit=MAX_HEADER_CHARS, required=False
    )
    raw_options = arguments.get("options")
    if not isinstance(raw_options, Sequence) or isinstance(raw_options, str):
        raise InvalidQuestionError("options must be a list")
    options: list[QuestionOption] = []
    seen: set[str] = set()
    for raw in raw_options:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(raw, Mapping):
            raise InvalidQuestionError("each option must be an object")
        option = cast(Mapping[str, object], raw)
        label = _text(
            option.get("label"),
            what="option label",
            limit=MAX_LABEL_CHARS,
            required=True,
        )
        assert label is not None
        if label.casefold() in seen:
            raise InvalidQuestionError(f"option '{label}' is given twice")
        seen.add(label.casefold())
        description = _text(
            option.get("description"),
            what="option description",
            limit=MAX_DESCRIPTION_CHARS,
            required=False,
        )
        options.append(QuestionOption(label=label, description=description))
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise InvalidQuestionError(
            f"give between {MIN_OPTIONS} and {MAX_OPTIONS} options, not {len(options)}"
        )
    multi_select = arguments.get("multi_select", False)
    if not isinstance(multi_select, bool):
        raise InvalidQuestionError("multi_select must be true or false")
    return AskedQuestion(
        question=question,
        header=header,
        options=tuple(options),
        multi_select=multi_select,
    )


def asked_question_result() -> str:
    """The tool result the model reads, now and on replay: the answer is the
    next user message, so the turn ends here."""
    return json.dumps(
        {
            "asked": True,
            "note": (
                "The question is shown to the person. Their next message is "
                "the answer; end your turn now."
            ),
        }
    )


def refused_question_result(reason: str) -> str:
    """The tool result for a question the client could not show."""
    return json.dumps({"asked": False, "error": reason})


def pending_question_result() -> str:
    """The tool result for a call made in the same round as a question: it
    did not run, since the turn ends with the question."""
    return json.dumps(
        {"deferred": True, "reason": "question_pending", "retryable": True}
    )

"""The ids of the questions the Builder asks about MCP tools: the one place
they are built and read, with the typed facts a showing carries for the web.

``tool_relevance`` is asked once per create session; ``tool_choice:<use_ref>``
and ``tool_argument:<use_ref>:<tool_ref>:<argument>`` once per use of a tool
and per argument, so two uses never share a question, and an argument's answer
names the tool it was given for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.ai_builder.ai_builder_tool_catalog import TOOL_REF_PATTERN

TOOL_RELEVANCE_QUESTION_ID = "tool_relevance"
_CHOICE_PREFIX = "tool_choice:"
_ARGUMENT_PREFIX = "tool_argument:"
# An answer stores its question's id in at most this many characters.
QUESTION_ID_MAX_LENGTH = 128
# The planner's key for a use of a tool (``ToolUseIntent.use_ref``).
TOOL_USE_REF_PATTERN = r"^[a-z][a-z0-9_]{0,31}$"
_USE_REF = re.compile(TOOL_USE_REF_PATTERN)
_TOOL_REF = re.compile(TOOL_REF_PATTERN)


@dataclass(frozen=True, slots=True)
class ToolRelevanceQuestion:
    pass


@dataclass(frozen=True, slots=True)
class ToolChoiceQuestion:
    use_ref: str


@dataclass(frozen=True, slots=True)
class ToolArgumentQuestion:
    use_ref: str
    tool_ref: str
    argument: str


ToolQuestion: TypeAlias = (
    ToolRelevanceQuestion | ToolChoiceQuestion | ToolArgumentQuestion
)


def tool_question_id(question: ToolQuestion) -> str:
    if isinstance(question, ToolRelevanceQuestion):
        return TOOL_RELEVANCE_QUESTION_ID
    if isinstance(question, ToolChoiceQuestion):
        return f"{_CHOICE_PREFIX}{question.use_ref}"
    return (
        f"{_ARGUMENT_PREFIX}{question.use_ref}:{question.tool_ref}:{question.argument}"
    )


def parse_tool_question_id(question_id: str) -> ToolQuestion | None:
    """The tool question ``question_id`` names, None for any other id."""
    if len(question_id) > QUESTION_ID_MAX_LENGTH:
        return None
    if question_id == TOOL_RELEVANCE_QUESTION_ID:
        return ToolRelevanceQuestion()
    if question_id.startswith(_CHOICE_PREFIX):
        use_ref = question_id.removeprefix(_CHOICE_PREFIX)
        return ToolChoiceQuestion(use_ref) if _USE_REF.fullmatch(use_ref) else None
    if question_id.startswith(_ARGUMENT_PREFIX):
        use_ref, _, rest = question_id.removeprefix(_ARGUMENT_PREFIX).partition(":")
        tool_ref, _, argument = rest.partition(":")
        if argument and _USE_REF.fullmatch(use_ref) and _TOOL_REF.fullmatch(tool_ref):
            return ToolArgumentQuestion(use_ref, tool_ref, argument)
    return None


class AIBuilderToolQuestion(BaseModel):
    """Which MCP tool question a showing is, so a client reads it from typed
    fields rather than from the question's id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    family: Literal["relevance", "choice", "argument"] = Field(
        description=(
            "relevance: whether the flow reads data with the space's tools. "
            "choice: which tool one use reads. argument: where one argument's "
            "value comes from."
        )
    )
    use_ref: str | None = Field(
        default=None,
        description="The use of a tool the question is about; null for relevance.",
    )
    argument_name: str | None = Field(
        default=None,
        description="The argument the question is about; set only for argument.",
    )
    fixed_value_option_id: str | None = Field(
        default=None,
        description=(
            "The option a typed value answers: the answer names it with the "
            "value in custom_value. Set only on an argument question that "
            "takes a typed value."
        ),
    )


def tool_question_facts(
    question: ToolQuestion, *, fixed_value_option_id: str | None = None
) -> AIBuilderToolQuestion:
    """The typed facts of ``question`` for its showing."""
    if isinstance(question, ToolRelevanceQuestion):
        return AIBuilderToolQuestion(family="relevance")
    if isinstance(question, ToolChoiceQuestion):
        return AIBuilderToolQuestion(family="choice", use_ref=question.use_ref)
    return AIBuilderToolQuestion(
        family="argument",
        use_ref=question.use_ref,
        argument_name=question.argument,
        fixed_value_option_id=fixed_value_option_id,
    )

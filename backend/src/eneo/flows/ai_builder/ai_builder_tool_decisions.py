"""What the person decided about the space's MCP tools in a Builder session.

Rebuilt every turn from their answers to the tool questions
(``ai_builder_tool_questions.fold_tool_decisions``) and never stored. Each use
of a tool is keyed by the planner's ``use_ref``.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.ai_builder.ai_builder_tool_use import (
    EarlierStepToolArgument,
    FixedToolArgument,
    RunInputToolArgument,
)

ToolRelevance: TypeAlias = Literal["use", "dont_use"]
# How many uses and arguments one session's decisions hold (the most
# recently answered ones): a plan uses tools at most this many times, and a
# use asks for at most this many arguments.
TOOL_DECISION_MAX_USES = 20
TOOL_DECISION_MAX_ARGUMENTS = 40


class FixedTextDecision(BaseModel):
    """A fixed value the person typed: read against the argument's schema
    when the tool is known (``ai_builder_tool_questions``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["fixed_text"] = "fixed_text"
    name: str
    text: str = Field(min_length=1, max_length=500)


ToolArgumentDecision: TypeAlias = Annotated[
    FixedToolArgument
    | RunInputToolArgument
    | EarlierStepToolArgument
    | FixedTextDecision,
    Field(discriminator="kind"),
]


class ToolUseDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # The tool the person chose for the use; None while they chose none.
    tool_ref: str | None = None
    # The person chose to build the use without a tool.
    no_tool: bool = False
    # The tool the arguments were answered for: they never fill another tool's.
    arguments_for: str | None = None
    arguments: dict[str, ToolArgumentDecision] = Field(
        default_factory=dict[str, ToolArgumentDecision],
        max_length=TOOL_DECISION_MAX_ARGUMENTS,
    )


class ToolDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relevance: ToolRelevance | None = None
    # The last answer to the relevance question asked to see the tools first.
    tools_requested: bool = False
    uses: dict[str, ToolUseDecision] = Field(
        default_factory=dict[str, ToolUseDecision],
        max_length=TOOL_DECISION_MAX_USES,
    )

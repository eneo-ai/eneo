"""The person's answers to the Builder's tool questions, read from the
conversation each against the showing it answered.

Kept apart from the questions themselves (``ai_builder_tool_questions``) so the
planning-state fold can read the relevance answer: whether the run-input
question may be answered with no_run_input (``offers_no_run_input``).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    StructuredQuestionAnswerMetadata,
    question_answer_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_event_models import (
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_question_state import shown_question
from eneo.flows.ai_builder.ai_builder_tool_decisions import ToolRelevance
from eneo.flows.ai_builder.ai_builder_tool_question_ids import (
    ToolChoiceQuestion,
    ToolQuestion,
    ToolRelevanceQuestion,
    parse_tool_question_id,
)

RELEVANCE_USE = "use"
RELEVANCE_DONT_USE = "dont_use"
RELEVANCE_SHOW_TOOLS = "show_tools"
NO_TOOL = "no_tool"
ARGUMENT_FIXED = "fixed"


@dataclass(frozen=True, slots=True)
class ToolAnswer:
    question: ToolQuestion
    option: StructuredQuestionOptionPayload
    answer: StructuredQuestionAnswerMetadata


@dataclass(frozen=True, slots=True)
class ToolRelevanceAnswer:
    relevance: ToolRelevance | None = None
    # The last answer asked to see the tools first.
    tools_requested: bool = False


def tool_answer_is_valid(
    answer: StructuredQuestionAnswerMetadata, *, shown: StructuredQuestionPayload | None
) -> bool:
    """Whether an answer to a tool question picks exactly one option of the
    question as it was shown, with a typed value only for a fixed value."""
    if shown is None:
        return False
    selected = selected_tool_option(answer)
    if selected is None or selected not in {option.id for option in shown.options}:
        return False
    custom = (answer.custom_value or "").strip()
    if selected == ARGUMENT_FIXED and shown.allow_custom:
        return bool(custom)
    return answer.custom_value is None


def selected_tool_option(answer: StructuredQuestionAnswerMetadata) -> str | None:
    ids = answer.selected_option_ids or []
    if answer.selected_option_id is not None:
        ids = [*ids, answer.selected_option_id]
    unique = set(ids)
    return next(iter(unique)) if len(unique) == 1 else None


def tool_answers(conversation: Sequence[ConversationMessage]) -> Iterator[ToolAnswer]:
    """Every valid answer to a tool question, in order, each read against the
    latest showing of its question before it."""
    shown: dict[str, StructuredQuestionPayload] = {}
    for message in conversation:
        if message.role == "assistant":
            payload = shown_question(message)
            if payload is not None and parse_tool_question_id(payload.question_id):
                shown[payload.question_id] = payload
            continue
        if message.role != "user":
            continue
        answer = question_answer_from_metadata(message.metadata)
        if answer is None or answer.question_id is None:
            continue
        question = parse_tool_question_id(answer.question_id)
        payload = shown.get(answer.question_id)
        if question is None or payload is None:
            continue
        if not tool_answer_is_valid(answer, shown=payload):
            continue
        selected = selected_tool_option(answer)
        option = next(option for option in payload.options if option.id == selected)
        yield ToolAnswer(question=question, option=option, answer=answer)


def answered_tool_relevance(
    conversation: Sequence[ConversationMessage],
) -> ToolRelevanceAnswer:
    """What the person last answered to whether the flow uses the tools: the
    last answer counts."""
    result = ToolRelevanceAnswer()
    for item in tool_answers(conversation):
        if not isinstance(item.question, ToolRelevanceQuestion):
            continue
        if item.option.id == RELEVANCE_SHOW_TOOLS:
            result = ToolRelevanceAnswer(result.relevance, tools_requested=True)
        else:
            result = ToolRelevanceAnswer(
                "use" if item.option.id == RELEVANCE_USE else "dont_use"
            )
    return result


def offers_no_run_input(
    conversation: Sequence[ConversationMessage], *, is_edit_mode: bool
) -> bool:
    """Whether the run-input question may be answered with no_run_input, and
    whether such an answer still counts: only in a create session whose
    person's latest answer is to use the space's tools and who has not
    declined a tool for every use they decided, so a tool can still supply
    the data a run would otherwise be given. An edit reads the value off the
    saved flow instead."""
    if is_edit_mode or answered_tool_relevance(conversation).relevance != "use":
        return False
    no_tool_by_use = {
        item.question.use_ref: item.option.id == NO_TOOL
        for item in tool_answers(conversation)
        if isinstance(item.question, ToolChoiceQuestion)
    }
    return not no_tool_by_use or not all(no_tool_by_use.values())

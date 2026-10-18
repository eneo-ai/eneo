"""The questions the Builder asks about a space's MCP tools, and what the
person's answers decide.

``tool_relevance`` is asked once in a create session; ``tool_choice:<use_ref>``
and ``tool_argument:<use_ref>:<argument>`` after a draft, per use and per
argument. Answers are read against the showing they answer and folded again
every turn. Every server and tool here is a neutral fake.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.flows.ai_builder.ai_builder_backend_question_persistence import (
    persist_backend_question,
)
from eneo.flows.ai_builder.ai_builder_canonicalization import (
    is_supported_structured_question_id,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    DelegatedQuestionAnswerRequest,
    StructuredQuestionAnswerRequest,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import BackendQuestion
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_edit_proposal import process_edit_arguments
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderQuestionEvent,
    AIBuilderTextEvent,
    AIBuilderToolRefusal,
    StructuredQuestionOptionPayload,
    StructuredQuestionPayload,
)
from eneo.flows.ai_builder.ai_builder_non_plan_outcome import persist_non_plan_turn
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    ProposalPrepared,
    ServerOutputPrepared,
    build_proposal_prepared,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CorrectableFailure,
    ProposalAnswer,
    ProposalNeedsDecision,
    ProposalReady,
)
from eneo.flows.ai_builder.ai_builder_question_state import shown_question
from eneo.flows.ai_builder.ai_builder_requirements_state import RequirementsState
from eneo.flows.ai_builder.ai_builder_tool_catalog import (
    AIBuilderToolCatalogLeftOut,
    tool_ref,
)
from eneo.flows.ai_builder.ai_builder_tool_decisions import (
    FixedTextDecision,
    ToolDecisions,
    ToolUseDecision,
)
from eneo.flows.ai_builder.ai_builder_tool_question_ids import (
    AIBuilderToolQuestion,
    ToolArgumentQuestion,
    ToolChoiceQuestion,
    ToolRelevanceQuestion,
    parse_tool_question_id,
    tool_question_id,
)
from eneo.flows.ai_builder.ai_builder_tool_questions import (
    EarlierField,
    RunForm,
    SettledToolUses,
    ToolSettlement,
    ToolUseSite,
    fold_tool_decisions,
    render_tool_decisions_block,
    settle_tool_uses,
    tool_relevance_question,
    users_quote_check,
)
from eneo.flows.ai_builder.ai_builder_tool_use import (
    EarlierStepToolArgument,
    FixedToolArgument,
    RunInputToolArgument,
    ToolUseIntent,
)
from eneo.flows.ai_builder.ai_builder_tool_validation import tool_not_usable_answer
from eneo.flows.ai_builder.ai_builder_turn_controller import AskCanonicalQuestion
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    prepare_user_question_metadata,
)
from eneo.flows.ai_builder.planning_state import (
    ConfirmedRuntimeMetadataField,
    PlanningState,
)
from eneo.flows.api.flow_ai_builder_router import _to_public_conversation
from eneo.flows.application.flow_tool_options import FlowToolOption, FlowToolOptions
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.flow_authoring_spec import FormFieldSpec
from eneo.mcp_servers.application.unattended_tool_use import UnattendedToolRefusal
from tests.unittests.flows.ai_builder.test_ai_builder_create_proposal import (
    _make_turn,
)
from tests.unittests.flows.ai_builder.test_ai_builder_planner import (
    _budget_policy,
    _discovery_analysis,
    _make_planner,
    _prepare_planner_request_for_test,
    _requirements_state_unconfirmed,
    _route,
    _runtime_result,
)
from tests.unittests.flows.ai_builder.test_ai_builder_tool_steps import (
    DEPARTMENT,
    DETAILS,
    DETAILS_REF,
    OFF,
    OFF_REF,
    SERVER,
    VALUES,
    VALUES_REF,
    _argument,
    _catalog,
    _option,
    _saved_flow,
)

ROWS_TOOL = UUID("9d4e5f6a-7b8c-4d9e-8fa0-2b3c4d5e6f70")
ROWS = _option(
    ROWS_TOOL,
    "rows",
    {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "maximum": 10},
            "label": {"type": "string"},
            "unit": {"type": "string", "enum": ["hour", "day"]},
            "start": {"type": "string", "format": "date"},
        },
        "required": ["limit"],
    },
)
ROWS_REF = tool_ref(SERVER, ROWS_TOOL)
_PREPARATION = "eneo.flows.ai_builder.ai_builder_planner_request_preparation"


def _use(
    use_ref: str, ref: str, *arguments: dict[str, Any], **fields: Any
) -> ToolUseIntent:
    return ToolUseIntent.model_validate(
        {"use_ref": use_ref, "tool_ref": ref, "arguments": list(arguments), **fields}
    )


def _site(
    use: ToolUseIntent,
    *earlier: EarlierField,
    needs_confirmation: bool = False,
) -> ToolUseSite:
    return ToolUseSite(
        label=f"step '{use.use_ref}'",
        step_name=use.use_ref,
        use=use,
        earlier_fields=earlier,
        needs_confirmation=needs_confirmation,
    )


def _settle(
    *sites: ToolUseSite,
    decisions: ToolDecisions | None = None,
    tools: tuple[FlowToolOption, ...] = (VALUES, DETAILS, ROWS),
    conversation: list[ConversationMessage] | None = None,
    projection_left_out: bool = False,
    run_form: RunForm = RunForm(fields=(), adds_fields=True),
) -> ToolSettlement:
    catalog = _catalog(*tools).tools
    if projection_left_out:
        catalog = replace(catalog, projection=AIBuilderToolCatalogLeftOut())
    return asyncio.run(
        settle_tool_uses(
            sites,
            decisions=decisions or ToolDecisions(),
            catalog=catalog,
            run_form=run_form,
            is_users_quote=users_quote_check(conversation or []),
            ui_language="en",
        )
    )


def _asked(outcome: ToolSettlement) -> StructuredQuestionPayload:
    assert isinstance(outcome, ProposalNeedsDecision), outcome
    return outcome.question.question_data


def _show(
    conversation: list[ConversationMessage], question: BackendQuestion
) -> StructuredQuestionPayload:
    """Persist a showing the way a turn does, and read it back."""
    repo = SimpleNamespace(commit_turn=AsyncMock(return_value=1))
    result = asyncio.run(
        persist_backend_question(
            repo=cast(Any, repo),
            turn=_make_turn(),
            conversation=conversation,
            new_messages_start=len(conversation),
            question=question,
            planning_state=PlanningState.empty(),
        )
    )
    shown = shown_question(conversation[-2])
    assert shown is not None
    assert [type(event) for event in result.events] == [
        AIBuilderTextEvent,
        AIBuilderQuestionEvent,
    ]
    return shown


def _answer(
    conversation: list[ConversationMessage],
    shown: StructuredQuestionPayload,
    option_id: str,
    custom_value: str | None = None,
) -> None:
    """Send an answer through the validation every client answer passes."""
    prepared = prepare_user_question_metadata(
        is_edit_mode=False,
        conversation=conversation,
        message="",
        question_answer=StructuredQuestionAnswerRequest(
            question_id=shown.question_id,
            instance_token=shown.instance_token,
            selected_option_ids=[option_id],
            custom_value=custom_value,
        ),
        ui_language="en",
    )
    conversation.append(
        ConversationMessage(role="user", content="", metadata=prepared.metadata)
    )


def conversation_using_tools(choices: dict[str, str]) -> list[ConversationMessage]:
    """A create conversation whose person said to use the tools and chose, per
    use, the tool ``choices`` names."""
    conversation = [ConversationMessage(role="user", content="Build it.")]
    relevance = _show(
        conversation,
        tool_relevance_question(
            _catalog(VALUES, DETAILS).tools, ui_language="en", show_tools=False
        ),
    )
    _answer(conversation, relevance, "use")
    for use_ref, ref in choices.items():
        choice = _shown_by_hand(conversation, f"tool_choice:{use_ref}", ref)
        _answer(conversation, choice, ref)
    return conversation


def test_question_ids_round_trip_and_other_ids_are_not_tool_questions() -> None:
    # Kills: an argument name cut at its own colon, an id longer than an
    # answer stores read as a question, a use_ref outside the planner's
    # pattern accepted, an argument id without its tool's ref read, the
    # family ids unknown to the question vocabulary (every answer to them
    # refused as unsupported).
    for question in (
        ToolRelevanceQuestion(),
        ToolChoiceQuestion("lookup"),
        ToolArgumentQuestion("lookup", ROWS_REF, "range:start"),
    ):
        question_id = tool_question_id(question)
        assert parse_tool_question_id(question_id) == question
        assert is_supported_structured_question_id(question_id)
    for other in (
        "tool_choice:Lookup",
        f"tool_argument:lookup:{ROWS_REF}:",
        "tool_argument:lookup:range:start",
        f"tool_argument:lookup:{ROWS_REF}:" + "x" * 100,
        "primary_runtime_input",
    ):
        assert parse_tool_question_id(other) is None


@pytest.mark.parametrize(
    ("tool_question", "allow_custom"),
    [
        (AIBuilderToolQuestion(family="choice", fixed_value_option_id="a"), True),
        (
            AIBuilderToolQuestion(
                family="argument",
                use_ref="r",
                argument_name="x",
                fixed_value_option_id="z",
            ),
            True,
        ),
        (
            AIBuilderToolQuestion(
                family="argument",
                use_ref="r",
                argument_name="x",
                fixed_value_option_id="a",
            ),
            False,
        ),
    ],
)
def test_a_typed_value_option_is_one_offered_on_an_argument_question(
    tool_question: AIBuilderToolQuestion, allow_custom: bool
) -> None:
    # Kills: a showing that names a typed-value option the web cannot find,
    # one on a question that takes no typed value, or on another family.
    with pytest.raises(ValueError):
        StructuredQuestionPayload(
            question_id="tool_argument:r:x",
            question="?",
            options=[StructuredQuestionOptionPayload(id="a", label="A", value="a")],
            selection_mode="single",
            allow_custom=allow_custom,
            tool_question=tool_question,
        )


def test_an_answer_is_read_against_the_question_as_it_was_shown() -> None:
    # Kills: an option of an earlier showing accepted, a fixed value with
    # nothing typed, a typed value on an option that takes none, the typed
    # family facts lost from a persisted showing.
    catalog = _catalog(VALUES, DETAILS).tools
    conversation = [ConversationMessage(role="user", content="Build a report.")]
    first = _show(
        conversation,
        tool_relevance_question(catalog, ui_language="en", show_tools=False),
    )
    _answer(conversation, first, "show_tools")
    listed = _show(
        conversation,
        tool_relevance_question(catalog, ui_language="en", show_tools=True),
    )
    with pytest.raises(AIBuilderBadRequestException):
        _answer(conversation, listed, "show_tools")
    question = _asked(
        _settle(_site(_use("rows", ROWS_REF, _argument("label", "ask_user"))))
    )
    asked = _show(
        conversation, BackendQuestion(question_data=question, assistant_text="?")
    )
    for option_id, custom_value in (
        ("fixed", None),
        ("fixed", " "),
        ("run_input:label", "x"),
    ):
        with pytest.raises(AIBuilderBadRequestException):
            _answer(conversation, asked, option_id, custom_value)
    _answer(conversation, asked, "fixed", "north")

    assert [option.id for option in listed.options] == ["use", "dont_use"]
    # The family travels typed on the showing, through persistence.
    assert first.tool_question == AIBuilderToolQuestion(family="relevance")
    assert asked.tool_question == AIBuilderToolQuestion(
        family="argument",
        use_ref="rows",
        argument_name="label",
        fixed_value_option_id="fixed",
    )
    listing = next(m.content for m in conversation if shown_question(m) == listed)
    assert "values_by_day" in listing and "details_for_days" in listing
    assert fold_tool_decisions(conversation, catalog=catalog).tools_requested is True


def test_the_last_answer_to_a_question_wins_and_a_tool_gone_is_dropped() -> None:
    # Kills: the first answer kept over a later one, a choice of a tool the
    # space no longer offers kept as a decision, an argument answered for a
    # tool other than the chosen one kept, answers of one use applied to
    # another.
    catalog = _catalog(VALUES, DETAILS, ROWS).tools
    conversation: list[ConversationMessage] = []
    relevance = _show(
        conversation,
        tool_relevance_question(catalog, ui_language="en", show_tools=False),
    )
    _answer(conversation, relevance, "dont_use")
    relevance = _show(
        conversation,
        tool_relevance_question(catalog, ui_language="en", show_tools=False),
    )
    _answer(conversation, relevance, "use")
    choice = _asked(
        _settle(_site(_use("rows", ROWS_REF, alternative_refs=[DETAILS_REF])))
    )
    shown_choice = _show(
        conversation, BackendQuestion(question_data=choice, assistant_text="?")
    )
    _answer(conversation, shown_choice, DETAILS_REF)
    argument = _asked(
        _settle(
            _site(_use("rows", ROWS_REF, _argument("label", "ask_user"))),
            decisions=ToolDecisions(uses={"rows": ToolUseDecision(tool_ref=ROWS_REF)}),
        )
    )
    shown_argument = _show(
        conversation, BackendQuestion(question_data=argument, assistant_text="?")
    )
    _answer(conversation, shown_argument, "fixed", "north")
    shown_choice = _show(
        conversation, BackendQuestion(question_data=choice, assistant_text="?")
    )
    _answer(conversation, shown_choice, ROWS_REF)
    other = _asked(
        _settle(_site(_use("other", VALUES_REF, alternative_refs=[ROWS_REF])))
    )
    shown_other = _show(
        conversation, BackendQuestion(question_data=other, assistant_text="?")
    )
    _answer(conversation, shown_other, "no_tool")

    decided = fold_tool_decisions(conversation, catalog=catalog)
    without_rows = fold_tool_decisions(
        conversation, catalog=_catalog(VALUES, DETAILS).tools
    )

    assert decided.relevance == "use"
    assert decided.uses == {
        "rows": ToolUseDecision(tool_ref=ROWS_REF),
        "other": ToolUseDecision(no_tool=True),
    }
    assert "rows" not in without_rows.uses


def test_letting_eneo_decide_a_tool_choice_picks_the_models_tool() -> None:
    # Kills: a delegated choice answered with another candidate than the one
    # the model proposed.
    catalog = _catalog(VALUES, DETAILS, ROWS).tools
    conversation: list[ConversationMessage] = []
    choice = _asked(
        _settle(
            _site(_use("rows", ROWS_REF, alternative_refs=[DETAILS_REF, VALUES_REF]))
        )
    )
    shown = _show(
        conversation, BackendQuestion(question_data=choice, assistant_text="?")
    )
    prepared = prepare_user_question_metadata(
        is_edit_mode=False,
        conversation=conversation,
        message="",
        question_answer=DelegatedQuestionAnswerRequest(
            question_id=shown.question_id, instance_token=shown.instance_token
        ),
        ui_language="en",
    )
    conversation.append(
        ConversationMessage(role="user", content="", metadata=prepared.metadata)
    )

    assert fold_tool_decisions(conversation, catalog=catalog).uses == {
        "rows": ToolUseDecision(tool_ref=ROWS_REF)
    }


def test_a_decision_the_draft_leaves_out_is_kept() -> None:
    # Kills: a decided argument lost when the next draft omits it, a decision
    # for an argument the tool does not declare written into the step.
    draft = _site(_use("rows", ROWS_REF, _argument("limit", "fixed", value_json="5")))

    settled = _settle(
        draft,
        decisions=ToolDecisions(
            uses={
                "rows": ToolUseDecision(
                    tool_ref=ROWS_REF,
                    arguments_for=ROWS_REF,
                    arguments={
                        "label": FixedTextDecision(name="label", text="north"),
                        "days": FixedTextDecision(name="days", text="[]"),
                    },
                )
            }
        ),
    )

    assert isinstance(settled, SettledToolUses)
    assert settled.uses[0].arguments == (
        FixedToolArgument(name="limit", value=5),
        FixedToolArgument(name="label", value="north"),
    )


@pytest.mark.parametrize("typed", ["NaN", "Infinity", "1e999"])
def test_a_typed_number_the_editor_cannot_hold_is_asked_again(typed: str) -> None:
    # Kills: a non-finite or out-of-range number taken as a value (it breaks
    # the argument check instead of asking).
    asked = _asked(
        _settle(
            _site(_use("rows", ROWS_REF, _argument("limit", "ask_user"))),
            decisions=ToolDecisions(
                uses={
                    "rows": ToolUseDecision(
                        tool_ref=ROWS_REF,
                        arguments_for=ROWS_REF,
                        arguments={
                            "limit": FixedTextDecision(name="limit", text=typed)
                        },
                    )
                }
            ),
        )
    )

    assert asked.question_id == f"tool_argument:rows:{ROWS_REF}:limit"


def test_an_argument_answered_for_one_tool_never_fills_another() -> None:
    # Kills: the answer for one tool's argument written into another tool
    # the next draft puts on the same use.
    answered_for_rows = ToolDecisions(
        uses={
            "rows": ToolUseDecision(
                arguments_for=ROWS_REF,
                arguments={"unit": FixedToolArgument(name="unit", value="hour")},
            )
        }
    )
    draft = _use(
        "rows",
        VALUES_REF,
        _argument("from_date", "fixed", value_json='"2026-01-01"'),
        _argument("to_date", "fixed", value_json='"2026-01-31"'),
        _argument("unit", "ask_user"),
    )

    asked = _asked(_settle(_site(draft), decisions=answered_for_rows))

    assert asked.question_id == f"tool_argument:rows:{VALUES_REF}:unit"


def test_answers_for_one_tool_are_dropped_when_another_tool_is_answered() -> None:
    # Kills: an argument answer that keeps the answers given for another
    # tool of the use, a tool choice that keeps answers given for another.
    catalog = _catalog(VALUES, DETAILS, ROWS).tools
    conversation: list[ConversationMessage] = []
    fixed_dates = (
        _argument("from_date", "fixed", value_json='"2026-01-01"'),
        _argument("to_date", "fixed", value_json='"2026-01-31"'),
    )
    for use_ref in ("a", "b"):
        unit = _asked(
            _settle(
                _site(
                    _use(
                        use_ref, VALUES_REF, *fixed_dates, _argument("unit", "ask_user")
                    )
                )
            )
        )
        _answer(
            conversation,
            _show(
                conversation, BackendQuestion(question_data=unit, assistant_text="?")
            ),
            "value:0",
        )
    label = _asked(_settle(_site(_use("a", ROWS_REF, _argument("label", "ask_user")))))
    _answer(
        conversation,
        _show(conversation, BackendQuestion(question_data=label, assistant_text="?")),
        "fixed",
        "north",
    )
    choice = _asked(_settle(_site(_use("b", ROWS_REF, alternative_refs=[DETAILS_REF]))))
    _answer(
        conversation,
        _show(conversation, BackendQuestion(question_data=choice, assistant_text="?")),
        ROWS_REF,
    )

    decided = fold_tool_decisions(conversation, catalog=catalog)

    assert decided.uses == {
        "a": ToolUseDecision(
            arguments_for=ROWS_REF,
            arguments={"label": FixedTextDecision(name="label", text="north")},
        ),
        "b": ToolUseDecision(tool_ref=ROWS_REF),
    }


def test_an_old_question_about_another_tool_decides_nothing_for_the_chosen_one() -> (
    None
):
    # Kills: a late answer to a question about a tool the person chose
    # against overwriting the chosen tool's values, values stated to the
    # planner without the tool they were given for.
    catalog = _catalog(VALUES, DETAILS, ROWS).tools
    conversation: list[ConversationMessage] = []
    dates = (
        _argument("from_date", "fixed", value_json='"2026-01-01"'),
        _argument("to_date", "fixed", value_json='"2026-01-31"'),
    )
    values_unit = _show(
        conversation,
        BackendQuestion(
            question_data=_asked(
                _settle(
                    _site(
                        _use("rows", VALUES_REF, *dates, _argument("unit", "ask_user"))
                    )
                )
            ),
            assistant_text="?",
        ),
    )
    _answer(conversation, values_unit, "value:0")
    before_choice = fold_tool_decisions(conversation, catalog=catalog)
    choice = _shown_by_hand(conversation, "tool_choice:rows", ROWS_REF)
    _answer(conversation, choice, ROWS_REF)
    rows_unit = _show(
        conversation,
        BackendQuestion(
            question_data=_asked(
                _settle(_site(_use("rows", ROWS_REF, _argument("unit", "ask_user"))))
            ),
            assistant_text="?",
        ),
    )
    _answer(conversation, rows_unit, "value:0")
    _answer(conversation, values_unit, "value:1")

    decided = fold_tool_decisions(conversation, catalog=catalog)

    assert decided.uses == {
        "rows": ToolUseDecision(
            tool_ref=ROWS_REF,
            arguments_for=ROWS_REF,
            arguments={"unit": FixedToolArgument(name="unit", value="hour")},
        )
    }
    assert f"- use_ref=rows: values for tool_ref={VALUES_REF}" in (
        render_tool_decisions_block(before_choice, catalog=catalog, listing=None)
    )


def test_an_allowed_value_the_editor_cannot_hold_is_neither_offered_nor_kept() -> None:
    # Kills: an enum value beyond the exact range offered as an option, or
    # kept when decided, so the step saves a number other than the one shown.
    huge = _option(
        ROWS_TOOL,
        "rows",
        {
            "type": "object",
            "properties": {"limit": {"enum": [9007199254740993, 5]}},
            "required": ["limit"],
        },
    )
    site = _site(_use("rows", ROWS_REF, _argument("limit", "ask_user")))
    decided = ToolDecisions(
        uses={
            "rows": ToolUseDecision(
                tool_ref=ROWS_REF,
                arguments_for=ROWS_REF,
                arguments={
                    "limit": FixedToolArgument(name="limit", value=9007199254740993)
                },
            )
        }
    )

    asked = _asked(_settle(site, tools=(huge,)))
    asked_again = _asked(_settle(site, decisions=decided, tools=(huge,)))

    assert [
        option.value for option in asked.options if option.id.startswith("value:")
    ] == [5]
    assert asked_again.question_id == asked.question_id


def test_an_argument_that_allows_only_inexact_numbers_reads_another_source() -> None:
    # Kills: an earlier step's field refused for an argument whose allowed
    # values are not exact (the field carries the value, not the step), a
    # typed value offered that no answer can satisfy, a question with no
    # option asked instead of the answer.
    only_huge = _option(
        ROWS_TOOL,
        "rows",
        {
            "type": "object",
            "properties": {"limit": {"type": "integer", "enum": [9007199254740993]}},
            "required": ["limit"],
        },
    )
    use = _use("rows", ROWS_REF, _argument("limit", "ask_user"))
    record = EarlierField(1, "record_id", "number")
    bound = EarlierStepToolArgument(name="limit", from_step=1, field_path="record_id")

    asked = _asked(_settle(_site(use, record), tools=(only_huge,)))
    settled = _settle(
        _site(use, record),
        decisions=ToolDecisions(
            uses={
                "rows": ToolUseDecision(
                    tool_ref=ROWS_REF,
                    arguments_for=ROWS_REF,
                    arguments={"limit": bound},
                )
            }
        ),
        tools=(only_huge,),
    )
    answered = _settle(_site(use), tools=(only_huge,))

    assert [option.id for option in asked.options] == ["earlier_step:1:record_id"]
    assert isinstance(settled, SettledToolUses)
    assert settled.uses[0].arguments == (bound,)
    assert isinstance(answered, ProposalAnswer)
    assert answered.codes == frozenset({"tool_argument_values_not_exact"})


def test_a_use_needing_more_values_than_the_decisions_hold_is_answered() -> None:
    # Kills: one use asking argument after argument past the decisions'
    # bound, the oldest answer dropped and asked again forever.
    many = _option(
        ROWS_TOOL,
        "rows",
        {
            "type": "object",
            "properties": {f"a{n}": {"type": "string"} for n in range(41)},
            "required": [f"a{n}" for n in range(41)],
        },
    )

    answered = _settle(
        _site(
            _use("rows", ROWS_REF, *(_argument(f"a{n}", "ask_user") for n in range(41)))
        ),
        tools=(many,),
    )

    assert isinstance(answered, ProposalAnswer)
    assert answered.codes == frozenset({"too_many_tool_arguments"})


def test_an_edit_settles_against_the_run_form_compile_uses() -> None:
    # Kills: an edit's decided run-form field checked against the model's
    # form while compile reads the form with the fields the person confirmed.
    added = {
        "kind": "add",
        "step": {
            "name": "Rader",
            "instructions": "Hämta rader.",
            "tool_use": {
                "use_ref": "rows",
                "tool_ref": ROWS_REF,
                "arguments": [
                    _argument("limit", "fixed", value_json="5"),
                    _argument("label", "ask_user"),
                ],
            },
        },
    }

    outcome = _edit_outcome(
        added,
        ToolDecisions(
            uses={
                "rows": ToolUseDecision(
                    tool_ref=ROWS_REF,
                    arguments_for=ROWS_REF,
                    arguments={
                        "label": RunInputToolArgument(
                            name="label", field_name="department"
                        )
                    },
                )
            }
        ),
        tools=(VALUES, DETAILS, ROWS),
        confirmed=(DEPARTMENT,),
    )

    assert isinstance(outcome, ProposalReady), outcome


def test_more_uses_than_a_flow_holds_are_answered() -> None:
    # Kills: a plan with more tool uses than the decisions hold asked use by
    # use, its answers dropped and asked again forever.
    sites = [
        _site(_use(f"u{n}", ROWS_REF, _argument("limit", "fixed", value_json="5")))
        for n in range(21)
    ]

    answered = _settle(*sites)

    assert isinstance(answered, ProposalAnswer)
    assert answered.codes == frozenset({"too_many_tool_uses"})


def test_the_decisions_keep_the_latest_uses_and_the_state_reloads() -> None:
    # Kills: a new answer dropped once the bound is reached, a use answered
    # again dropped as if it were the oldest, the decisions stored with the
    # planning state (they only add payload: every turn reads them again).
    catalog = _catalog(VALUES, DETAILS, ROWS).tools
    conversation: list[ConversationMessage] = []
    for use_ref in [*(f"u{n}" for n in range(20)), "u0", "u20", "u21"]:
        choice = _asked(
            _settle(_site(_use(use_ref, ROWS_REF, alternative_refs=[DETAILS_REF])))
        )
        shown = _show(
            conversation, BackendQuestion(question_data=choice, assistant_text="?")
        )
        _answer(conversation, shown, ROWS_REF)
    state = PlanningState.empty()

    state.tool_decisions = fold_tool_decisions(conversation, catalog=catalog)

    assert list(state.tool_decisions.uses) == [
        *(f"u{n}" for n in range(3, 20)),
        "u0",
        "u20",
        "u21",
    ]
    assert "tool_decisions" not in state.model_dump(mode="json")


def _shown_by_hand(
    conversation: list[ConversationMessage], question_id: str, *option_ids: str
) -> StructuredQuestionPayload:
    return _show(
        conversation,
        BackendQuestion(
            question_data=StructuredQuestionPayload(
                question_id=question_id,
                question="?",
                options=[
                    StructuredQuestionOptionPayload(
                        id=option_id, label=option_id, value="hour"
                    )
                    for option_id in option_ids
                ],
                selection_mode="single",
                allow_custom=False,
            ),
            assistant_text="?",
        ),
    )


def test_an_answer_counts_against_the_latest_showing_and_an_unreadable_one_is_skipped() -> (
    None
):
    # Kills: an answer read against an earlier showing of its question, an
    # option this build cannot read as a decision that breaks every later
    # turn.
    catalog = _catalog(ROWS).tools
    conversation: list[ConversationMessage] = []
    _shown_by_hand(conversation, f"tool_argument:rows:{ROWS_REF}:unit", "fixed")
    latest = _shown_by_hand(
        conversation, f"tool_argument:rows:{ROWS_REF}:unit", "value:0"
    )
    _answer(conversation, latest, "value:0")
    unreadable = _shown_by_hand(
        conversation, f"tool_argument:rows:{ROWS_REF}:start", "earlier_step:1:e.g."
    )
    _answer(conversation, unreadable, "earlier_step:1:e.g.")

    decided = fold_tool_decisions(conversation, catalog=catalog)

    assert decided.uses == {
        "rows": ToolUseDecision(
            arguments_for=ROWS_REF,
            arguments={"unit": FixedToolArgument(name="unit", value="hour")},
        )
    }


def _proposal_schema_steps(
    planning_state: PlanningState,
    *,
    is_edit_mode: bool,
    tools: tuple[FlowToolOption, ...] = (VALUES, DETAILS),
    conversation: list[ConversationMessage] | None = None,
) -> Any:
    prepared = build_proposal_prepared(
        requirements_state=RequirementsState(),
        ui_language="en",
        slot_classification_metadata=None,
        conversation=conversation
        or [ConversationMessage(role="user", content="Build the flow.")],
        planning_state=planning_state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=is_edit_mode,
        resource_catalog=_catalog(*tools),
        flow=_saved_flow() if is_edit_mode else None,
        assistant_snapshots=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        litellm_model="gpt-4o-mini",
        capacity=ModelCapacity(100_000, 1024),
        budget_policy=_budget_policy(),
        attachment_file_count=0,
        current_turn_start=0,
    )
    assert isinstance(prepared, ProposalPrepared)
    return prepared.proposal_tool_schema["function"]["parameters"]["properties"][
        "steps"
    ]["items"]


@pytest.mark.parametrize(
    ("relevance", "offered"),
    [(None, False), ("dont_use", False), ("use", True)],
)
def test_a_create_schema_offers_tool_use_only_after_a_use_answer(
    relevance: Any, offered: bool
) -> None:
    # Kills: tool_use offered before the person said to use the tools, or
    # after they said not to; a proposal built from a stored state (the
    # continuation after a server decision) that does not read the answers.
    conversation = [ConversationMessage(role="user", content="Build the flow.")]
    if relevance is not None:
        shown = _show(
            conversation,
            tool_relevance_question(
                _catalog(VALUES, DETAILS).tools, ui_language="en", show_tools=False
            ),
        )
        _answer(conversation, shown, relevance)

    steps = _proposal_schema_steps(
        PlanningState.empty(), is_edit_mode=False, conversation=conversation
    )

    assert ("tool_use" in steps["properties"]) is offered


def test_a_create_session_whose_tools_are_all_refused_still_names_them() -> None:
    # Kills: the refused tools hidden until a relevance answer no session
    # with nothing usable is asked, so a request for one is never told why.
    steps = _proposal_schema_steps(
        PlanningState.empty(), is_edit_mode=False, tools=(OFF,)
    )

    assert steps["properties"]["tool_use"]["properties"]["tool_ref"]["enum"] == [
        OFF_REF
    ]


def test_a_create_session_asks_once_whether_to_use_the_tools() -> None:
    # Kills: the relevance question skipped in a create session with usable
    # tools, asked in an edit, asked again once answered, decisions read from
    # the persisted state instead of the conversation.
    planner = _make_planner()
    options = FlowToolOptions(
        options=[VALUES, OFF], security_classifications_enabled=False
    )
    conversation = [ConversationMessage(role="user", content="Build a report.")]

    def prepare(persisted: PlanningState | None, flow: object = None) -> Any:
        with (
            patch(
                f"{_PREPARATION}.resolve_requirements_state",
                return_value=_requirements_state_unconfirmed(),
            ),
            patch(
                f"{_PREPARATION}.build_discovery_runtime_result",
                new_callable=AsyncMock,
                return_value=_runtime_result(
                    _discovery_analysis(), PlanningState.empty()
                ),
            ),
            patch(
                f"{_PREPARATION}.compute_conversation_token_budget", return_value=256
            ),
        ):
            return asyncio.run(
                _prepare_planner_request_for_test(
                    planner,
                    conversation=conversation,
                    completion_model_route=_route(),
                    tool_options=options,
                    persisted_planning_state=persisted,
                    flow=flow,
                )
            )

    in_edit = prepare(None, flow=_saved_flow())
    asked = prepare(None)
    assert not (
        isinstance(in_edit, ServerOutputPrepared)
        and isinstance(in_edit.server_decision, AskCanonicalQuestion)
        and in_edit.server_decision.slot_name == "tool_relevance"
    )
    assert isinstance(asked, ServerOutputPrepared)
    decision = asked.server_decision
    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "tool_relevance" and decision.question is not None
    shown = _show(conversation, decision.question)
    _answer(conversation, shown, "use")
    stale = PlanningState.empty()
    stale.tool_decisions = ToolDecisions(relevance="dont_use")

    answered = prepare(stale)

    assert [option.id for option in shown.options] == ["use", "dont_use", "show_tools"]
    assert answered.planning_state.tool_decisions == ToolDecisions(relevance="use")
    assert not (
        isinstance(answered, ServerOutputPrepared)
        and isinstance(answered.server_decision, AskCanonicalQuestion)
        and answered.server_decision.slot_name == "tool_relevance"
    )


def test_a_use_is_asked_when_other_tools_fit_with_the_users_words_as_why() -> None:
    # Kills: the choice skipped when alternatives fit, a question skipped
    # because the draft cites the user, a quote the user never wrote shown
    # as why, a use with one fitting tool asked although the relevance
    # answer consented, two uses sharing one question, a use_ref given twice
    # let through.
    conversation = [ConversationMessage(role="user", content="Läs med rows varje dag.")]
    named = _use(
        "rows",
        ROWS_REF,
        _argument("limit", "fixed", value_json="5"),
        alternative_refs=[VALUES_REF],
        evidence_quote="med rows",
    )
    unquoted = named.model_copy(update={"evidence_quote": "use rows please"})
    only = named.model_copy(update={"alternative_refs": ()})
    second = _use(
        "days",
        DETAILS_REF,
        _argument("days", "fixed", value_json="[]"),
        alternative_refs=[VALUES_REF],
    )

    asked = _asked(_settle(_site(named), conversation=conversation))
    unquoted_asked = _asked(_settle(_site(unquoted), conversation=conversation))
    settled = _settle(_site(only), conversation=conversation)
    second_asked = _asked(
        _settle(_site(only), _site(second), conversation=conversation)
    )
    repeated = _settle(_site(only), _site(only), conversation=conversation)

    assert asked.question_id == "tool_choice:rows"
    assert asked.tool_question == AIBuilderToolQuestion(family="choice", use_ref="rows")
    assert [option.id for option in asked.options] == [ROWS_REF, VALUES_REF, "no_tool"]
    assert asked.recommended_option_id == ROWS_REF
    assert asked.recommended_option_evidence == "med rows"
    assert unquoted_asked.recommended_option_evidence is None
    assert isinstance(settled, SettledToolUses) and settled.uses == (only,)
    assert second_asked.question_id == "tool_choice:days"
    assert isinstance(repeated, CorrectableFailure)
    assert repeated.codes == frozenset({"tool_use_ref_repeated"})


def test_a_draft_that_contradicts_the_persons_choice_is_repaired() -> None:
    # Kills: a decided "no tool" or another decided tool overridden by the
    # draft.
    use = _use("rows", ROWS_REF, _argument("limit", "fixed", value_json="5"))
    for decision in (
        ToolUseDecision(no_tool=True),
        ToolUseDecision(tool_ref=VALUES_REF),
    ):
        outcome = _settle(_site(use), decisions=ToolDecisions(uses={"rows": decision}))
        assert isinstance(outcome, CorrectableFailure)
        assert outcome.codes == frozenset({"tool_decision_contradicted"})


def test_an_open_argument_is_asked_with_the_sources_its_type_fits() -> None:
    # Kills: an earlier step's field of another JSON type offered, or one
    # whose name a field path cannot read whole ("e.g."), a typed value
    # offered for an argument that has allowed values, the typed value's
    # option not named to the web (or named where no value can be typed).
    decided = ToolDecisions(uses={"rows": ToolUseDecision(tool_ref=ROWS_REF)})
    earlier = (
        EarlierField(1, "first_day", "string"),
        EarlierField(1, "days", "array"),
        EarlierField(1, "e.g.", "string"),
    )

    start = _asked(
        _settle(
            _site(
                _use(
                    "rows", ROWS_REF, _argument("start", "ask_user", field_name="start")
                ),
                *earlier,
            ),
            decisions=decided,
        )
    )
    unit = _asked(
        _settle(
            _site(_use("rows", ROWS_REF, _argument("unit", "ask_user")), *earlier),
            decisions=decided,
        )
    )

    assert start.question_id == f"tool_argument:rows:{ROWS_REF}:start"
    assert [option.id for option in start.options] == [
        "fixed",
        "run_input:start",
        "earlier_step:1:first_day",
    ]
    assert start.allow_custom is True
    assert [option.id for option in unit.options] == [
        "value:0",
        "value:1",
        "run_input:unit",
        "earlier_step:1:first_day",
    ]
    assert unit.allow_custom is False
    # Only an argument that takes a typed value names the option it answers.
    assert start.tool_question is not None and unit.tool_question is not None
    assert start.tool_question.fixed_value_option_id == "fixed"
    assert unit.tool_question.fixed_value_option_id is None


def test_a_decided_argument_replaces_the_planners_and_a_refused_value_is_asked_again() -> (
    None
):
    # Kills: a typed number kept as text, a typed text read as JSON, a typed
    # value the argument's schema refuses let through, the planner's
    # suggested run-form label dropped.
    use = _use(
        "rows",
        ROWS_REF,
        _argument("limit", "ask_user"),
        _argument("label", "ask_user"),
        _argument("start", "ask_user", field_label="First day"),
    )

    def decide(limit: str) -> ToolDecisions:
        return ToolDecisions(
            uses={
                "rows": ToolUseDecision(
                    tool_ref=ROWS_REF,
                    arguments_for=ROWS_REF,
                    arguments={
                        "limit": FixedTextDecision(name="limit", text=limit),
                        "label": FixedTextDecision(name="label", text="42"),
                        "start": RunInputToolArgument(name="start", field_name="start"),
                    },
                )
            }
        )

    settled = _settle(_site(use), decisions=decide("5"))
    refused = _asked(_settle(_site(use), decisions=decide("50")))

    assert isinstance(settled, SettledToolUses)
    assert settled.uses[0].arguments == (
        FixedToolArgument(name="limit", value=5),
        FixedToolArgument(name="label", value="42"),
        RunInputToolArgument(name="start", field_name="start", field_label="First day"),
    )
    assert refused.question_id == f"tool_argument:rows:{ROWS_REF}:limit"


def test_a_tool_whose_schema_was_not_in_view_is_confirmed_then_shown_whole() -> None:
    # Kills: a use the planner wrote without the tool's schema in view built
    # unasked, the decided block without the chosen tool's whole schema or
    # with it once per use, a schema too large to show sent to the planner
    # instead of answered, chosen tools whose schemas together do not fit
    # built with one unseen, a schema the listing shows repeated with the
    # decisions.
    use = _use("rows", ROWS_REF, _argument("limit", "fixed", value_json="5"))
    huge = _option(
        ROWS_TOOL,
        "rows",
        {
            "type": "object",
            "properties": {"q": {"type": "string", "description": "x" * 13_000}},
        },
    )
    decided = ToolDecisions(
        uses={f"rows{n}": ToolUseDecision(tool_ref=ROWS_REF) for n in range(12)}
    )
    wide = _option(
        VALUES.tool_id,
        "values_by_day",
        {
            "type": "object",
            "properties": {"q": {"type": "string", "description": "y" * 11_900}},
        },
    )
    both = ToolDecisions(
        uses={
            "rows0": ToolUseDecision(tool_ref=ROWS_REF),
            "wide": ToolUseDecision(tool_ref=VALUES_REF),
        }
    )

    asked = _asked(
        _settle(
            _site(use.model_copy(update={"use_ref": "rows0"})), projection_left_out=True
        )
    )
    confirmed = _settle(
        _site(use.model_copy(update={"use_ref": "rows0"})),
        decisions=decided,
        projection_left_out=True,
    )
    block = render_tool_decisions_block(
        decided, catalog=_catalog(ROWS).tools, listing=AIBuilderToolCatalogLeftOut()
    )
    listed_block = render_tool_decisions_block(
        decided, catalog=_catalog(ROWS).tools, listing=_catalog(ROWS).tools.projection
    )
    too_large = _settle(_site(use), tools=(huge,))
    unseen = _settle(
        _site(use.model_copy(update={"use_ref": "rows0"})),
        decisions=both,
        tools=(wide, ROWS),
        projection_left_out=True,
    )

    assert asked.question_id == "tool_choice:rows0"
    assert isinstance(confirmed, SettledToolUses)
    assert block.count('"maximum":10') == 1 and '"enum":["hour","day"]' in block
    assert '"maximum":10' not in listed_block
    assert isinstance(too_large, ProposalAnswer)
    assert too_large.tool_refusal == AIBuilderToolRefusal(
        tool_name="rows", server_name="Data", kind="input_schema_too_large"
    )
    assert isinstance(unseen, ProposalAnswer) and unseen.tool_refusal is not None
    assert unseen.tool_refusal.tool_name == "rows"


def test_twelve_uses_of_one_tool_fit_a_small_window() -> None:
    # Kills: a chosen tool's schema repeated per use in the prompt, which
    # refuses the turn for budget.
    big = _option(
        ROWS_TOOL,
        "rows",
        {
            "type": "object",
            "properties": {
                f"p{n}": {"type": "string", "description": "word " * 22}
                for n in range(100)
            },
        },
    )
    conversation = conversation_using_tools({f"u{n}": ROWS_REF for n in range(12)})

    prepared = build_proposal_prepared(
        requirements_state=RequirementsState(),
        ui_language="en",
        slot_classification_metadata=None,
        conversation=conversation,
        planning_state=PlanningState.empty(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=_catalog(big),
        flow=None,
        assistant_snapshots=None,
        plan_edit_context=None,
        prior_plan_for_revision=None,
        litellm_model="gpt-4o-mini",
        capacity=ModelCapacity(32_000, 1024),
        budget_policy=_budget_policy(),
        attachment_file_count=0,
        current_turn_start=0,
    )

    assert isinstance(prepared, ProposalPrepared)


def test_a_decided_value_that_no_longer_fits_is_asked_again() -> None:
    # Kills: a decided run-form field, earlier step's field or allowed value
    # put back without a check (the model's repair overwritten every round),
    # a re-asked run-form option that clashes again, an edit's argument
    # adding a run-form field.
    def decided(**arguments: Any) -> ToolDecisions:
        return ToolDecisions(
            uses={
                "rows": ToolUseDecision(
                    tool_ref=ROWS_REF, arguments_for=ROWS_REF, arguments=arguments
                )
            }
        )

    text_start = RunForm(
        fields=(FormFieldSpec(name="start", type="text", label="Start"),),
        adds_fields=True,
    )
    start = _site(_use("rows", ROWS_REF, _argument("start", "ask_user")))

    clash = _asked(
        _settle(
            start,
            decisions=decided(
                start=RunInputToolArgument(name="start", field_name="start")
            ),
            run_form=text_start,
        )
    )
    gone = _asked(
        _settle(
            start,
            decisions=decided(
                start=EarlierStepToolArgument(
                    name="start", from_step=1, field_path="first_day"
                )
            ),
        )
    )
    outside = _asked(
        _settle(
            _site(_use("rows", ROWS_REF, _argument("unit", "ask_user"))),
            decisions=decided(unit=FixedToolArgument(name="unit", value="week")),
        )
    )
    edit = _asked(
        _settle(
            start,
            decisions=decided(
                start=RunInputToolArgument(name="start", field_name="start")
            ),
            run_form=RunForm(fields=(), adds_fields=False),
        )
    )

    assert clash.question_id == f"tool_argument:rows:{ROWS_REF}:start"
    assert [option.id for option in clash.options] == ["fixed", "run_input:start_2"]
    assert gone.question_id == f"tool_argument:rows:{ROWS_REF}:start"
    assert outside.question_id == f"tool_argument:rows:{ROWS_REF}:unit"
    assert [option.id for option in edit.options] == ["fixed"]


def _edit_outcome(
    entry: dict[str, Any],
    decisions: ToolDecisions,
    *,
    tools: tuple[FlowToolOption, ...] = (VALUES, DETAILS),
    confirmed: tuple[ConfirmedRuntimeMetadataField, ...] = (),
) -> Any:
    flow = _saved_flow()
    state = PlanningState.empty()
    state.tool_decisions = decisions
    state.input_fields = list(confirmed)
    return asyncio.run(
        process_edit_arguments(
            turn=_make_turn(),
            conversation=[ConversationMessage(role="user", content="Hämta igen.")],
            arguments={
                "plan_rationale": "Edit.",
                "steps": [
                    entry
                    if entry.get("existing_step_ref") == "existing_step_1"
                    else {"kind": "keep", "existing_step_ref": "existing_step_1"},
                    {"kind": "keep", "existing_step_ref": "existing_step_2"},
                    *([entry] if entry["kind"] == "add" else []),
                    {"kind": "keep", "existing_step_ref": "existing_step_3"},
                ],
            },
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots={
                step.assistant_id: AssistantAuthoringSnapshot(instructions="Gör.")
                for step in flow.steps
            },
            resource_catalog=_catalog(*tools),
            planning_state=state,
        )
    )


def test_an_edit_asks_before_each_new_use_of_a_tool() -> None:
    # Kills: a new use in an edit built unasked, a saved step's own tool
    # asked about again.
    added = {
        "kind": "add",
        "step": {
            "name": "Fler detaljer",
            "instructions": "Hämta detaljer igen.",
            "tool_use": {
                "use_ref": "again",
                "tool_ref": DETAILS_REF,
                "arguments": [
                    _argument("days", "earlier_step", from_step=1, field_path="days")
                ],
            },
        },
    }
    own = {
        "kind": "modify",
        "existing_step_ref": "existing_step_1",
        "tool_use": {
            "use_ref": "values",
            "tool_ref": VALUES_REF,
            "arguments": [
                _argument("from_date", "fixed", value_json='"2026-10-01"'),
                _argument("to_date", "fixed", value_json='"2026-10-31"'),
            ],
        },
    }

    asked = _edit_outcome(added, ToolDecisions())
    confirmed = _edit_outcome(
        added, ToolDecisions(uses={"again": ToolUseDecision(tool_ref=DETAILS_REF)})
    )
    kept_tool = _edit_outcome(own, ToolDecisions())

    assert _asked(asked).question_id == "tool_choice:again"
    assert isinstance(confirmed, ProposalReady)
    assert isinstance(kept_tool, ProposalReady)


def test_a_tool_refusal_reaches_the_web_typed() -> None:
    # Kills: the refusal left out of the answer, of the text event, of the
    # stored message or of the message API that a reloaded session reads; a
    # stored refusal that no longer reads whole shown instead of dropped.
    answer = tool_not_usable_answer(
        "archive",
        "Data",
        reason=UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE,
        ui_language="en",
    )
    repo = SimpleNamespace(
        commit_turn=AsyncMock(return_value=1),
        restore_awaiting_approval_after_answered_turn=AsyncMock(),
    )
    conversation: list[ConversationMessage] = []

    (event,) = asyncio.run(
        persist_non_plan_turn(
            repo=cast(Any, repo),
            turn=_make_turn(),
            conversation=conversation,
            new_messages_start=0,
            message=answer.answer,
            base_assistant_metadata=None,
            usage_tracker=None,
            planning_state=PlanningState.empty(),
            flow=None,
            outcome=answer.outcome,
            tool_refusal=answer.tool_refusal,
        )
    )

    refusal = AIBuilderToolRefusal(
        tool_name="archive",
        server_name="Data",
        kind="refused",
        refusal=UnattendedToolRefusal.TOOL_SWITCHED_OFF_IN_SPACE,
    )
    assert answer.tool_refusal == refusal
    assert isinstance(event, AIBuilderTextEvent) and event.data.tool_refusal == refusal
    (public,) = _to_public_conversation(conversation)
    assert public.tool_refusal == refusal
    metadata = cast(dict[str, Any], conversation[0].metadata)
    metadata["non_plan_outcome"]["tool_refusal"]["kind"] = "renamed"
    (garbled,) = _to_public_conversation(conversation)
    assert garbled.tool_refusal is None

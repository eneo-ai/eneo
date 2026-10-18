"""A saved flow whose steps read no run input needs no run-input answer.

The run input is what a run is started with: the run text or payload, a form
field, a step's own upload. A tool step's input type is the type of the tool's
answer, not of the run input.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from eneo.flows.ai_builder.ai_builder_action_policy import build_planner_action_policy
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_commit_invariance import (
    architecture_commit_draft_matches_pinned,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    StructuredQuestionAnswerRequest,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    CreateCompileContext,
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_discovery import (
    analyze_discovery,
    build_registry_question_followup,
)
from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    FlowWithStepPrompts,
    build_flow_capability_profile,
    build_flow_discovery_defaults,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_edit_scope import resolve_edit_scope
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_plan_proposal_task import (
    build_plan_proposal_system_prompt,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.ai_builder_server_decision_dispatch import situate_question
from eneo.flows.ai_builder.ai_builder_slot_vocabulary import NO_RUN_INPUT
from eneo.flows.ai_builder.ai_builder_tool_questions import tool_relevance_question
from eneo.flows.ai_builder.ai_builder_user_question_metadata import (
    prepare_user_question_metadata,
)
from eneo.flows.ai_builder.planning_state import ConfirmedRuntimeMetadataField
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    llm_resolvable_slot_values_for_state,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import Flow
from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_authoring_spec import InputSource, InputType
from tests.unittests.flows.ai_builder.test_ai_builder_action_policy import (
    _slot as _policy_slot,
)
from tests.unittests.flows.ai_builder.test_ai_builder_action_policy import (
    _template_file_role,
)
from tests.unittests.flows.ai_builder.test_ai_builder_saved_tool_steps import (
    _seab,
    _tool,
)
from tests.unittests.flows.ai_builder.test_ai_builder_tool_questions import (
    _answer,
    _show,
    _shown_by_hand,
)
from tests.unittests.flows.ai_builder.test_ai_builder_tool_steps import (
    DEPARTMENT,
    DETAILS,
    VALUES,
    VALUES_REF,
    _catalog,
    _step_payload,
    _two_tool_flow,
)
from tests.unittests.flows.ai_builder.test_ai_builder_unsupported_saved_steps import (
    _flow,
    _step,
)


def _read(flow: Flow, **prompts: str) -> FlowWithStepPrompts:
    """The flow as a Builder turn reads it: each step's prompt beside it
    (`step_3="..."`), "Gör det." where none is given."""

    return FlowWithStepPrompts.of(
        flow,
        {
            step.assistant_id: AssistantAuthoringSnapshot(
                instructions=prompts.get(f"step_{step.step_order}", "Gör det.")
            )
            for step in flow.steps
        },
    )


def _seab_with(order: int, **overrides: object) -> Flow:
    flow = _seab()
    steps = list(flow.steps)
    steps[order - 1] = steps[order - 1].model_copy(update=overrides)
    return flow.model_copy(update={"steps": steps})


_UPLOAD = {"enabled": True, "required": True, "input_format": "document"}
_FORM = {"form_schema": {"fields": [{"name": "period", "type": "text"}]}}
_TOOL_READS_RUN_TEXT = _read(
    _flow(_tool(1, {"from": "{{flow_input.text}}"}), _step(2, input_type="json"))
)
_TOOL_READS_PERIOD = _seab(_tool(1, {"from": "{{flow_input.period}}"}, "anomaly_days"))
_TOOL_READS_FORM_FIELD = _read(
    _TOOL_READS_PERIOD.model_copy(update={"metadata_json": _FORM})
)
_TOOL_FILLS_TEMPLATE = _read(
    _flow(
        _tool(1, {"from": "2026-09-01"}),
        _step(
            2,
            output_type="docx",
            output_mode="template_fill",
            output_config={
                "template_asset_id": str(UUID(int=7)),
                "bindings": {"summary": "{{step_1.output.text}}"},
            },
        ),
    )
)


@pytest.mark.parametrize(
    ("flow", "run_input"),
    [
        pytest.param(_read(_seab()), {"no_run_input"}, id="steps-read-tools-and-steps"),
        pytest.param(
            _read(_seab(), step_3="Jämför med {{flow_input.text}}."),
            None,
            id="prompt-reads-run-text",
        ),
        pytest.param(_seab(), None, id="prompts-unknown"),
        pytest.param(FlowWithStepPrompts.of(_seab(), {}), None, id="prompts-missing"),
        pytest.param(_TOOL_READS_RUN_TEXT, None, id="tool-argument-reads-run-text"),
        pytest.param(
            _read(
                _seab_with(3, input_bindings={"question": "Jämför med {{flow_input}}."})
            ),
            None,
            id="question-reads-run-input",
        ),
        *(
            pytest.param(
                _read(
                    _seab_with(
                        3, input_bindings={"question": f"{{{{flow_input{gap}}}}}"}
                    )
                ),
                None,
                id=f"question-reads-run-input-before-a-{name}",
            )
            for name, gap in (("newline", "\n"), ("tab", "\t"))
        ),
        pytest.param(
            _read(
                _seab_with(
                    3, input_bindings={"question": "Jämför med {{indata_text}}."}
                )
            ),
            None,
            id="question-reads-run-text-alias",
        ),
        pytest.param(
            _read(_seab_with(4, input_config={"runtime_input": _UPLOAD})),
            None,
            id="step-takes-an-upload",
        ),
        pytest.param(
            _read(
                _seab_with(2, input_source=FlowInputSource.HTTP_GET, input_config=None)
            ),
            None,
            id="step-fetches-over-http",
        ),
        pytest.param(
            _read(_seab_with(4, output_mode=FlowOutputMode.HTTP_POST)),
            None,
            id="step-sends-over-http",
        ),
        pytest.param(
            _read(_flow(_tool(1, {"days": "dag {{step_1.output.text}}"}), _step(2))),
            None,
            id="tool-config-cannot-be-read",
        ),
        pytest.param(
            _read(_seab().model_copy(update={"metadata_json": _FORM})),
            {"no_run_input"},
            id="run-form-has-fields",
        ),
        pytest.param(
            _TOOL_READS_FORM_FIELD,
            {"no_run_input"},
            id="tool-argument-reads-a-form-field",
        ),
        pytest.param(
            _read(_TOOL_READS_PERIOD),
            None,
            id="tool-argument-reads-an-undeclared-field",
        ),
        pytest.param(
            _read(_seab(_step(1, input_type="text"))),
            {"text"},
            id="step-reads-run-text",
        ),
    ],
)
def test_the_flow_reads_no_run_input_only_when_no_step_reads_any(
    flow: Flow, run_input: set[str] | None
) -> None:
    # Kills: a derivation from input sources alone; prompts, tool arguments,
    # run-input payload or alias reads, or step uploads left unread; a decision
    # without the prompts; a flow with form fields never decided, or its
    # declared fields left out so a read of one counts as a run-input read; a
    # read of an undeclared run-input key taken for a form field; a flow with
    # steps the Builder cannot carry decided (or raising); an unreadable
    # configuration read as reading nothing; the tool answer's type taken for
    # the run input.
    assert build_flow_discovery_defaults(flow).get("primary_runtime_input") == run_input


@pytest.mark.parametrize(
    ("flow", "allowed", "asked"),
    [
        (_read(_seab()), ("commit_architecture",), ()),
        (_TOOL_READS_FORM_FIELD, ("commit_architecture",), ()),
        (_TOOL_FILLS_TEMPLATE, ("commit_architecture",), ()),
        (_TOOL_READS_RUN_TEXT, ("ask_question",), ("primary_runtime_input",)),
    ],
)
def test_an_edit_asks_for_the_run_input_only_when_a_step_reads_it(
    flow: Flow, allowed: tuple[str, ...], asked: tuple[str, ...]
) -> None:
    # Kills: the edit's core slots still demanding a run input a flow does not
    # read; a flow that reads one no longer asked; a saved tool flow that fills
    # a DOCX template refused by the create-only rule against that pair.
    state = build_planning_state_from_conversation(
        [ConversationMessage(role="user", content="Byt namn på rapportsteget.")],
        flow=flow,
    )
    policy = build_planner_action_policy(
        session_state=state, selected_discovery_question_ids=(), is_edit_mode=True
    )

    assert policy.allowed_action_kinds == allowed
    assert policy.allowed_ask_question_targets == asked


def test_an_architecture_without_run_input_compiles_and_reads_without_one() -> None:
    # Kills: the commit carrying no run-input fact, so the compile treats the
    # earlier steps' text as a run input to collect; the summary naming the
    # derived value instead of saying that the flow receives no input; an
    # edit's planner told that its first step reads a tool, which only the
    # create compile holds a plan to.
    state = build_planning_state_from_conversation(
        [ConversationMessage(role="user", content="Byt namn på rapportsteget.")],
        flow=_read(_seab()),
    )
    draft = derive_architecture_commit_draft(state)
    assert draft is not None and not draft.reads_run_input
    state.architecture_commit = finalize_architecture_commit(draft)

    context = create_compile_context_from_planning_state(state)

    assert context is not None and context.runtime_input_type is None
    assert draft.tuples_chain[0].input_type.value == InputType.TEXT.value
    summary = build_requirements_disclosure(state, ui_language="sv").summary
    assert summary.startswith(
        "Flödet tar emot inget material att ladda upp eller klistra in vid körning"
    )
    assert "No run input" not in build_plan_proposal_system_prompt(
        planning_state=state,
        confirmed_requirements=None,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=True,
        resource_catalog=_catalog(VALUES),
    )


def test_a_run_input_named_after_the_commit_is_a_drift_from_it() -> None:
    # Kills: the commit hash and comparison leaving out the run-input fact, so a
    # later answer naming a run text keeps the commit without one.
    state = build_planning_state_from_conversation([], flow=_read(_seab()))
    pinned = derive_architecture_commit_draft(state)
    state.resolved_slots["primary_runtime_input"] = state.resolved_slots[
        "primary_runtime_input"
    ].model_copy(update={"value": "text"})

    assert pinned is not None
    assert not architecture_commit_draft_matches_pinned(
        before=finalize_architecture_commit(pinned),
        after=derive_architecture_commit_draft(state),
    )


def test_an_edit_naming_a_material_still_opens_the_run_input() -> None:
    # Kills: a flow without run input taken as settled, so asking it to take
    # JSON is not read as an input change.
    scope = resolve_edit_scope(
        edit_mode=True,
        capabilities=build_flow_capability_profile(_read(_seab())),
        active_request_text="Ta emot JSON",
        active_answer_signals={},
    )

    assert "input_shape" in scope.active_families


def _conversation(*relevance: str) -> list[ConversationMessage]:
    """A create conversation whose person answered the tool question with
    each of `relevance` in turn."""
    conversation = [ConversationMessage(role="user", content="Hämta värden.")]
    _answer_tools(conversation, *relevance)
    return conversation


def _answer_tools(conversation: list[ConversationMessage], *answers: str) -> None:
    """Answer the tool question with each of `answers`; `no_tool` and `tool`
    answer which tool the planner's use `values` reads instead."""
    for answer in answers:
        if answer in ("no_tool", "tool"):
            option = "no_tool" if answer == "no_tool" else VALUES_REF
            shown = _shown_by_hand(conversation, "tool_choice:values", option)
            _answer(conversation, shown, option)
            continue
        tools = _catalog(VALUES).tools
        question = tool_relevance_question(tools, ui_language="sv", show_tools=False)
        _answer(conversation, _show(conversation, question), answer)


def _answer_slots(conversation: list[ConversationMessage], *slots: str) -> None:
    """Answer the run-input question with no_run_input, then each further
    slot (terminal_output) with a structured text result."""
    for slot in ("primary_runtime_input", *slots):
        value = NO_RUN_INPUT if slot == "primary_runtime_input" else "structured_text"
        _answer(conversation, _show(conversation, _question(conversation, slot)), value)


def _question(conversation: list[ConversationMessage], slot: str, **context: Any):
    question = build_registry_question_followup(slot, conversation, **context)
    assert question is not None
    return question


def _situated(conversation: list[ConversationMessage], **context: Any):
    return situate_question(
        _question(conversation, "primary_runtime_input", **context).question_data,
        conversation=conversation,
        planned_remaining=None,
        locale="sv",
        **context,
    )


@pytest.mark.parametrize(
    ("relevance", "flow", "offered"),
    [(("use",), None, True), (("dont_use",), None, False), ((), None, False)]
    + [(("use", "show_tools"), None, True), (("use", "no_tool"), None, False)]
    + [(("use", "no_tool", "tool"), None, True), (("use",), _read(_seab()), False)],
)
def test_the_question_offers_no_input_only_in_a_create_session_using_tools(
    relevance: tuple[str, ...], flow: Flow | None, offered: bool
) -> None:
    # Kills: the option shown whatever the person answered, after "build
    # without tools" or before any answer, or while editing a saved flow; a
    # later "show the tools" taken for a no; a no-tool answer for every use
    # the person decided ignored, or one they changed back still counted.
    shown = _situated(_conversation(*relevance), flow=flow)

    assert (NO_RUN_INPUT in {option.value for option in shown.options}) is offered


@pytest.mark.parametrize(
    ("later", "kept"),
    [(("dont_use",), False), (("dont_use", "use"), True), (("no_tool",), False)],
)
def test_a_no_input_answer_counts_only_while_the_tools_are_used(
    later: tuple[str, ...], kept: bool
) -> None:
    # Kills: a stored no_run_input answer kept after the person declines the
    # tools or every tool use, so the committed flow without input is planned
    # again and every plan is sent back; the answer dropped although they
    # said use again.
    conversation = _conversation("use")
    _answer_slots(conversation, "terminal_output")
    pinned = derive_architecture_commit_draft(
        build_planning_state_from_conversation(conversation)
    )
    assert pinned is not None
    _answer_tools(conversation, *later)

    state = build_planning_state_from_conversation(conversation)
    state.architecture_commit = finalize_architecture_commit(pinned)
    policy = build_planner_action_policy(
        session_state=state,
        selected_discovery_question_ids=analyze_discovery(
            conversation, planning_state=state
        ).selected_question_ids,
        requirements_confirmed=True,
        is_edit_mode=False,
    )

    assert (
        state.commit_grade_slot_value("primary_runtime_input") == NO_RUN_INPUT
    ) is kept
    assert ("primary_runtime_input" in policy.allowed_ask_question_targets) is not kept
    assert "propose_plan" not in policy.allowed_action_kinds or kept


@pytest.mark.parametrize(
    ("relevance", "is_edit_mode", "accepted"),
    [("use", False, True), ("dont_use", False, False), ("use", True, False)],
)
def test_a_no_input_answer_is_taken_only_where_the_question_offers_it(
    relevance: str, is_edit_mode: bool, accepted: bool
) -> None:
    # Kills: a no_run_input answer accepted by vocabulary alone, after "build
    # without tools", or in an edit; a create session that uses tools refused.
    conversation = _conversation(relevance)
    shown = _show(conversation, _question(conversation, "primary_runtime_input"))
    answer = StructuredQuestionAnswerRequest(
        question_id=shown.question_id,
        instance_token=shown.instance_token,
        selected_option_ids=[NO_RUN_INPUT],
    )

    def prepare() -> object:
        return prepare_user_question_metadata(
            conversation=conversation,
            message="",
            question_answer=answer,
            is_edit_mode=is_edit_mode,
        )

    if accepted:
        prepare()
        return
    with pytest.raises(AIBuilderBadRequestException) as refused:
        prepare()
    assert refused.value.context == {"reason": "unsupported_question_value"}


def test_a_create_session_without_run_input_compiles_a_tool_first_plan() -> None:
    # Kills: the classifier offered no_run_input, so a request's words could
    # settle it without the person's answer; the answer not reaching the
    # commit (a run input still collected); the canonical input projection
    # refusing the value; a main-text field added to the run form, or a form
    # field read counted as a run-input read; the final spec not checked
    # against the commit, so a first step reading the run text compiles; the
    # summary naming a material; the planner not told that the first step
    # reads a tool or fixed values.
    conversation = _conversation("use")
    offered = llm_resolvable_slot_values_for_state(
        build_planning_state_from_conversation(conversation)
    )
    assert NO_RUN_INPUT not in offered["primary_runtime_input"]
    _answer_slots(conversation, "terminal_output")
    state = build_planning_state_from_conversation(conversation)
    draft = derive_architecture_commit_draft(state)
    assert draft is not None and not draft.reads_run_input
    state.architecture_commit = finalize_architecture_commit(draft)
    context = create_compile_context_from_planning_state(state)
    catalog = _catalog(VALUES, DETAILS)

    spec = compile_create_intent_to_spec(
        parse_create_flow_intent_arguments(_two_tool_flow()),
        context=context,
        tool_catalog=catalog.tools,
    )

    assert spec.steps[0].input_source is InputSource.TOOL
    assert [field.name for field in spec.form_fields or ()] == ["from_date", "to_date"]
    with pytest.raises(AIBuilderArchitectureError) as raised:
        compile_create_intent_to_spec(
            parse_create_flow_intent_arguments(
                {**_two_tool_flow(), "steps": [_step_payload("Skriv", None)]}
            ),
            context=context,
        )
    assert raised.value.repair_disposition == "model_correctable"
    assert raised.value.failure_code == "run_input_read_without_run_input"
    summary = build_requirements_disclosure(state, ui_language="sv").summary
    assert summary.startswith(
        "Flödet tar emot inget material att ladda upp eller klistra in vid körning"
    )
    assert "the first step reads an MCP tool" in (
        build_plan_proposal_system_prompt(
            planning_state=state,
            confirmed_requirements=None,
            attachment_context=None,
            flow_context=None,
            is_edit_mode=False,
            resource_catalog=catalog,
        )
    )


@pytest.mark.parametrize("confirmed", [(), (DEPARTMENT,)])
def test_a_first_step_that_reads_no_tool_is_sent_back_by_name(
    confirmed: tuple[ConfirmedRuntimeMetadataField, ...],
) -> None:
    # Kills: a first step without a tool accepted because it reads only run
    # form fields (among them the main-text field the compiler declares beside
    # confirmed ones); a repair that names neither the step nor the fix.
    with pytest.raises(AIBuilderArchitectureError) as raised:
        compile_create_intent_to_spec(
            parse_create_flow_intent_arguments(
                {**_two_tool_flow(), "steps": [_step_payload("Skriv", None)]}
            ),
            context=CreateCompileContext(
                reads_run_input=False, runtime_input_fields=confirmed
            ),
        )

    assert raised.value.failure_code == "run_input_read_without_run_input"
    assert "step 1 'Skriv'" in raised.value.detail
    assert "start with a step that reads an MCP tool" in raised.value.detail


@pytest.mark.parametrize("material", [NO_RUN_INPUT, "text"])
def test_a_template_filled_document_without_run_input_is_refused_before_planning(
    material: str,
) -> None:
    # Kills: the architecture committed although no plan can both fill a DOCX
    # template (which takes no tool step) and start with a step that reads a
    # tool, so every proposal is sent back with contradicting repairs.
    state = build_planning_state_from_conversation(_conversation("use"))
    for slot, value in (
        ("primary_runtime_input", material),
        ("terminal_output", "docx_document"),
        ("docx_output_mode", "template_fill_docx"),
    ):
        state.resolved_slots[slot] = _policy_slot(slot, value)
    state.file_roles = [_template_file_role(placeholders=["namn"])]

    policy = build_planner_action_policy(
        session_state=state, selected_discovery_question_ids=()
    )

    refused = material == NO_RUN_INPUT
    assert ("refuse_architecture_commit" in policy.allowed_action_kinds) is refused
    assert (
        policy.architecture_refusal_code is AIBuilderErrorCode.UNSUPPORTED_ARCHITECTURE
    ) is refused

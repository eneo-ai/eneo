"""A saved flow whose steps read no run input needs no run-input answer.

The run input is what a run is started with: the run text or payload, a form
field, a step's own upload. A tool step's input type is the type of the tool's
answer, not of the run input.
"""

from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_action_policy import build_planner_action_policy
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_commit_invariance import (
    architecture_commit_draft_matches_pinned,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_discovery_flow_defaults import (
    FlowWithStepPrompts,
    build_flow_capability_profile,
    build_flow_discovery_defaults,
)
from eneo.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from eneo.flows.ai_builder.ai_builder_edit_scope import resolve_edit_scope
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import Flow
from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_authoring_spec import InputType
from tests.unittests.flows.ai_builder.test_ai_builder_saved_tool_steps import (
    _seab,
    _tool,
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
            None,
            id="run-form-has-fields",
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
    # without the prompts; declared form fields left out; a flow with steps the
    # Builder cannot carry decided (or raising); an unreadable configuration
    # read as reading nothing; the tool answer's type taken for the run input.
    assert build_flow_discovery_defaults(flow).get("primary_runtime_input") == run_input


@pytest.mark.parametrize(
    ("flow", "allowed", "asked"),
    [
        (_read(_seab()), ("commit_architecture",), ()),
        (_TOOL_READS_RUN_TEXT, ("ask_question",), ("primary_runtime_input",)),
    ],
)
def test_an_edit_asks_for_the_run_input_only_when_a_step_reads_it(
    flow: Flow, allowed: tuple[str, ...], asked: tuple[str, ...]
) -> None:
    # Kills: the edit's core slots still demanding a run input a flow does not
    # read; a flow that reads one no longer asked.
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
    # derived value instead of saying that the flow receives no input.
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
    assert summary.startswith("Flödet tar emot ingen indata vid körning")


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

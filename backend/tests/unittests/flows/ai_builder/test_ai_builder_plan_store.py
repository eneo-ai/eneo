from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_create_outline import OUTLINE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_domain_models import LintSeverity, LintWarning
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    ConversationMessage,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    PlannerPlanEnvelope,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_plan_store import (
    _persist_active_send_plan_proposal,
    append_plan_messages,
    build_lint_warnings,
    format_validation_feedback,
    store_plan_and_update_conversation,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_validation_common import (
    SpecValidationError,
    SpecValidationResult,
)
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)


def test_build_lint_warnings_hides_internal_info_level_quality_lints() -> None:
    validation = SpecValidationResult()
    validation.warnings.extend(
        [
            LintWarning(
                step_ref="step_d",
                code="json_output_text_interpolation",
                message=(
                    "Underlag interpolates output.text from a JSON-producing step. "
                    "Prefer output.structured.<field> when only specific fields are needed."
                ),
                severity=LintSeverity.INFO,
            ),
            LintWarning(
                step_ref="step_e",
                code="all_previous_overuse",
                message="Too many steps use all_previous_steps.",
                severity=LintSeverity.WARNING,
            ),
        ]
    )

    visible_warnings = build_lint_warnings(validation)

    assert visible_warnings == [
        LintWarning(
            step_ref="step_e",
            code="all_previous_overuse",
            message="Too many steps use all_previous_steps.",
            severity=LintSeverity.WARNING,
        )
    ]


def test_append_plan_messages_uses_active_submission_tool_name() -> None:
    conversation: list[ConversationMessage] = []
    spec = FlowDraftSpecCore(
        flow_name="Kommunärende",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extrahera",
                assistant_spec=AssistantSpec(instructions="Extrahera."),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )

    append_plan_messages(
        conversation=conversation,
        assistant_content="Här är planen.",
        tool_call_id="call_create",
        tool_name=OUTLINE_FLOW_TOOL_NAME,
        arguments={"plan_rationale": "Struktur först."},
        spec=spec,
        assumptions=["Antagande"],
    )

    assert conversation[0].tool_calls is not None
    assert conversation[0].tool_calls[0]["name"] == OUTLINE_FLOW_TOOL_NAME


def test_format_validation_feedback_does_not_add_step_ref_guidance_for_runtime_alias_error() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Unit plan",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract",
                assistant_spec=AssistantSpec(instructions="Extract."),
                input_source=InputSource.FLOW_INPUT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Summarize",
                assistant_spec=AssistantSpec(instructions="Summarize."),
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    feedback = format_validation_feedback(
        spec=spec,
        errors=[
            SpecValidationError(
                step_ref="step_a",
                code="flow_step_invalid",
                message="Invalid step reference 'step_a' in input bindings.",
            )
        ],
    )

    assert "Invalid step reference 'step_a' in input bindings." in feedback
    assert "Declared step refs in this draft: step_a, step_b" not in feedback


def test_format_validation_feedback_keeps_undeclared_step_ref_visible() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Unit plan",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract",
                assistant_spec=AssistantSpec(instructions="Extract."),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )

    feedback = format_validation_feedback(
        spec=spec,
        errors=[
            SpecValidationError(
                step_ref="step_a",
                code="invalid_runtime_variable_path",
                message="Invalid step reference 'step_z' in template expression.",
            )
        ],
    )

    assert "Invalid step reference 'step_z' in template expression." in feedback
    assert "Declared step refs in this draft: step_a" not in feedback


@asynccontextmanager
async def _noop_savepoint() -> AsyncIterator[None]:
    yield


def _make_repo_mock() -> AsyncMock:
    repo = AsyncMock()
    repo.savepoint = _noop_savepoint
    repo.append_session_messages = AsyncMock(return_value=[])
    repo.create_plan = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    repo.load_planning_state = AsyncMock(return_value=None)
    return repo


def _make_turn_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Unit plan",
        flow_description="Unit plan description",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref=None,
                name="Step A",
                assistant_spec=AssistantSpec(instructions="Do work."),
                mcp_policy=MCPPolicy.INHERIT,
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            )
        ],
    )


def _make_binding() -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=uuid4(),
    )


def _make_turn(
    *,
    tenant_id=None,
    session_id=None,
    base_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_version,
    )


@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_saves_planning_state_inside_savepoint() -> (
    None
):
    repo = _make_repo_mock()
    spec = _make_turn_spec()

    await store_plan_and_update_conversation(
        repo=repo,
        turn=_make_turn(base_version=7),
        conversation=[],
        new_messages_start=0,
        assistant_content="plan ready",
        tool_call_id="call-unit-1",
        tool_name=OUTLINE_FLOW_TOOL_NAME,
        arguments={},
        spec=spec,
        assumptions=[],
        plan_rationale=None,
        reasoning=None,
        validation=SpecValidationResult(),
    )

    repo.save_planning_state.assert_awaited_once()
    assert repo.save_planning_state.await_args is not None
    saved_state = repo.save_planning_state.await_args.kwargs["state"]
    assert isinstance(saved_state, PlanningState)
    assert saved_state.draft_plan_id == repo.create_plan.return_value.id
    assert saved_state.phase == "plan_proposed"
    assert repo.save_planning_state.await_args.kwargs["base_version"] == 7


@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_passes_resource_bindings_to_repo() -> (
    None
):
    repo = _make_repo_mock()
    binding = _make_binding()

    await store_plan_and_update_conversation(
        repo=repo,
        turn=_make_turn(),
        conversation=[],
        new_messages_start=0,
        assistant_content="plan ready",
        tool_call_id="call-unit-1",
        tool_name=OUTLINE_FLOW_TOOL_NAME,
        arguments={},
        spec=_make_turn_spec(),
        assumptions=[],
        plan_rationale=None,
        reasoning=None,
        validation=SpecValidationResult(),
        resource_bindings=(binding,),
    )

    assert repo.create_plan.await_args is not None
    assert repo.create_plan.await_args.kwargs["resource_bindings"] == (binding,)


@pytest.mark.asyncio
async def test_active_send_plan_proposal_uses_only_bindings_for_current_plan() -> None:
    repo = _make_repo_mock()
    tenant_id = uuid4()
    session_id = uuid4()
    first_binding = _make_binding()
    second_binding = _make_binding()
    spec = _make_turn_spec()

    await _persist_active_send_plan_proposal(
        repo=repo,
        turn=_make_turn(tenant_id=tenant_id, session_id=session_id),
        spec=spec,
        envelope=PlannerPlanEnvelope(spec=spec),
        resource_bindings=(first_binding,),
    )
    await _persist_active_send_plan_proposal(
        repo=repo,
        turn=_make_turn(tenant_id=tenant_id, session_id=session_id),
        spec=spec,
        envelope=PlannerPlanEnvelope(spec=spec),
        resource_bindings=(second_binding,),
    )

    first_call, second_call = repo.create_plan.await_args_list
    assert first_call.kwargs["resource_bindings"] == (first_binding,)
    assert second_call.kwargs["resource_bindings"] == (second_binding,)
    assert first_binding not in second_call.kwargs["resource_bindings"]
    assert repo.supersede_existing_plans.await_count == 2

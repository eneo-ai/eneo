from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_backend_question_persistence import (
    BackendQuestionPersistenceResult,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    FlowBuilderEditApproval,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_edit_preview_models import (
    EditAdvisory,
    FlowEditDiff,
    StepChange,
)
from intric.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizationRequest,
    CompiledProposalFinalizer,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ToolProcessingResult,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)


def _make_turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=0,
    )


def _make_flow_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Grounded flow",
        flow_description="Desc",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Analys",
                assistant_spec=AssistantSpec(
                    instructions="Gör analysen.",
                    model_ref=None,
                    knowledge_refs=[],
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            )
        ],
    )


def _compiled_outline_proposal() -> CompiledProposal:
    return CompiledProposal(
        spec=_make_flow_spec(),
        assumptions=(),
        plan_rationale="Classify incoming text.",
        reasoning=None,
        validation=SpecValidationResult(),
    )


def _compiled_outline_proposal_with_validation(
    validation: SpecValidationResult,
) -> CompiledProposal:
    compiled = _compiled_outline_proposal()
    return CompiledProposal(
        spec=compiled.spec,
        assumptions=compiled.assumptions,
        plan_rationale=compiled.plan_rationale,
        reasoning=compiled.reasoning,
        validation=validation,
        resource_bindings=compiled.resource_bindings,
        edit=compiled.edit,
        aggregation_intent=compiled.aggregation_intent,
    )


def _compiled_edit_proposal(*, compiled_spec: FlowDraftSpecCore) -> CompiledProposal:
    edit = FlowBuilderEditApproval(
        diff=FlowEditDiff(
            step_changes=[StepChange(kind="unchanged", step_name="Analys")]
        ),
        base_flow_revision=3,
        advisories=[
            EditAdvisory(
                code="flow_description_update_required",
                message="The flow description should be refreshed.",
                severity="warning",
                field="flow_description",
            )
        ],
    )
    return CompiledProposal(
        spec=compiled_spec,
        assumptions=(),
        plan_rationale="Update the flow.",
        reasoning=None,
        validation=SpecValidationResult(),
        edit=edit,
    )


def _stored_plan_result(*, plan=None, proposal=None):
    return SimpleNamespace(
        plan=plan or MagicMock(id=uuid4()),
        proposal=proposal
        or FlowBuilderProposal(
            content=FlowBuilderProposalContent(spec=_make_flow_spec())
        ),
        new_planning_state_version=1,
    )


async def _store_compiled_plan(**kwargs):
    return _stored_plan_result(
        proposal=FlowBuilderProposal(
            content=FlowBuilderProposalContent(spec=kwargs["compiled"].spec),
        ),
    )


def _make_finalizer(**overrides) -> CompiledProposalFinalizer:
    defaults = {
        "repo": AsyncMock(),
        "quality_retry_warning_codes": set(),
    }
    defaults.update(overrides)
    return CompiledProposalFinalizer(**defaults)


def _make_request(**overrides) -> CompiledProposalFinalizationRequest:
    defaults = {
        "turn": _make_turn(),
        "conversation": [],
        "new_messages_start": 0,
        "tool_name": PROPOSE_FLOW_TOOL_NAME,
        "target_kind": TargetKind.CREATE,
        "arguments": {"flow_name": "Test", "steps": []},
        "assistant_content": "Här är mitt förslag:",
        "assistant_metadata": None,
        "tool_call_id": "call-outline",
        "metadata_tool_call": MagicMock(),
        "compiled": _compiled_outline_proposal(),
        "resource_catalog": None,
        "flow": None,
        "request_id": "req-finalize",
        "usage_tracker": ProposalTurnTelemetry(
            request_id="req-finalize",
            model="openai/gpt-5.4",
            target_kind=TargetKind.CREATE,
        ),
    }
    defaults.update(overrides)
    return CompiledProposalFinalizationRequest(**defaults)


def test_finalization_request_is_frozen_without_retry_snapshot_payload() -> None:
    dataclass_params = CompiledProposalFinalizationRequest.__dataclass_params__

    assert dataclass_params.frozen is True
    assert (
        "assistant_snapshots" not in CompiledProposalFinalizationRequest.__annotations__
    )


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_records_success_once_when_persisted() -> None:
    finalizer = _make_finalizer()
    tracker = ProposalTurnTelemetry(
        request_id="req-success",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    captured_metadata: list[dict[str, object] | None] = []

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                request_id="req-success",
                usage_tracker=tracker,
            )
        )

    assert result.event is not None
    assert result.event["event"] == "plan"
    assert tracker.proposal_first_attempt_success is True
    assert tracker.proposal_first_attempt_tool == PROPOSE_FLOW_TOOL_NAME
    assert captured_metadata[0] is not None
    assert captured_metadata[0]["planner_telemetry"]["proposal_first_attempt_success"]


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_does_not_record_success_on_quality_reject() -> (
    None
):
    finalizer = _make_finalizer(quality_retry_warning_codes={"quality_issue"})
    validation = SpecValidationResult()
    validation.add_warning(
        step_ref="step_a",
        code="quality_issue",
        message="The plan should be improved before persistence.",
    )
    tracker = ProposalTurnTelemetry(
        request_id="req-quality",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    store_plan = AsyncMock(return_value=_stored_plan_result())

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                request_id="req-quality",
                usage_tracker=tracker,
                compiled=_compiled_outline_proposal_with_validation(validation),
            )
        )

    assert result.event is None
    assert result.failure_kind == "quality"
    assert tracker.proposal_first_attempt_success is None
    store_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_uses_target_kind_for_quality_branch() -> None:
    finalizer = _make_finalizer()
    create_quality = MagicMock(
        return_value=ToolProcessingResult(feedback="create", failure_kind="quality")
    )
    edit_quality = MagicMock(
        return_value=ToolProcessingResult(feedback="edit", failure_kind="quality")
    )

    with (
        patch.object(finalizer, "_create_quality_result", new=create_quality),
        patch.object(finalizer, "_edit_quality_result", new=edit_quality),
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                target_kind=TargetKind.EDIT,
                compiled=_compiled_edit_proposal(compiled_spec=_make_flow_spec()),
                flow=MagicMock(),
            )
        )

    assert result.feedback == "edit"
    create_quality.assert_not_called()
    edit_quality.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_accepts_retry_metadata_without_recorder() -> (
    None
):
    finalizer = _make_finalizer()
    tracker = ProposalTurnTelemetry(
        request_id="req-retry",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    retry_metadata = {"planner_telemetry": {"request_id": "req-retry"}}
    captured_metadata: list[dict[str, object] | None] = []

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                assistant_content="Här är mitt korrigerade förslag:",
                assistant_metadata=retry_metadata,
                metadata_tool_call=None,
                request_id="req-retry",
                usage_tracker=tracker,
            )
        )

    assert result.event is not None
    assert result.event["event"] == "plan"
    assert tracker.proposal_first_attempt_success is None
    assert captured_metadata == [retry_metadata]


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_allows_missing_usage_tracker() -> None:
    finalizer = _make_finalizer()
    captured_metadata: list[dict[str, object] | None] = []

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                assistant_metadata={"existing": True},
                usage_tracker=None,
            )
        )

    assert result.event is not None
    assert result.event["event"] == "plan"
    assert captured_metadata[0] == {"existing": True}


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_persists_mcp_clarification_without_plan() -> (
    None
):
    finalizer = _make_finalizer()
    issue = SimpleNamespace(
        step_ref="step_a",
        requested_name="case_lookup",
        reason="ambiguous",
        selected_server_refs={"server_a", "server_b"},
    )
    persist_backend_question = AsyncMock(
        return_value=BackendQuestionPersistenceResult(
            events=[
                {"event": "message", "data": "Choose an MCP resource."},
                {"event": "question", "data": "{}"},
            ],
            new_planning_state_version=4,
        )
    )
    store_plan = AsyncMock(return_value=_stored_plan_result())

    with (
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.mcp_clarification_issue_if_needed",
            return_value=issue,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.build_mcp_resource_selection_question",
            return_value=({"id": "mcp_resource_selection"}, "Choose an MCP resource."),
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.persist_backend_question",
            new=persist_backend_question,
        ),
        patch(
            "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
            new=store_plan,
        ),
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(resource_catalog=MagicMock())
        )

    assert result.event == {"event": "message", "data": "Choose an MCP resource."}
    assert result.events == ({"event": "question", "data": "{}"},)
    assert result.new_planning_state_version == 4
    store_plan.assert_not_awaited()
    persisted_metadata = persist_backend_question.await_args.kwargs[
        "assistant_metadata"
    ]
    assert (
        persisted_metadata["planner_telemetry"]["proposal_first_attempt_success"]
        is True
    )


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_keeps_compiled_edit_without_description_repair() -> (
    None
):
    finalizer = _make_finalizer()
    original_spec = _make_flow_spec()
    captured_compiled: list[CompiledProposal] = []

    async def store_plan(**kwargs):
        captured_compiled.append(kwargs["compiled"])
        return await _store_compiled_plan(**kwargs)

    with patch(
        "intric.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                compiled=_compiled_edit_proposal(compiled_spec=original_spec),
                flow=SimpleNamespace(
                    description="Old generated description.",
                    metadata_json={"ai_builder": {"description": {}}},
                    steps=[],
                ),
            )
        )

    assert result.event is not None
    captured = captured_compiled[0]
    assert captured.spec.flow_description == original_spec.flow_description
    captured_edit = captured.edit
    assert captured_edit is not None
    assert [advisory.code for advisory in captured_edit.advisories] == [
        "flow_description_update_required"
    ]

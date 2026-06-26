"""Pure proposal-turn builders shared by proposal processor/submission tests."""

from __future__ import annotations

from uuid import UUID, uuid4

from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    FlowBuilderEditApproval,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    PlanStatus,
)
from intric.flows.ai_builder.ai_builder_edit_compiler import EditCompilationResult
from intric.flows.ai_builder.ai_builder_edit_preview_models import (
    EditAdvisory,
    FlowEditDiff,
    StepChange,
)
from intric.flows.ai_builder.ai_builder_event_models import AIBuilderPlanEvent
from intric.flows.ai_builder.ai_builder_events import build_plan_event
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ProposalTurnContext,
    ToolRetryInvocation,
)
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
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


def _make_turn(
    *,
    session_id: UUID | None = None,
    tenant_id: UUID | None = None,
    base_planning_state_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_planning_state_version,
    )


def _make_context(**overrides: object) -> ProposalTurnContext:
    turn_override = overrides.pop("turn", None)
    session_id_override = overrides.pop("session_id", None)
    base_version_override = overrides.pop("base_planning_state_version", 0)
    turn = (
        turn_override
        if isinstance(turn_override, SessionSendTurn)
        else _make_turn(
            session_id=(
                session_id_override if isinstance(session_id_override, UUID) else None
            ),
            base_planning_state_version=(
                base_version_override if isinstance(base_version_override, int) else 0
            ),
        )
    )
    defaults = {
        "turn": turn,
        "conversation": [],
        "new_messages_start": 0,
        "llm_messages": [],
        "tool_schemas": [],
        "litellm_model": "openai/gpt-5.4",
        "litellm_kwargs": {},
        "available_model_refs": None,
        "available_kb_refs": None,
        "resource_catalog": None,
        "max_output_tokens": 4096,
        "request_id": "req-1",
        "flow": None,
        "assistant_snapshots": None,
        "text_content": None,
    }
    defaults.update(overrides)
    return ProposalTurnContext(**defaults)


def _make_retry_invocation(**overrides: object) -> ToolRetryInvocation:
    defaults = {
        "turn": _make_turn(),
        "conversation": [],
        "new_messages_start": 0,
        "arguments": {"flow_name": "Test", "plan_rationale": "R", "steps": []},
        "assistant_content": "Här är mitt korrigerade förslag:",
        "tool_call_id": "call_retry",
        "available_model_refs": None,
        "available_kb_refs": None,
        "resource_catalog": None,
        "flow": None,
        "assistant_metadata": None,
    }
    defaults.update(overrides)
    return ToolRetryInvocation(**defaults)


def _compiled_outline_proposal() -> CompiledProposal:
    spec = _make_flow_spec(model_ref=None, knowledge_refs=[])
    return CompiledProposal(
        content=FlowBuilderProposalContent(
            spec=spec,
            plan_rationale="Classify incoming text.",
        ),
        validation=SpecValidationResult(),
    )


def _plan_stream_event(
    *,
    compiled: CompiledProposal | None = None,
    plan_id: UUID | None = None,
) -> AIBuilderPlanEvent:
    proposal = compiled or _compiled_outline_proposal()
    return build_plan_event(
        plan_id=plan_id or uuid4(),
        proposal=proposal.content,
    )


def _builder_plan(spec: FlowDraftSpecCore) -> BuilderPlan:
    return BuilderPlan(
        id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4(),
        status=PlanStatus.PROPOSED,
        proposal=FlowBuilderProposal(content=FlowBuilderProposalContent(spec=spec)),
    )


def _compiled_outline_proposal_with_validation(
    validation: SpecValidationResult,
) -> CompiledProposal:
    compiled = _compiled_outline_proposal()
    return CompiledProposal(
        content=compiled.content,
        reasoning=compiled.reasoning,
        validation=validation,
        resource_bindings=compiled.resource_bindings,
        aggregation_intent=compiled.aggregation_intent,
    )


def _compiled_edit_proposal(
    *,
    spec: FlowDraftSpecCore | None = None,
    advisories: list[EditAdvisory] | None = None,
) -> CompiledProposal:
    compiled_spec = spec or _make_flow_spec(model_ref=None, knowledge_refs=[])
    edit = FlowBuilderEditApproval(
        diff=FlowEditDiff(
            step_changes=[StepChange(kind="unchanged", step_name="Analys")]
        ),
        base_flow_revision=7,
        advisories=advisories or [],
    )
    return CompiledProposal(
        content=FlowBuilderProposalContent(
            spec=compiled_spec,
            plan_rationale="Update the flow.",
            edit=edit,
        ),
        validation=SpecValidationResult(),
    )


def _description_update_advisory() -> EditAdvisory:
    return EditAdvisory(
        code="flow_description_update_required",
        message="Refresh the flow description.",
        severity="warning",
        field="flow_description",
    )


def _make_flow_spec(
    *,
    model_ref: str | None,
    knowledge_refs: list[str],
    mcp_server_refs: list[str] | None = None,
    mcp_tool_refs: list[str] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Grounded flow",
        flow_description="Desc",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Analys",
                assistant_spec=AssistantSpec(
                    instructions="Gör analysen.",
                    model_ref=model_ref,
                    knowledge_refs=knowledge_refs,
                    mcp_server_refs=mcp_server_refs or [],
                    mcp_tool_refs=mcp_tool_refs or [],
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
                mcp_policy=MCPPolicy.INHERIT,
            )
        ],
    )


def _make_edit_approval() -> FlowBuilderEditApproval:
    return FlowBuilderEditApproval(
        diff=FlowEditDiff(
            step_changes=[StepChange(kind="unchanged", step_name="Analys")]
        ),
        base_flow_revision=7,
    )


def _make_edit_compilation(
    compiled_spec: FlowDraftSpecCore,
) -> EditCompilationResult:
    return EditCompilationResult(
        spec=compiled_spec,
        approval=_make_edit_approval(),
    )

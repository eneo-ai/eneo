"""Pure proposal-turn builders shared by proposal processor/submission tests."""

from __future__ import annotations

from uuid import UUID, uuid4

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    FlowBuilderEditApproval,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    PlanStatus,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import EditCompilationResult
from eneo.flows.ai_builder.ai_builder_edit_preview_models import (
    EditAdvisory,
    FlowEditDiff,
    StepChange,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderPlanEvent
from eneo.flows.ai_builder.ai_builder_events import build_plan_event
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
    ProposalMessageGroup,
    ProposalTurnContext,
    ToolRetryInvocation,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
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
    legacy_messages = overrides.pop("llm_messages", None)
    turn_override = overrides.pop("turn", None)
    session_id_override = overrides.pop("session_id", None)
    base_version_override = overrides.pop("base_planning_state_version", 0)
    litellm_model = overrides.pop("litellm_model", "openai/gpt-5.4")
    litellm_kwargs = overrides.pop("litellm_kwargs", {})
    if not isinstance(litellm_model, str) or not isinstance(litellm_kwargs, dict):
        raise TypeError(
            "Proposal test route requires a model name and provider kwargs."
        )
    provider_kwargs = {
        key: value for key, value in litellm_kwargs.items() if isinstance(key, str)
    }
    if len(provider_kwargs) != len(litellm_kwargs):
        raise TypeError("Proposal test provider kwargs require string keys.")
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
    defaults: dict[str, object] = {
        "turn": turn,
        "conversation": [],
        "new_messages_start": 0,
        "message_groups": (),
        "tool_schemas": [],
        "route": ResolvedCompletionModelRoute(
            litellm_model=litellm_model,
            litellm_kwargs=provider_kwargs,
            supported_model_kwargs=SupportedModelKwargs(
                temperature=ModelKwargCapability(supported=True)
            ),
        ),
        "available_model_refs": None,
        "available_kb_refs": None,
        "resource_catalog": None,
        "max_output_tokens": 4096,
        "request_id": "req-1",
        "flow": None,
        "assistant_snapshots": None,
        "text_content": None,
    }
    if legacy_messages is not None:
        if not isinstance(legacy_messages, list):
            raise TypeError("Proposal test messages must be a list.")
        defaults["message_groups"] = (
            (
                ProposalMessageGroup(
                    messages=tuple(legacy_messages),  # type: ignore[arg-type]
                    kind="current_turn",
                    protected=True,
                ),
            )
            if legacy_messages
            else ()
        )
    defaults.update(overrides)
    return ProposalTurnContext(**defaults)  # type: ignore[arg-type]


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
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
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

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias
from uuid import UUID

from eneo.files.file_models import File
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContext,
    AIBuilderAttachmentContextPolicy,
    build_ai_builder_attachment_context_for_model,
    fit_ai_builder_attachment_context,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationMetadata,
    provider_safe_tool_call_id,
    question_answer_from_metadata,
    tool_calls_from_message,
    ui_language_from_metadata,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryAnalysis,
)
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from eneo.flows.ai_builder.ai_builder_discovery_runtime import (
    build_discovery_runtime_result,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_flow_context import build_flow_context
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_unprompted_user_text,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
    extract_requested_output_sections,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    build_plan_revision_prompt_block,
)
from eneo.flows.ai_builder.ai_builder_plan_proposal_task import (
    build_plan_proposal_system_prompt,
)
from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
    build_requirements_signal_text,
    form_intake_signal_values_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    LLMMessageParam,
    LLMMessageRole,
    ProposalMessageGroup,
    ProposalRequestBudget,
    fit_proposal_message_groups,
    flatten_proposal_message_groups,
    group_proposal_messages,
)
from eneo.flows.ai_builder.ai_builder_requirements_state import (
    RequirementsState,
    latest_confirmed_requirements,
    resolve_requirements_state,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    DeclaredSchemaCandidate,
    SchemaCandidateRefusal,
    SchemaLimitExceeded,
    derive_freeform_schema_candidates,
    latest_schema_direction_answer_matches_candidates,
    merge_declared_schema_candidates,
)
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from eneo.flows.ai_builder.ai_builder_tools import build_propose_flow_tool_schema
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    BuilderTurnDecision,
    GenerateProposal,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import PlanningState
from eneo.flows.ai_builder.planning_state_builder import (
    carry_forward_persisted_planner_state,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.main.logging import get_logger
from eneo.observability.failure_events import stable_hash
from eneo.tokens.token_utils import count_message_tokens, count_tool_tokens

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        ResolvedCompletionModelRoute,
    )
    from eneo.flows.domain.flow import Flow, FlowStep

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlannerRequestPreparationInput:
    conversation: list[ConversationMessage]
    litellm_client: Any
    completion_model_route: ResolvedCompletionModelRoute
    available_models: list[AIBuilderAvailableModelResource] | None
    available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None
    flow: Flow | None
    assistant_snapshots: AssistantAuthoringSnapshots | None
    attachment_files: list[File]
    max_input_tokens: int
    max_output_tokens: int
    budget_policy: AIBuilderBudgetPolicy
    attachment_context_policy: AIBuilderAttachmentContextPolicy
    mapped_execution_policy: FlowMappedExecutionPolicy
    base_planning_state_version: int
    tenant_id: UUID
    plan_edit_context: AIBuilderPlanEditContext | None
    prior_plan_for_revision: BuilderPlan | None
    persisted_planning_state: PlanningState | None
    current_turn_start: int
    usage_tracker: ProposalTurnTelemetry
    before_provider_call: Callable[[], Awaitable[None]] | None = None
    prepared_attachment_context: AIBuilderAttachmentContext | None = None
    prepared_schema_candidates: tuple[DeclaredSchemaCandidate, ...] | None = None


@dataclass(frozen=True, slots=True)
class PreparedPromptMessages:
    message_groups: tuple[ProposalMessageGroup, ...]
    system_prompt_hash: str
    conversation_budget_tokens: int
    trimmed_message_count: int
    system_prompt_chars: int

    @property
    def llm_messages(self) -> list[LLMMessageParam]:
        return flatten_proposal_message_groups(self.message_groups)


@dataclass(frozen=True, slots=True)
class _PreparedBase:
    requirements_state: RequirementsState
    ui_language: str | None
    slot_classification_metadata: SlotClassificationMetadata | None


@dataclass(frozen=True, slots=True)
class ServerOutputPrepared(_PreparedBase):
    server_decision: BuilderTurnDecision
    discovery_analysis: DiscoveryAnalysis
    planning_state: PlanningState
    resource_catalog: AIBuilderResourceCatalog
    attachment_context: AIBuilderAttachmentContext | None
    flow_context: str | None


@dataclass(frozen=True, slots=True)
class ProposalPrepared(_PreparedBase):
    message_groups: tuple[ProposalMessageGroup, ...]
    system_prompt_hash: str
    plan_edit_context: AIBuilderPlanEditContext | None
    prior_plan_for_revision: BuilderPlan | None
    resource_catalog: AIBuilderResourceCatalog
    planning_state: PlanningState
    requested_output_sections: RequestedOutputSections
    request_budget: ProposalRequestBudget | None = None

    @property
    def llm_messages(self) -> list[LLMMessageParam]:
        return flatten_proposal_message_groups(self.message_groups)


PreparedTurnOutcome: TypeAlias = ServerOutputPrepared | ProposalPrepared


async def prepare_planner_request(
    request: PlannerRequestPreparationInput,
) -> PreparedTurnOutcome:
    requirements_state = resolve_requirements_state(request.conversation)
    ui_language = _resolve_ui_language(request.conversation)
    if request.prepared_schema_candidates is not None:
        attachment_context_result = request.prepared_attachment_context
        schema_candidates = request.prepared_schema_candidates
    else:
        attachment_context_result = build_ai_builder_attachment_context_for_model(
            request.attachment_files,
            policy=request.attachment_context_policy,
            model_name=request.completion_model_route.litellm_model,
            max_input_tokens=request.max_input_tokens,
            max_output_tokens=request.max_output_tokens,
            safety_buffer_tokens=request.budget_policy.conversation_safety_buffer_tokens,
            minimum_conversation_tokens=(
                request.budget_policy.minimum_conversation_budget_tokens
            ),
        )
        schema_candidates = validate_preprovider_schema_gate(
            conversation=request.conversation,
            attachment_context=attachment_context_result,
        )
    discovery_runtime = await build_discovery_runtime_result(
        request.conversation,
        flow=request.flow,
        litellm_client=request.litellm_client,
        completion_model_route=request.completion_model_route,
        ui_language=ui_language,
        tenant_id=request.tenant_id,
        attachment_context=attachment_context_result,
        usage_tracker=request.usage_tracker,
        before_provider_call=request.before_provider_call,
        mapped_execution_policy=request.mapped_execution_policy,
        prepared_schema_candidates=schema_candidates,
    )
    discovery_analysis = discovery_runtime.discovery_analysis
    rebuilt_planning_state = discovery_runtime.planning_state

    flow_context = _build_flow_context_if_needed(
        conversation=request.conversation,
        flow=request.flow,
        assistant_snapshots=request.assistant_snapshots,
    )
    prior_resource_bindings = (
        request.prior_plan_for_revision.resource_bindings
        if request.prior_plan_for_revision is not None
        else tuple()
    )
    resource_catalog = build_ai_builder_resource_catalog(
        available_models=request.available_models,
        available_kbs=request.available_kbs,
        prior_bindings=prior_resource_bindings,
    )
    carry_forward_persisted_planner_state(
        rebuilt_planning_state,
        request.persisted_planning_state,
        attached_file_ids={file.id for file in request.attachment_files},
    )
    if discovery_runtime.schema_direction_pending:
        rebuilt_planning_state.replace_schema_resolution(
            input_evidence=None,
            output_evidence=None,
            example_inference=None,
        )
    turn_control = resolve_turn_control(
        session_state=rebuilt_planning_state,
        selected_discovery_question_ids=discovery_analysis.selected_question_ids,
        confirmed_attachment_evidence_fingerprint=(
            requirements_state.confirmed_attachment_evidence_fingerprint
        ),
        ui_language=ui_language,
        discovery_assumptions=discovery_analysis.assumptions,
        attachment_context=attachment_context_result,
        schema_candidates=discovery_runtime.schema_candidates,
        schema_direction_pending=discovery_runtime.schema_direction_pending,
    )
    if not isinstance(turn_control.decision, GenerateProposal):
        return ServerOutputPrepared(
            requirements_state=requirements_state,
            ui_language=ui_language,
            slot_classification_metadata=(
                discovery_runtime.slot_classification_metadata
            ),
            discovery_analysis=discovery_analysis,
            server_decision=turn_control.decision,
            planning_state=rebuilt_planning_state,
            resource_catalog=resource_catalog,
            attachment_context=attachment_context_result,
            flow_context=flow_context,
        )

    assert isinstance(turn_control.decision, GenerateProposal)
    return build_proposal_prepared(
        requirements_state=requirements_state,
        ui_language=ui_language,
        slot_classification_metadata=discovery_runtime.slot_classification_metadata,
        conversation=request.conversation,
        planning_state=rebuilt_planning_state,
        attachment_context=attachment_context_result,
        flow_context=flow_context,
        is_edit_mode=request.flow is not None,
        resource_catalog=resource_catalog,
        current_steps=None if request.flow is None else list(request.flow.steps),
        plan_edit_context=request.plan_edit_context,
        prior_plan_for_revision=request.prior_plan_for_revision,
        litellm_model=request.completion_model_route.litellm_model,
        max_input_tokens=request.max_input_tokens,
        max_output_tokens=request.max_output_tokens,
        budget_policy=request.budget_policy,
        attachment_file_count=len(request.attachment_files),
        current_turn_start=request.current_turn_start,
    )


def build_proposal_prepared(
    *,
    requirements_state: RequirementsState,
    ui_language: str | None,
    slot_classification_metadata: SlotClassificationMetadata | None,
    conversation: list[ConversationMessage],
    planning_state: PlanningState,
    attachment_context: AIBuilderAttachmentContext | None,
    flow_context: str | None,
    is_edit_mode: bool,
    resource_catalog: AIBuilderResourceCatalog,
    current_steps: list["FlowStep"] | None,
    plan_edit_context: AIBuilderPlanEditContext | None,
    prior_plan_for_revision: BuilderPlan | None,
    litellm_model: str,
    max_input_tokens: int,
    max_output_tokens: int,
    budget_policy: AIBuilderBudgetPolicy,
    attachment_file_count: int,
    current_turn_start: int,
) -> ProposalPrepared:
    confirmed_requirements = latest_confirmed_requirements(conversation)
    section_signal_text = "\n".join(
        part
        for part in (
            aggregate_unprompted_user_text(conversation),
            build_requirements_signal_text(confirmed_requirements),
        )
        if part
    )
    requested_output_sections = extract_requested_output_sections(
        section_signal_text,
        model_form_intake_signals=form_intake_signal_values_from_planning_state(
            planning_state
        ),
        confirmed_headings=(
            planning_state.example_output_constraints.headings
            if planning_state.example_output_constraints is not None
            else ()
        ),
    )
    plan_revision_context = build_plan_revision_prompt_block(
        context=plan_edit_context,
        prior_plan=prior_plan_for_revision,
    )

    def build_proposal_prompt(attachment_text: str | None) -> str:
        return build_plan_proposal_system_prompt(
            planning_state=planning_state,
            confirmed_requirements=confirmed_requirements,
            attachment_context=attachment_text,
            flow_context=flow_context,
            is_edit_mode=is_edit_mode,
            resource_catalog=resource_catalog,
            requested_output_sections=requested_output_sections,
            plan_revision_context=plan_revision_context,
        )

    fitted_attachment_context = _fit_proposal_attachment_context(
        attachment_context=attachment_context,
        build_proposal_prompt=build_proposal_prompt,
        current_steps=current_steps,
        resource_catalog=resource_catalog,
        litellm_model=litellm_model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        budget_policy=budget_policy,
    )
    proposal_system_prompt = build_proposal_prompt(
        (
            fitted_attachment_context.context
            if fitted_attachment_context is not None
            else None
        )
    )
    prepared_prompt = _prepare_prompt_messages(
        conversation=conversation,
        system_prompt=proposal_system_prompt,
        litellm_model=litellm_model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        budget_policy=budget_policy,
        current_turn_start=current_turn_start,
    )
    logger.info(
        "AI Builder plan proposal prompt metrics",
        extra={
            "system_prompt_chars": prepared_prompt.system_prompt_chars,
            "attachment_context_chars": len(
                fitted_attachment_context.context or ""
                if fitted_attachment_context is not None
                else ""
            ),
            "conversation_budget_tokens": prepared_prompt.conversation_budget_tokens,
            "conversation_message_count": len(conversation),
            "trimmed_message_count": prepared_prompt.trimmed_message_count,
            "attachment_file_count": attachment_file_count,
            "confirmed_requirements_present": confirmed_requirements is not None,
        },
    )

    return ProposalPrepared(
        requirements_state=requirements_state,
        ui_language=ui_language,
        slot_classification_metadata=slot_classification_metadata,
        message_groups=prepared_prompt.message_groups,
        system_prompt_hash=prepared_prompt.system_prompt_hash,
        plan_edit_context=plan_edit_context,
        prior_plan_for_revision=prior_plan_for_revision,
        resource_catalog=resource_catalog,
        planning_state=planning_state,
        requested_output_sections=requested_output_sections,
        request_budget=ProposalRequestBudget(
            context_window_tokens=max_input_tokens,
            output_reserve_tokens=max_output_tokens,
            safety_buffer_tokens=budget_policy.conversation_safety_buffer_tokens,
        ),
    )


def _fit_proposal_attachment_context(
    *,
    attachment_context: AIBuilderAttachmentContext | None,
    build_proposal_prompt: Callable[[str | None], str],
    current_steps: list["FlowStep"] | None,
    resource_catalog: AIBuilderResourceCatalog,
    litellm_model: str,
    max_input_tokens: int,
    max_output_tokens: int,
    budget_policy: AIBuilderBudgetPolicy,
) -> AIBuilderAttachmentContext | None:
    if attachment_context is None:
        return None

    proposal_tool = build_propose_flow_tool_schema(
        current_steps=current_steps,
        resource_catalog=resource_catalog,
    )
    system_prompt_token_limit = max(
        0,
        max_input_tokens
        - max_output_tokens
        - budget_policy.conversation_safety_buffer_tokens
        - budget_policy.minimum_conversation_budget_tokens
        - count_tool_tokens([proposal_tool], litellm_model),
    )

    def fits_context(context: str | None) -> bool:
        prompt = build_proposal_prompt(context)
        return (
            count_message_tokens(
                [{"role": "system", "content": prompt}],
                litellm_model,
            )
            <= system_prompt_token_limit
        )

    return fit_ai_builder_attachment_context(
        attachment_context,
        fits_context=fits_context,
    )


def validate_preprovider_schema_gate(
    *,
    conversation: list[ConversationMessage],
    attachment_context: AIBuilderAttachmentContext | None,
) -> tuple[DeclaredSchemaCandidate, ...]:
    """Validate deterministic schema blockers before any provider work."""

    if attachment_context is not None:
        blocking_refusal = next(
            (
                refusal
                for refusal in attachment_context.schema_discovery.refusals
                if refusal.blocks_provider_work
            ),
            None,
        )
        if blocking_refusal is not None:
            _raise_schema_limit(blocking_refusal)
    try:
        candidates = merge_declared_schema_candidates(
            derive_freeform_schema_candidates(conversation),
            (
                attachment_context.schema_discovery.candidates
                if attachment_context is not None
                else ()
            ),
        )
    except SchemaLimitExceeded as error:
        raise AIBuilderBadRequestException(
            "The supplied schema exceeds the Builder safety limit.",
            code=AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED,
            context={
                "reason": error.reason,
                "max_value": error.max_value,
                **(
                    {"actual_value": error.actual_value}
                    if error.actual_value is not None
                    else {}
                ),
            },
        ) from error
    if not latest_schema_direction_answer_matches_candidates(
        conversation=conversation,
        candidates=candidates,
    ):
        raise AIBuilderBadRequestException(
            "The schema-direction answer does not match the current schemas.",
            code=AIBuilderErrorCode.INVALID_QUESTION_PAYLOAD,
            context={"reason": "invalid_schema_direction"},
        )
    return candidates


def _raise_schema_limit(refusal: SchemaCandidateRefusal) -> None:
    raise AIBuilderBadRequestException(
        "An attached schema exceeds the Builder safety limit.",
        code=AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED,
        context={
            "reason": refusal.reason,
            "max_value": refusal.max_value,
            **(
                {"actual_value": refusal.actual_value}
                if refusal.actual_value is not None
                else {}
            ),
            "file_id": str(refusal.file_id),
        },
    )


def _build_flow_context_if_needed(
    *,
    conversation: list[ConversationMessage],
    flow: Flow | None,
    assistant_snapshots: AssistantAuthoringSnapshots | None,
) -> str | None:
    if flow is None:
        return None
    discovery_profile = build_discovery_profile(conversation, flow=flow)
    return build_flow_context(
        flow,
        assistant_snapshots=assistant_snapshots,
        is_edit_mode=True,
        capabilities=discovery_profile.capabilities,
        edit_scope=discovery_profile.edit_scope,
    )


def _prepare_prompt_messages(
    *,
    conversation: list[ConversationMessage],
    system_prompt: str,
    litellm_model: str,
    max_input_tokens: int,
    max_output_tokens: int,
    budget_policy: AIBuilderBudgetPolicy,
    current_turn_start: int,
) -> PreparedPromptMessages:
    prompt_tokens = count_message_tokens(
        [{"role": "system", "content": system_prompt}],
        litellm_model,
    )
    conversation_budget = compute_conversation_token_budget(
        model_max_input_tokens=max_input_tokens,
        system_prompt_tokens=prompt_tokens,
        max_output_tokens=max_output_tokens,
        safety_buffer_tokens=budget_policy.conversation_safety_buffer_tokens,
    )
    raw_messages = [
        conversation_message_to_llm_message(message) for message in conversation
    ]
    conversation_groups = group_proposal_messages(
        raw_messages,
        current_turn_index=current_turn_start,
    )
    trimmed_groups = fit_proposal_message_groups(
        conversation_groups,
        token_limit=conversation_budget,
        model_name=litellm_model,
    )
    if trimmed_groups is None:
        trimmed_groups = tuple(
            group for group in conversation_groups if group.protected
        )
    system_group = ProposalMessageGroup(
        messages=({"role": "system", "content": system_prompt},),
        kind="system",
        protected=True,
    )
    return PreparedPromptMessages(
        message_groups=(system_group, *trimmed_groups),
        system_prompt_hash=stable_hash(system_prompt),
        conversation_budget_tokens=conversation_budget,
        trimmed_message_count=sum(len(group.messages) for group in trimmed_groups),
        system_prompt_chars=len(system_prompt),
    )


def compute_conversation_token_budget(
    *,
    model_max_input_tokens: int,
    system_prompt_tokens: int,
    max_output_tokens: int,
    safety_buffer_tokens: int,
) -> int:
    budget = (
        model_max_input_tokens
        - system_prompt_tokens
        - max_output_tokens
        - safety_buffer_tokens
    )
    return max(budget, 0)


def trim_conversation_for_context(
    messages: list[LLMMessageParam],
    *,
    max_tokens: int,
    litellm_model: str = "",
) -> list[LLMMessageParam]:
    if not messages:
        return []
    groups = group_proposal_messages(
        messages,
        current_turn_index=len(messages) - 1,
    )
    fitted = fit_proposal_message_groups(
        groups,
        token_limit=max_tokens,
        model_name=litellm_model,
    )
    if fitted is None:
        fitted = tuple(group for group in groups if group.protected)
    return flatten_proposal_message_groups(fitted)


def conversation_message_to_llm_message(msg: ConversationMessage) -> LLMMessageParam:
    content = msg.content
    question_answer = question_answer_from_metadata(msg.metadata)
    if msg.role == "user" and question_answer is not None:
        question_answer_payload = question_answer.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"kind", "ui_language"},
        )
        sanitized_answer = {
            key: value
            for key, value in question_answer_payload.items()
            if key
            in {
                "question_id",
                "selected_option_ids",
                "selected_values",
                "custom_value",
            }
        }
        if sanitized_answer:
            structured_note = json.dumps(
                sanitized_answer,
                ensure_ascii=False,
                sort_keys=True,
            )
            content = (
                f"{content}\n\n[Structured answer metadata: {structured_note}]"
                if content
                else f"[Structured answer metadata: {structured_note}]"
            )

    payload: LLMMessageParam = {
        "role": _llm_message_role(msg.role),
        "content": content,
    }
    tool_calls = tool_calls_from_message(msg)
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": provider_safe_tool_call_id(tool_call.id),
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                },
            }
            for tool_call in tool_calls
        ]
    if msg.tool_call_id:
        payload["tool_call_id"] = provider_safe_tool_call_id(msg.tool_call_id)
    return payload


def _llm_message_role(role: str) -> LLMMessageRole:
    match role:
        case "system":
            return "system"
        case "user":
            return "user"
        case "assistant":
            return "assistant"
        case "tool":
            return "tool"
        case _:
            raise ValueError(f"Unsupported AI Builder conversation role: {role!r}")


def _resolve_ui_language(conversation: list[ConversationMessage]) -> str | None:
    for message in reversed(conversation):
        if message.role != "user":
            continue
        ui_language = ui_language_from_metadata(message.metadata)
        if ui_language is not None:
            return ui_language
    return None

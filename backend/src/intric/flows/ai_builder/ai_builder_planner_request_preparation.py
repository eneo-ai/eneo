from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias, cast
from uuid import UUID

from intric.files.file_models import File
from intric.flows.ai_builder.ai_builder_attachment_context import (
    build_ai_builder_attachment_context,
)
from intric.flows.ai_builder.ai_builder_conversation_metadata import (
    SlotClassificationMetadata,
    provider_safe_tool_call_id,
    question_answer_from_metadata,
    tool_calls_from_message,
    ui_language_from_metadata,
)
from intric.flows.ai_builder.ai_builder_discovery_models import (
    DiscoveryAnalysis,
)
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    DiscoveryRuntimeResult,
    build_discovery_runtime_result,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
)
from intric.flows.ai_builder.ai_builder_mcp_intent import (
    mcp_resource_selection_values,
)
from intric.flows.ai_builder.ai_builder_mcp_resources import AIBuilderMCPResourceInput
from intric.flows.ai_builder.ai_builder_output_sections_signals import (
    extract_requested_output_sections,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    build_plan_revision_prompt_block,
)
from intric.flows.ai_builder.ai_builder_plan_proposal_task import (
    build_plan_proposal_system_prompt,
)
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    build_requirements_signal_text,
)
from intric.flows.ai_builder.ai_builder_prompts import (
    build_flow_context,
    compute_conversation_token_budget,
    trim_conversation_for_context,
)
from intric.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    LLMMessageParam,
    LLMMessageRole,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    RequirementsState,
    latest_confirmed_requirements,
    resolve_requirements_state,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
    AIBuilderResourceCatalog,
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from intric.flows.ai_builder.ai_builder_turn_controller import (
    BuilderTurnDecision,
    GenerateProposal,
    resolve_turn_control,
)
from intric.flows.ai_builder.planning_state import PlanningState
from intric.flows.ai_builder.planning_state_builder import (
    carry_forward_persisted_planner_state,
)
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from intric.main.logging import get_logger
from intric.observability.failure_events import stable_hash

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PlannerRequestPreparationInput:
    conversation: list[ConversationMessage]
    message: str
    litellm_client: Any
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    available_models: list[AIBuilderAvailableModelResource] | None
    available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None
    flow: Flow | None
    assistant_snapshots: AssistantAuthoringSnapshots | None
    attachment_files: list[File]
    max_input_tokens: int
    max_output_tokens: int
    budget_policy: AIBuilderBudgetPolicy
    is_requirements_confirmation: bool
    base_planning_state_version: int
    tenant_id: UUID
    plan_edit_context: AIBuilderPlanEditContext | None
    prior_plan_for_revision: BuilderPlan | None
    allow_discovery_semantic_adjudication: bool
    persisted_planning_state: PlanningState | None
    available_mcps: AIBuilderMCPResourceInput


@dataclass(frozen=True, slots=True)
class PreparedPromptMessages:
    llm_messages: list[LLMMessageParam]
    system_prompt_hash: str
    conversation_budget_tokens: int
    trimmed_message_count: int
    system_prompt_chars: int


@dataclass(frozen=True, slots=True)
class _PreparedBase:
    requirements_state: RequirementsState
    ui_language: str | None
    slot_classification_metadata: SlotClassificationMetadata | None


@dataclass(frozen=True, slots=True)
class ServerOutputPrepared(_PreparedBase):
    server_decision: BuilderTurnDecision
    discovery_analysis: DiscoveryAnalysis


@dataclass(frozen=True, slots=True)
class ProposalPrepared(_PreparedBase):
    llm_messages: list[LLMMessageParam]
    system_prompt_hash: str
    plan_edit_context: AIBuilderPlanEditContext | None
    prior_plan_for_revision: BuilderPlan | None
    resource_catalog: AIBuilderResourceCatalog
    planning_state: PlanningState
    discovery_runtime: DiscoveryRuntimeResult


PreparedTurnOutcome: TypeAlias = (
    ServerOutputPrepared
    | ProposalPrepared
)


async def prepare_planner_request(
    request: PlannerRequestPreparationInput,
) -> PreparedTurnOutcome:
    requirements_state = resolve_requirements_state(request.conversation)
    ui_language = _resolve_ui_language(request.conversation)
    discovery_runtime = await build_discovery_runtime_result(
        request.conversation,
        flow=request.flow,
        litellm_client=request.litellm_client,
        litellm_model=request.litellm_model,
        litellm_kwargs=request.litellm_kwargs,
        ui_language=ui_language,
        allow_semantic_adjudication=request.allow_discovery_semantic_adjudication,
        tenant_id=request.tenant_id,
        requirements_confirmed=requirements_state.confirmed,
        is_requirements_confirmation=request.is_requirements_confirmation,
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
        available_mcps=request.available_mcps,
        prior_bindings=prior_resource_bindings,
    )
    carry_forward_persisted_planner_state(
        rebuilt_planning_state,
        request.persisted_planning_state,
    )
    turn_control = resolve_turn_control(
        session_state=rebuilt_planning_state,
        selected_discovery_question_ids=discovery_analysis.selected_question_ids,
        requirements_confirmed=requirements_state.confirmed,
        is_edit_mode=request.flow is not None,
        ui_language=ui_language,
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
        )

    confirmed_requirements = latest_confirmed_requirements(request.conversation)
    section_signal_text = "\n".join(
        part
        for part in (
            aggregate_freeform_user_text(request.conversation),
            build_requirements_signal_text(confirmed_requirements),
        )
        if part
    )
    attachment_context_result = build_ai_builder_attachment_context(
        request.attachment_files
    )
    assert isinstance(turn_control.decision, GenerateProposal)
    proposal_system_prompt = build_plan_proposal_system_prompt(
        planning_state=rebuilt_planning_state,
        confirmed_requirements=confirmed_requirements,
        attachment_context=(
            attachment_context_result.context
            if attachment_context_result is not None
            else None
        ),
        flow_context=flow_context,
        is_edit_mode=request.flow is not None,
        resource_catalog=resource_catalog,
        mcp_selection_values=mcp_resource_selection_values(request.conversation),
        requested_output_sections=extract_requested_output_sections(
            section_signal_text
        ),
        plan_revision_context=build_plan_revision_prompt_block(
            context=request.plan_edit_context,
            prior_plan=request.prior_plan_for_revision,
        ),
    )
    prepared_prompt = _prepare_prompt_messages(
        conversation=request.conversation,
        system_prompt=proposal_system_prompt,
        litellm_model=request.litellm_model,
        max_input_tokens=request.max_input_tokens,
        max_output_tokens=request.max_output_tokens,
        budget_policy=request.budget_policy,
    )
    logger.info(
        "AI Builder plan proposal prompt metrics",
        extra={
            "system_prompt_chars": prepared_prompt.system_prompt_chars,
            "attachment_context_chars": len(
                attachment_context_result.context
                if attachment_context_result is not None
                else ""
            ),
            "conversation_budget_tokens": prepared_prompt.conversation_budget_tokens,
            "conversation_message_count": len(request.conversation),
            "trimmed_message_count": prepared_prompt.trimmed_message_count,
            "attachment_file_count": len(request.attachment_files),
            "confirmed_requirements_present": confirmed_requirements is not None,
        },
    )

    return ProposalPrepared(
        requirements_state=requirements_state,
        ui_language=ui_language,
        slot_classification_metadata=discovery_runtime.slot_classification_metadata,
        llm_messages=prepared_prompt.llm_messages,
        system_prompt_hash=prepared_prompt.system_prompt_hash,
        plan_edit_context=request.plan_edit_context,
        prior_plan_for_revision=request.prior_plan_for_revision,
        resource_catalog=resource_catalog,
        planning_state=rebuilt_planning_state,
        discovery_runtime=discovery_runtime,
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
) -> PreparedPromptMessages:
    prompt_tokens = max(1, len(system_prompt) // 3)
    conversation_budget = compute_conversation_token_budget(
        litellm_model=litellm_model,
        model_max_input_tokens=max_input_tokens,
        system_prompt_tokens=prompt_tokens,
        max_output_tokens=max_output_tokens,
        safety_buffer_tokens=budget_policy.conversation_safety_buffer_tokens,
        minimum_budget_tokens=budget_policy.minimum_conversation_budget_tokens,
        unknown_model_context_window_tokens=(
            budget_policy.unknown_model_context_window_tokens
        ),
    )
    raw_messages = cast(
        list[dict[str, Any]],
        [conversation_message_to_llm_dict(message) for message in conversation],
    )
    trimmed = cast(
        list[LLMMessageParam],
        trim_conversation_for_context(
            raw_messages,
            max_tokens=conversation_budget,
        ),
    )
    return PreparedPromptMessages(
        llm_messages=[{"role": "system", "content": system_prompt}, *trimmed],
        system_prompt_hash=stable_hash(system_prompt),
        conversation_budget_tokens=conversation_budget,
        trimmed_message_count=len(trimmed),
        system_prompt_chars=len(system_prompt),
    )


def conversation_message_to_llm_dict(msg: ConversationMessage) -> LLMMessageParam:
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

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias, TypeVar
from uuid import UUID

from eneo.files.file_models import File
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    build_ai_builder_attachment_context,
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
from eneo.flows.ai_builder.ai_builder_flow_context import build_flow_context
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
)
from eneo.flows.ai_builder.ai_builder_mcp_intent import (
    mcp_resource_selection_values,
)
from eneo.flows.ai_builder.ai_builder_mcp_resources import AIBuilderMCPResourceInput
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
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
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    LLMMessageParam,
    LLMMessageRole,
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
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
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
from eneo.main.logging import get_logger
from eneo.model_providers.domain.model_defaults import lookup_model_defaults
from eneo.observability.failure_events import stable_hash
from eneo.tokens.token_utils import count_message_tokens

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow

logger = get_logger(__name__)
_MessageT = TypeVar("_MessageT", bound=Mapping[str, Any])


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
    planning_state: PlanningState
    resource_catalog: AIBuilderResourceCatalog
    attachment_context: str | None
    flow_context: str | None


@dataclass(frozen=True, slots=True)
class ProposalPrepared(_PreparedBase):
    llm_messages: list[LLMMessageParam]
    system_prompt_hash: str
    plan_edit_context: AIBuilderPlanEditContext | None
    prior_plan_for_revision: BuilderPlan | None
    resource_catalog: AIBuilderResourceCatalog
    planning_state: PlanningState


PreparedTurnOutcome: TypeAlias = ServerOutputPrepared | ProposalPrepared


async def prepare_planner_request(
    request: PlannerRequestPreparationInput,
) -> PreparedTurnOutcome:
    requirements_state = resolve_requirements_state(request.conversation)
    ui_language = _resolve_ui_language(request.conversation)
    attachment_context_result = build_ai_builder_attachment_context(
        request.attachment_files
    )
    discovery_runtime = await build_discovery_runtime_result(
        request.conversation,
        flow=request.flow,
        litellm_client=request.litellm_client,
        litellm_model=request.litellm_model,
        litellm_kwargs=request.litellm_kwargs,
        ui_language=ui_language,
        allow_semantic_adjudication=request.allow_discovery_semantic_adjudication,
        tenant_id=request.tenant_id,
        attachment_context=attachment_context_result,
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
        ui_language=ui_language,
        discovery_assumptions=discovery_analysis.assumptions,
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
            attachment_context=(
                attachment_context_result.context
                if attachment_context_result is not None
                else None
            ),
            flow_context=flow_context,
        )

    assert isinstance(turn_control.decision, GenerateProposal)
    return build_proposal_prepared(
        requirements_state=requirements_state,
        ui_language=ui_language,
        slot_classification_metadata=discovery_runtime.slot_classification_metadata,
        conversation=request.conversation,
        planning_state=rebuilt_planning_state,
        attachment_context=(
            attachment_context_result.context
            if attachment_context_result is not None
            else None
        ),
        flow_context=flow_context,
        is_edit_mode=request.flow is not None,
        resource_catalog=resource_catalog,
        plan_edit_context=request.plan_edit_context,
        prior_plan_for_revision=request.prior_plan_for_revision,
        litellm_model=request.litellm_model,
        max_input_tokens=request.max_input_tokens,
        max_output_tokens=request.max_output_tokens,
        budget_policy=request.budget_policy,
        attachment_file_count=len(request.attachment_files),
    )


def build_proposal_prepared(
    *,
    requirements_state: RequirementsState,
    ui_language: str | None,
    slot_classification_metadata: SlotClassificationMetadata | None,
    conversation: list[ConversationMessage],
    planning_state: PlanningState,
    attachment_context: str | None,
    flow_context: str | None,
    is_edit_mode: bool,
    resource_catalog: AIBuilderResourceCatalog,
    plan_edit_context: AIBuilderPlanEditContext | None,
    prior_plan_for_revision: BuilderPlan | None,
    litellm_model: str,
    max_input_tokens: int,
    max_output_tokens: int,
    budget_policy: AIBuilderBudgetPolicy,
    attachment_file_count: int,
) -> ProposalPrepared:
    confirmed_requirements = latest_confirmed_requirements(conversation)
    section_signal_text = "\n".join(
        part
        for part in (
            aggregate_freeform_user_text(conversation),
            build_requirements_signal_text(confirmed_requirements),
        )
        if part
    )
    proposal_system_prompt = build_plan_proposal_system_prompt(
        planning_state=planning_state,
        confirmed_requirements=confirmed_requirements,
        attachment_context=attachment_context,
        flow_context=flow_context,
        is_edit_mode=is_edit_mode,
        resource_catalog=resource_catalog,
        mcp_selection_values=mcp_resource_selection_values(conversation),
        requested_output_sections=extract_requested_output_sections(
            section_signal_text,
            model_form_intake_signals=form_intake_signal_values_from_planning_state(
                planning_state
            ),
        ),
        plan_revision_context=build_plan_revision_prompt_block(
            context=plan_edit_context,
            prior_plan=prior_plan_for_revision,
        ),
    )
    prepared_prompt = _prepare_prompt_messages(
        conversation=conversation,
        system_prompt=proposal_system_prompt,
        litellm_model=litellm_model,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        budget_policy=budget_policy,
    )
    logger.info(
        "AI Builder plan proposal prompt metrics",
        extra={
            "system_prompt_chars": prepared_prompt.system_prompt_chars,
            "attachment_context_chars": len(attachment_context or ""),
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
        llm_messages=prepared_prompt.llm_messages,
        system_prompt_hash=prepared_prompt.system_prompt_hash,
        plan_edit_context=plan_edit_context,
        prior_plan_for_revision=prior_plan_for_revision,
        resource_catalog=resource_catalog,
        planning_state=planning_state,
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
    prompt_tokens = count_message_tokens(
        [{"role": "system", "content": system_prompt}],
        litellm_model,
    )
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
    raw_messages = [
        conversation_message_to_llm_message(message) for message in conversation
    ]
    trimmed = trim_conversation_for_context(
        raw_messages,
        max_tokens=conversation_budget,
        litellm_model=litellm_model,
    )
    return PreparedPromptMessages(
        llm_messages=[{"role": "system", "content": system_prompt}, *trimmed],
        system_prompt_hash=stable_hash(system_prompt),
        conversation_budget_tokens=conversation_budget,
        trimmed_message_count=len(trimmed),
        system_prompt_chars=len(system_prompt),
    )


def compute_conversation_token_budget(
    *,
    litellm_model: str | None,
    model_max_input_tokens: int | None,
    system_prompt_tokens: int,
    max_output_tokens: int,
    safety_buffer_tokens: int,
    minimum_budget_tokens: int,
    unknown_model_context_window_tokens: int | None = None,
) -> int:
    defaults = None
    if litellm_model:
        bare_name = litellm_model.split("/", 1)[-1] if "/" in litellm_model else None
        defaults = lookup_model_defaults(litellm_model, bare_name)

    context_window = (
        (defaults.max_input_tokens if defaults else None)
        or model_max_input_tokens
        or unknown_model_context_window_tokens
    )
    if context_window is None:
        raise ValueError("Planner model has no known context window.")

    budget = (
        context_window - system_prompt_tokens - max_output_tokens - safety_buffer_tokens
    )
    return max(budget, minimum_budget_tokens)


def trim_conversation_for_context(
    messages: list[_MessageT],
    *,
    max_tokens: int,
    litellm_model: str = "",
) -> list[_MessageT]:
    if max_tokens >= _count_group_tokens(messages, litellm_model):
        return list(messages)

    groups: list[list[_MessageT]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        group = [message]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            tool_index = index + 1
            while (
                tool_index < len(messages)
                and messages[tool_index].get("role") == "tool"
            ):
                group.append(messages[tool_index])
                tool_index += 1
            index = tool_index
        else:
            index += 1
        groups.append(group)

    kept_groups: list[list[_MessageT]] = []
    consumed_tokens = 0
    for group in reversed(groups):
        group_tokens = _count_group_tokens(group, litellm_model)
        if kept_groups and consumed_tokens + group_tokens > max_tokens:
            break
        kept_groups.append(group)
        consumed_tokens += group_tokens

    kept_groups.reverse()
    trimmed: list[_MessageT] = []
    for group in kept_groups:
        trimmed.extend(group)
    return trimmed


def _count_group_tokens(
    group: Sequence[Mapping[str, Any]],
    litellm_model: str,
) -> int:
    return count_message_tokens([dict(message) for message in group], litellm_model)


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

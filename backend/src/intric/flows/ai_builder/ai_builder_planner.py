from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, AsyncGenerator, cast
from uuid import UUID, uuid4

from intric.files.file_models import File
from intric.flows.ai_builder.ai_builder_action_policy import (
    PlannerActionPolicy,
    build_planner_action_policy,
)
from intric.flows.ai_builder.ai_builder_attachment_context import (
    build_ai_builder_attachment_context,
)
from intric.flows.ai_builder.ai_builder_capability_projection import (
    build_llm_prompt_context,
    render_llm_prompt_context,
)
from intric.flows.ai_builder.ai_builder_discovery import (
    build_registry_question_followup,
)
from intric.flows.ai_builder.ai_builder_discovery_followup import (
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_discovery_profile_builder import (
    build_discovery_profile,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_discovery_block_message_runtime,
)
from intric.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_DONE,
    build_error_event,
    build_requirements_summary_event,
    build_status_event,
    build_text_event,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    infer_question_answer_from_freeform,
    normalize_question_answer,
)
from intric.flows.ai_builder.ai_builder_interaction_utils import (
    looks_like_information_request,
)
from intric.flows.ai_builder.ai_builder_models import ConversationMessage, SessionStatus
from intric.flows.ai_builder.ai_builder_orchestrator import (
    AskQuestionAction,
    CommitArchitectureAction,
    ConfirmRequirementsAction,
    OrchestrationContext,
    PlannerOutput,
)
from intric.flows.ai_builder.ai_builder_plan_proposal_task import (
    build_plan_proposal_system_prompt,
)
from intric.flows.ai_builder.ai_builder_planner_turn import (
    PlannerTurnResult,
    TurnTelemetry,
    run_planner_turn,
)
from intric.flows.ai_builder.ai_builder_prompts import (
    build_available_kbs_context,
    build_available_models_context,
    build_clarification_hints,
    build_flow_context,
    build_system_prompt,
    compute_conversation_token_budget,
    trim_conversation_for_context,
)
from intric.flows.ai_builder.ai_builder_proposal_processor import (
    AIBuilderProposalProcessor,
)
from intric.flows.ai_builder.ai_builder_question_state import (
    derive_asked_question_state,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
    latest_confirmed_requirements,
    resolve_requirements_state,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from intric.flows.ai_builder.ai_builder_semantic_adjudication import (
    adjudicate_pending_question_answer,
)
from intric.flows.ai_builder.ai_builder_server_actions import (
    build_server_planner_output,
)
from intric.flows.ai_builder.ai_builder_settings import (
    AIBuilderBudgetPolicy,
    resolve_ai_builder_budget_policy,
)
from intric.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
    build_planner_telemetry_from_turn,
)
from intric.flows.ai_builder.pattern_registry import (
    PATTERN_REGISTRY,
    PATTERN_REGISTRY_VERSION,
)
from intric.flows.ai_builder.planning_state import (
    BUILDER_SCHEMA_VERSION,
    FCM_VERSION,
    PLANNER_CONTRACT_VERSION,
    PlanningState,
)
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
    carry_forward_persisted_planner_state,
)
from intric.flows.flow_capability_manifest import CAPABILITY_REGISTRY
from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger
from intric.model_providers.domain.model_defaults import lookup_model_defaults
from intric.observability.failure_events import (
    log_failure_event,
    make_failure_fingerprint,
    schema_fingerprint,
    stable_hash,
)

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow
    from intric.users.user import UserInDB

logger = get_logger(__name__)

# Stable hash of the PlannerOutput JSON schema, computed once at import so
# turn-metrics logs carry the contract shape under which a turn ran. A
# silent Pydantic-schema drift — say, a field becoming optional, or an
# enum gaining a value — flips this hash and shows up as a population
# shift in log queries, making schema drift diagnosable without running
# a diff against an older deploy.
_PLANNER_OUTPUT_SCHEMA_HASH: str = schema_fingerprint(PlannerOutput.model_json_schema())

# Core architectural slots that MUST resolve before `commit_architecture`
# can land. The stricter pattern-specific gate runs inside the orchestrator
# against `commit.chosen_patterns.required_architectural_slots` once the
# planner has declared which patterns it's committing to.
_CORE_ARCHITECTURAL_SLOTS: frozenset[str] = frozenset(
    {"primary_runtime_input", "terminal_output"}
)

_SERVER_SLOT_TO_DISCOVERY_QUESTION_ID: dict[str, str] = {
    "primary_runtime_input": "input_material_mode",
    "terminal_output": "final_output_mode",
}


def _compute_unresolved_core_slots(
    planning_state: PlanningState,
) -> frozenset[str]:
    """Conservative commit gate: which core slots are still unresolved.

    Both the prompt-side phase lock (rendered into the system prompt by
    `build_system_prompt`) and the orchestrator-side rejection
    (`_check_commit_architecture`) consume this same predicate, so the
    surface the LLM sees and the surface that rejects it can never
    disagree on which slots block commit.
    """
    resolved = frozenset(planning_state.resolved_slots.keys())
    return _CORE_ARCHITECTURAL_SLOTS - resolved


def _discovery_question_id_for_server_slot(slot_name: str) -> str:
    return _SERVER_SLOT_TO_DISCOVERY_QUESTION_ID.get(slot_name, slot_name)


@dataclass(frozen=True)
class PlannerMetadataResolution:
    metadata: dict[str, Any] | None
    is_requirements_confirmation: bool
    used_auxiliary_llm: bool


@dataclass(frozen=True)
class PlannerPreparedRequest:
    requirements_state: Any
    ui_language: str | None
    discovery_block_message: str | None
    llm_messages: list[dict[str, Any]]
    # Free-discovery escape valve: when the planner has been in
    # open-ended discovery for two turns without a structured answer
    # AND the MVS forced-followup catalog has a priority question
    # waiting, `send_message` yields the backend-owned followup before
    # invoking the planner LLM. Computed once per turn alongside the
    # other prompt-context signals.
    should_emit_forced_followup: bool
    # Rebuilt-from-current-conversation planning state — the same one
    # the capability projection rendered into the system prompt.
    # `send_message` derives the `OrchestrationContext` slot sets from
    # this so the model and the orchestrator evaluate against identical
    # resolved_slots; using the persisted (pre-turn) state here would
    # reject `commit_architecture` one turn after the user resolved the
    # last core slot even though the prompt already shows it resolved.
    rebuilt_planning_state: PlanningState | None = None
    # Server-owned legal action surface for this exact prompt/context.
    action_policy: PlannerActionPolicy | None = None
    # Deterministic server-owned planner output for ask/commit turns.
    # When populated, `send_message` dispatches this output directly and
    # skips the planner LLM contract entirely.
    server_output: PlannerOutput | None = None
    # Stable hash of the assembled system prompt, computed where the
    # prompt is built so the hash is tied to the literal bytes. Logging
    # it out of the prepared request instead of re-walking
    # `llm_messages` at log time keeps the hash honest if future
    # assembly inserts non-system messages ahead of the system turn.
    system_prompt_hash: str = ""
    # Plan proposal is a separate task-specific LLM boundary. The
    # server has already selected `propose_plan`; the model only fills
    # create/edit tool content, never the planner union.
    proposal_mode: bool = False


class AIBuilderPlanner:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        litellm_client: Any,
        discovery_temperature: float = 0.6,
        planner_temperature: float = 0.4,
        self_correction_temperature: float = 0.35,
        self_correction_bumped_temperature: float = 0.6,
        forced_proposal_temperature: float = 0.1,
        quality_retry_warning_codes: set[str],
    ) -> None:
        self.user = user
        self.repo = repo
        self.litellm_client = litellm_client
        self.discovery_temperature = discovery_temperature
        self.planner_temperature = planner_temperature
        self.proposal_processor = AIBuilderProposalProcessor(
            user=user,
            repo=repo,
            litellm_client=litellm_client,
            self_correction_temperature=self_correction_temperature,
            self_correction_bumped_temperature=self_correction_bumped_temperature,
            forced_proposal_temperature=forced_proposal_temperature,
            quality_retry_warning_codes=quality_retry_warning_codes,
        )

    @staticmethod
    def conversation_msg_to_llm_dict(msg: ConversationMessage) -> dict[str, Any]:
        content = msg.content
        metadata = msg.metadata if isinstance(msg.metadata, dict) else None
        question_answer = metadata.get("question_answer") if metadata else None
        if msg.role == "user" and isinstance(question_answer, dict):
            question_answer = normalize_question_answer(
                cast(dict[str, Any], question_answer)
            )
            sanitized_answer = {
                key: value
                for key, value in question_answer.items()
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

        payload: dict[str, Any] = {"role": msg.role, "content": content}
        if msg.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tool_call["id"],
                    "type": "function",
                    "function": {
                        "name": tool_call["name"],
                        "arguments": (
                            json.dumps(tool_call["arguments"])
                            if isinstance(tool_call["arguments"], dict)
                            else tool_call["arguments"]
                        ),
                    },
                }
                for tool_call in msg.tool_calls
            ]
        if msg.tool_call_id:
            payload["tool_call_id"] = msg.tool_call_id
        return payload

    @staticmethod
    def _send_lock_lease_seconds() -> int:
        return max(30, int(get_settings().ai_builder_send_lock_lease_seconds))

    @classmethod
    def _next_send_lock_expiry(cls) -> datetime:
        return datetime.now(timezone.utc) + timedelta(
            seconds=cls._send_lock_lease_seconds()
        )

    @classmethod
    def _send_lock_refresh_interval_seconds(cls) -> int:
        return max(5, cls._send_lock_lease_seconds() // 3)

    async def _maintain_send_lock_lease(
        self,
        *,
        session_id: UUID,
        request_id: UUID,
        lock_token: UUID,
        stop_event: asyncio.Event,
        lease_lost_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self._send_lock_refresh_interval_seconds(),
                )
                return
            except asyncio.TimeoutError:
                try:
                    refreshed = await self.repo.refresh_session_send_lease(
                        session_id=session_id,
                        tenant_id=self.user.tenant_id,
                        request_id=request_id,
                        lock_token=lock_token,
                        lock_expires_at=self._next_send_lock_expiry(),
                    )
                except Exception as error:
                    logger.warning(
                        "AI Builder send lease refresh failed.",
                        exc_info=error,
                        extra={
                            "session_id": str(session_id),
                            "request_id": str(request_id),
                        },
                    )
                    lease_lost_event.set()
                    return

                if not refreshed:
                    logger.warning(
                        "AI Builder send lease lost while processing.",
                        extra={
                            "session_id": str(session_id),
                            "request_id": str(request_id),
                        },
                    )
                    lease_lost_event.set()
                    return

    async def _resolve_message_metadata(
        self,
        *,
        conversation: list[ConversationMessage],
        message: str,
        question_answer: dict[str, Any] | None,
        ui_language: str | None = None,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
    ) -> PlannerMetadataResolution:
        if ui_language is None and question_answer is not None:
            raw_ui_language = question_answer.get("ui_language")
            if isinstance(raw_ui_language, str) and raw_ui_language:
                ui_language = raw_ui_language

        is_requirements_confirmation = (
            question_answer is not None
            and question_answer.get("requirements_confirmed") is True
        )
        metadata: dict[str, Any] | None = None
        if is_requirements_confirmation and question_answer is not None:
            metadata = {
                "requirements_confirmed": True,
                "requirements_version": question_answer.get("requirements_version"),
            }
        elif question_answer:
            metadata = {"question_answer": normalize_question_answer(question_answer)}

        used_auxiliary_llm = False
        if metadata is None and not is_requirements_confirmation:
            inferred_answer = infer_question_answer_from_freeform(conversation, message)
            if inferred_answer is not None:
                metadata = {"question_answer": inferred_answer}
            else:
                adjudicated_answer = await adjudicate_pending_question_answer(
                    litellm_client=self.litellm_client,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    conversation=conversation,
                    user_message=message,
                )
                if adjudicated_answer is not None:
                    metadata = {"question_answer": adjudicated_answer}
                used_auxiliary_llm = True

        if ui_language is not None:
            metadata = {
                **(metadata or {}),
                "ui_language": ui_language,
            }

        return PlannerMetadataResolution(
            metadata=metadata,
            is_requirements_confirmation=is_requirements_confirmation,
            used_auxiliary_llm=used_auxiliary_llm,
        )

    def _should_emit_forced_followup(
        self,
        *,
        conversation: list[ConversationMessage],
        requirements_confirmed: bool,
        is_requirements_confirmation: bool,
        discovery_block_message: str | None,
        discovery_analysis: Any,
        flow: "Flow | None",
    ) -> bool:
        """Arm the backend-owned followup when discovery has stalled.

        Returns ``True`` when the planner has been in open-ended
        discovery for at least two consecutive turns without a
        structured answer AND the MVS forced-followup catalog has a
        priority question waiting. Caller emits the backend-owned
        followup prior to invoking the planner LLM, short-circuiting
        another free-discovery turn that the LLM is unlikely to
        recover from on its own.
        """
        is_free_discovery = (
            not requirements_confirmed
            and not is_requirements_confirmation
            and not discovery_analysis.mvs_met
            and discovery_block_message is None
        )
        if not is_free_discovery:
            return False
        if _count_free_discovery_turns(conversation) < 2:
            return False
        return _get_mvs_forced_followup(conversation, flow=flow) is not None

    async def _prepare_planner_request(
        self,
        *,
        conversation: list[ConversationMessage],
        message: str,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_models: list[dict[str, Any]] | None,
        available_kbs: list[dict[str, Any]] | None,
        flow: "Flow | None",
        assistant_snapshots: dict[UUID, dict[str, Any]] | None,
        attachment_files: list[File] | None = None,
        max_input_tokens: int,
        max_output_tokens: int,
        budget_policy: AIBuilderBudgetPolicy,
        is_requirements_confirmation: bool,
        allow_discovery_semantic_adjudication: bool = True,
        persisted_planning_state: PlanningState | None = None,
        base_planning_state_version: int | None = None,
    ) -> PlannerPreparedRequest:
        requirements_state = resolve_requirements_state(conversation)
        has_requirements_summary = requirements_state.latest_summary is not None
        ui_language = _resolve_ui_language(conversation)
        (
            discovery_block_message,
            discovery_analysis,
        ) = await build_discovery_block_message_runtime(
            conversation,
            flow=flow,
            litellm_client=self.litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            ui_language=ui_language,
            allow_semantic_adjudication=allow_discovery_semantic_adjudication,
        )

        is_edit_mode = flow is not None
        flow_context = None
        if flow is not None:
            discovery_profile = build_discovery_profile(conversation, flow=flow)
            flow_context = build_flow_context(
                flow,
                assistant_snapshots=assistant_snapshots,
                is_edit_mode=True,
                capabilities=discovery_profile.capabilities,
                edit_scope=discovery_profile.edit_scope,
            )

        models_ctx = (
            build_available_models_context(available_models)
            if available_models
            else None
        )
        kbs_ctx = build_available_kbs_context(available_kbs) if available_kbs else None
        clarification_hints = build_clarification_hints(
            conversation=conversation,
            latest_user_message=message,
            flow=flow,
        )
        rebuilt_planning_state = build_planning_state_from_conversation(
            conversation,
            flow=flow,
        )
        carry_forward_persisted_planner_state(
            rebuilt_planning_state, persisted_planning_state
        )
        unresolved_architectural_choices = _compute_unresolved_core_slots(
            rebuilt_planning_state
        )
        selected_discovery_question_ids = frozenset(
            getattr(discovery_analysis, "selected_question_ids", ())
        )
        action_policy = build_planner_action_policy(
            session_state=rebuilt_planning_state,
            unresolved_architectural_choices=unresolved_architectural_choices,
            selected_discovery_question_ids=selected_discovery_question_ids,
            requirements_confirmed=requirements_state.confirmed,
        )
        should_emit_forced_followup = self._should_emit_forced_followup(
            conversation=conversation,
            requirements_confirmed=requirements_state.confirmed,
            is_requirements_confirmation=is_requirements_confirmation,
            discovery_block_message=discovery_block_message,
            discovery_analysis=discovery_analysis,
            flow=flow,
        )
        server_output = (
            build_server_planner_output(
                action_policy=action_policy,
                session_state=rebuilt_planning_state,
                base_planning_state_version=base_planning_state_version,
                ui_language=ui_language,
            )
            if base_planning_state_version is not None
            else None
        )
        confirmed_requirements = latest_confirmed_requirements(conversation)
        attachment_context_result = build_ai_builder_attachment_context(
            attachment_files or []
        )
        if server_output is not None:
            return PlannerPreparedRequest(
                requirements_state=requirements_state,
                ui_language=ui_language,
                discovery_block_message=None,
                llm_messages=[],
                should_emit_forced_followup=False,
                rebuilt_planning_state=rebuilt_planning_state,
                action_policy=action_policy,
                server_output=server_output,
            )

        if action_policy.allowed_action_kinds == ("propose_plan",):
            proposal_system_prompt = build_plan_proposal_system_prompt(
                planning_state=rebuilt_planning_state,
                confirmed_requirements=(
                    confirmed_requirements.model_dump(mode="json")
                    if confirmed_requirements is not None
                    else None
                ),
                attachment_context=(
                    attachment_context_result.context
                    if attachment_context_result is not None
                    else None
                ),
                flow_context=flow_context,
                is_edit_mode=is_edit_mode,
            )
            proposal_prompt_tokens = max(1, len(proposal_system_prompt) // 3)
            proposal_budget = compute_conversation_token_budget(
                litellm_model=litellm_model,
                model_max_input_tokens=max_input_tokens,
                system_prompt_tokens=proposal_prompt_tokens,
                max_output_tokens=max_output_tokens,
                safety_buffer_tokens=budget_policy.conversation_safety_buffer_tokens,
                minimum_budget_tokens=budget_policy.minimum_conversation_budget_tokens,
                unknown_model_context_window_tokens=budget_policy.unknown_model_context_window_tokens,
            )
            trimmed = trim_conversation_for_context(
                [
                    self.conversation_msg_to_llm_dict(message)
                    for message in conversation
                ],
                max_tokens=proposal_budget,
            )
            logger.info(
                "AI Builder plan proposal prompt metrics",
                extra={
                    "system_prompt_chars": len(proposal_system_prompt),
                    "attachment_context_chars": len(
                        attachment_context_result.context
                        if attachment_context_result is not None
                        else ""
                    ),
                    "conversation_budget_tokens": proposal_budget,
                    "conversation_message_count": len(conversation),
                    "trimmed_message_count": len(trimmed),
                    "attachment_file_count": len(attachment_files or []),
                    "confirmed_requirements_present": confirmed_requirements
                    is not None,
                },
            )
            return PlannerPreparedRequest(
                requirements_state=requirements_state,
                ui_language=ui_language,
                discovery_block_message=discovery_block_message,
                llm_messages=[
                    {"role": "system", "content": proposal_system_prompt},
                    *trimmed,
                ],
                should_emit_forced_followup=should_emit_forced_followup,
                rebuilt_planning_state=rebuilt_planning_state,
                action_policy=action_policy,
                system_prompt_hash=stable_hash(proposal_system_prompt),
                proposal_mode=True,
            )

        planning_state_block = render_llm_prompt_context(
            build_llm_prompt_context(
                rebuilt_planning_state,
                CAPABILITY_REGISTRY,
                PATTERN_REGISTRY,
            )
        )
        system_prompt = build_system_prompt(
            flow_context=flow_context,
            available_models=models_ctx,
            available_knowledge_bases=kbs_ctx,
            attachment_context=(
                attachment_context_result.context
                if attachment_context_result is not None
                else None
            ),
            planner_hints=clarification_hints,
            planning_state_block=planning_state_block,
            base_planning_state_version=base_planning_state_version,
            ui_language=ui_language,
            confirmed_requirements=(
                confirmed_requirements.model_dump(mode="json")
                if confirmed_requirements is not None
                else None
            ),
            is_edit_mode=is_edit_mode,
            unresolved_architectural_choices=unresolved_architectural_choices,
            action_policy=action_policy,
        )
        system_prompt_tokens = max(1, len(system_prompt) // 3)
        conversation_budget = compute_conversation_token_budget(
            litellm_model=litellm_model,
            model_max_input_tokens=max_input_tokens,
            system_prompt_tokens=system_prompt_tokens,
            max_output_tokens=max_output_tokens,
            safety_buffer_tokens=budget_policy.conversation_safety_buffer_tokens,
            minimum_budget_tokens=budget_policy.minimum_conversation_budget_tokens,
            unknown_model_context_window_tokens=budget_policy.unknown_model_context_window_tokens,
        )
        trimmed = trim_conversation_for_context(
            [self.conversation_msg_to_llm_dict(message) for message in conversation],
            max_tokens=conversation_budget,
        )
        logger.info(
            "AI Builder planner prompt metrics",
            extra={
                "system_prompt_chars": len(system_prompt),
                "flow_context_chars": len(flow_context or ""),
                "attachment_context_chars": len(
                    attachment_context_result.context
                    if attachment_context_result is not None
                    else ""
                ),
                "available_models_count": len(models_ctx or []),
                "available_kbs_count": len(kbs_ctx or []),
                "conversation_budget_tokens": conversation_budget,
                "conversation_message_count": len(conversation),
                "trimmed_message_count": len(trimmed),
                "attachment_file_count": len(attachment_files or []),
                "discovery_semantic_enabled": allow_discovery_semantic_adjudication,
                "confirmed_requirements_present": confirmed_requirements is not None,
            },
        )

        if (
            not has_requirements_summary
            and not requirements_state.confirmed
            and not is_requirements_confirmation
            and not looks_like_information_request(message)
            and discovery_block_message is not None
        ):
            return PlannerPreparedRequest(
                requirements_state=requirements_state,
                ui_language=ui_language,
                discovery_block_message=discovery_block_message,
                llm_messages=[],
                should_emit_forced_followup=should_emit_forced_followup,
                rebuilt_planning_state=rebuilt_planning_state,
                action_policy=action_policy,
            )

        return PlannerPreparedRequest(
            requirements_state=requirements_state,
            ui_language=ui_language,
            discovery_block_message=discovery_block_message,
            llm_messages=[{"role": "system", "content": system_prompt}] + trimmed,
            should_emit_forced_followup=should_emit_forced_followup,
            rebuilt_planning_state=rebuilt_planning_state,
            action_policy=action_policy,
            system_prompt_hash=stable_hash(system_prompt),
        )

    async def _dispatch_chained_server_action_after_commit(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        flow: "Flow | None",
        base_planning_state_version: int,
        requirements_confirmed: bool,
        ui_language: str | None,
        request_id: str,
        request_uuid: UUID,
        lock_token: UUID,
    ) -> PlannerTurnResult | None:
        """Advance one deterministic post-commit server action.

        `commit_architecture` is a backend state transition, not a useful
        terminal user-facing response. After that transition persists, the
        next legal deterministic phase is usually `confirm_requirements`;
        dispatch it in the same request so the UI lands on an actionable
        review checkpoint instead of a bare commit status.
        """

        persisted_state = await self.repo.load_planning_state(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )
        session_state = persisted_state or PlanningState.empty()
        unresolved_core_slots = _compute_unresolved_core_slots(session_state)
        action_policy = build_planner_action_policy(
            session_state=session_state,
            unresolved_architectural_choices=unresolved_core_slots,
            selected_discovery_question_ids=frozenset(),
            requirements_confirmed=requirements_confirmed,
        )
        server_output = build_server_planner_output(
            action_policy=action_policy,
            session_state=session_state,
            base_planning_state_version=base_planning_state_version,
            ui_language=ui_language,
        )
        if server_output is None or not isinstance(
            server_output.planner_action, ConfirmRequirementsAction
        ):
            return None

        resolved_slot_names = frozenset(session_state.resolved_slots.keys())
        required_slot_names = (
            frozenset(action_policy.allowed_ask_question_targets)
            - unresolved_core_slots
            - resolved_slot_names
        )
        asked_question_state = derive_asked_question_state(conversation)
        orchestration_context = OrchestrationContext(
            current_version=base_planning_state_version,
            session_state=session_state,
            unresolved_architectural_choices=unresolved_core_slots,
            required_slot_names=required_slot_names,
            asked_question_ids=asked_question_state.asked_question_ids,
            has_new_evidence=asked_question_state.has_new_evidence,
            question_ids_with_new_evidence=(
                asked_question_state.question_ids_with_new_evidence
            ),
            action_policy=action_policy,
        )

        def _build_chained_messages(
            accepted: PlannerOutput,
            telemetry: TurnTelemetry,
        ) -> list[ConversationMessage]:
            action = accepted.planner_action
            if not isinstance(action, ConfirmRequirementsAction):
                raise AssertionError(
                    "post-commit chained server action must be confirm_requirements"
                )
            requirements_payload = RequirementsSummaryPayload.model_validate(
                action.payload.model_dump()
            )
            base_metadata = {
                "requirements_summary": requirements_payload.model_dump(mode="json"),
                "requirements_version": build_requirements_version(
                    requirements_payload
                ),
            }
            planner_telemetry = build_planner_telemetry_from_turn(
                telemetry,
                used_auxiliary_llm=False,
            )
            return [
                ConversationMessage(
                    role="assistant",
                    content=action.payload.summary,
                    metadata=build_assistant_message_metadata(
                        conversation,
                        planner_telemetry=planner_telemetry,
                        base_metadata=base_metadata,
                    ),
                )
            ]

        return await run_planner_turn(
            repo=self.repo,
            litellm_client=self.litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs={
                **litellm_kwargs,
                "max_tokens": 1,
                "temperature": self.planner_temperature,
                "response_format": {"type": "json_object"},
                "drop_params": True,
            },
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            flow=flow,
            base_messages=[],
            orchestration_context=orchestration_context,
            build_new_messages=_build_chained_messages,
            precomputed_output=server_output,
            request_id=request_uuid,
            lock_token=lock_token,
        )

    async def _dispatch_server_question(
        self,
        *,
        action: AskQuestionAction,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        flow: "Flow | None",
        request_uuid: UUID,
        lock_token: UUID,
    ) -> list[dict[str, str]]:
        """Persist deterministic questions through the structured-question path.

        Server-selected questions must look exactly like discovery follow-ups to
        the UI and to the conversation replay layer. Emitting only a text event
        leaves the user without an actionable card and prevents free-form answer
        inference from seeing the pending question.
        """

        question_id = _discovery_question_id_for_server_slot(action.payload.slot_name)
        followup = build_registry_question_followup(
            question_id,
            conversation,
            flow=flow,
        )
        if followup is None:
            return [build_text_event(action.payload.prompt)]

        question_data, assistant_text = followup
        return await persist_backend_question(
            repo=self.repo,
            tenant_id=self.user.tenant_id,
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            question_data=question_data,
            assistant_text=assistant_text,
            flow=flow,
            assistant_metadata=build_assistant_message_metadata(
                conversation,
                tool_calls=[{"name": "ask_structured_question"}],
            ),
            lease_request_id=request_uuid,
            lease_lock_token=lock_token,
        )

    async def send_message(
        self,
        *,
        session_id: UUID,
        message: str,
        file_ids: list[UUID] | None = None,
        question_answer: dict[str, Any] | None = None,
        ui_language: str | None = None,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_models: list[dict[str, Any]] | None = None,
        available_kbs: list[dict[str, Any]] | None = None,
        flow: "Flow | None" = None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
        attachment_files: list[File] | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        budget_policy: AIBuilderBudgetPolicy | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        if budget_policy is None:
            budget_policy = resolve_ai_builder_budget_policy(None)

        bare_name = litellm_model.split("/", 1)[-1] if "/" in litellm_model else None
        defaults = lookup_model_defaults(litellm_model, bare_name)

        if max_input_tokens is None:
            max_input_tokens = (
                defaults.max_input_tokens if defaults else None
            ) or budget_policy.unknown_model_context_window_tokens
        if max_output_tokens is None:
            max_output_tokens = defaults.max_output_tokens if defaults else None

        if max_input_tokens is None or max_output_tokens is None:
            raise BadRequestException(
                "AI Builder planner budget settings are missing.",
                code="planner_budget_missing",
            )

        session = await self.repo.get_session(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )
        request_id = str(uuid4())
        request_uuid = UUID(request_id)
        lock_token = uuid4()
        lease_stop_event = asyncio.Event()
        lease_lost_event = asyncio.Event()
        claimed = await self.repo.claim_session_send(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            request_id=request_uuid,
            lock_token=lock_token,
            lock_expires_at=self._next_send_lock_expiry(),
        )
        if not claimed:
            raise BadRequestException(
                "Another AI Builder message is already being processed for this session.",
                code="session_message_in_progress",
            )
        lease_task = asyncio.create_task(
            self._maintain_send_lock_lease(
                session_id=session_id,
                request_id=request_uuid,
                lock_token=lock_token,
                stop_event=lease_stop_event,
                lease_lost_event=lease_lost_event,
            )
        )

        try:
            if session.status not in (
                SessionStatus.CHATTING,
                SessionStatus.AWAITING_APPROVAL,
            ):
                raise BadRequestException(
                    f"Cannot send messages in session status '{session.status.value}'."
                )

            if session.status == SessionStatus.AWAITING_APPROVAL:
                await self.repo.update_session_status(
                    session_id=session_id,
                    tenant_id=self.user.tenant_id,
                    status=SessionStatus.CHATTING,
                )

            conversation = list(session.conversation)
            persisted_planning_state = await self.repo.load_planning_state(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
            )
            metadata_resolution = await self._resolve_message_metadata(
                conversation=conversation,
                message=message,
                question_answer=question_answer,
                ui_language=ui_language,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
            )
            metadata = metadata_resolution.metadata
            is_requirements_confirmation = (
                metadata_resolution.is_requirements_confirmation
            )

            user_message = ConversationMessage(
                role="user",
                content=message,
                metadata=(
                    {
                        **(metadata or {}),
                        **(
                            {"file_ids": [str(file_id) for file_id in file_ids]}
                            if file_ids
                            else {}
                        ),
                    }
                    if metadata or file_ids
                    else None
                ),
            )
            new_messages_start = len(conversation)
            conversation.append(user_message)
            prepared_request = await self._prepare_planner_request(
                conversation=conversation,
                message=message,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                available_models=available_models,
                available_kbs=available_kbs,
                flow=flow,
                assistant_snapshots=assistant_snapshots,
                attachment_files=attachment_files or [],
                max_input_tokens=max_input_tokens,
                max_output_tokens=max_output_tokens,
                budget_policy=budget_policy,
                is_requirements_confirmation=is_requirements_confirmation,
                allow_discovery_semantic_adjudication=not metadata_resolution.used_auxiliary_llm,
                persisted_planning_state=persisted_planning_state,
                base_planning_state_version=session.planning_state_version,
            )
            requirements_state = prepared_request.requirements_state
            ui_language = prepared_request.ui_language

            if (
                prepared_request.server_output is None
                and not prepared_request.llm_messages
                and prepared_request.discovery_block_message is not None
            ):
                for (
                    event
                ) in await self.proposal_processor.emit_discovery_followup_if_needed(
                    session_id=session_id,
                    conversation=conversation,
                    new_messages_start=new_messages_start,
                    flow=flow,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    ui_language=ui_language,
                    assistant_metadata=build_assistant_message_metadata(
                        conversation,
                        tool_calls=[{"name": "ask_structured_question"}],
                    ),
                    lease_request_id=request_uuid,
                    lease_lock_token=lock_token,
                ):
                    yield event
                yield {"event": SSE_EVENT_DONE, "data": ""}
                return

            if (
                prepared_request.server_output is None
                and prepared_request.should_emit_forced_followup
            ):
                for (
                    event
                ) in await self.proposal_processor.emit_discovery_followup_if_needed(
                    session_id=session_id,
                    conversation=conversation,
                    new_messages_start=new_messages_start,
                    flow=flow,
                    assistant_metadata=build_assistant_message_metadata(
                        conversation,
                        tool_calls=[{"name": "ask_structured_question"}],
                    ),
                    lease_request_id=request_uuid,
                    lease_lock_token=lock_token,
                ):
                    yield event
                yield {"event": SSE_EVENT_DONE, "data": ""}
                return

            # Use the SAME planning state the projection rendered into the
            # prompt. `persisted_planning_state` is pre-turn; the projection
            # rebuilds from the current conversation (including the user
            # message that just landed) and only then carries persisted
            # planner-owned fields forward. Feeding pre-turn state here
            # would reject `commit_architecture` one turn after the user
            # resolved the last core slot — the prompt shows it resolved,
            # the orchestrator still blocks.
            session_state = (
                prepared_request.rebuilt_planning_state
                or persisted_planning_state
                or PlanningState.empty()
            )
            resolved_slot_names = frozenset(session_state.resolved_slots.keys())
            unresolved_core_slots = _compute_unresolved_core_slots(session_state)
            action_policy = prepared_request.action_policy
            if action_policy is None:
                action_policy = build_planner_action_policy(
                    session_state=session_state,
                    unresolved_architectural_choices=unresolved_core_slots,
                    selected_discovery_question_ids=frozenset(),
                    requirements_confirmed=requirements_state.confirmed,
                )
            # Compatibility surface for older tests/callers; the action
            # policy is authoritative and already excludes resolved slots.
            required_slot_names = (
                frozenset(action_policy.allowed_ask_question_targets)
                - unresolved_core_slots
                - resolved_slot_names
            )
            asked_question_state = derive_asked_question_state(conversation)
            orchestration_context = OrchestrationContext(
                current_version=session.planning_state_version,
                session_state=session_state,
                unresolved_architectural_choices=unresolved_core_slots,
                required_slot_names=required_slot_names,
                asked_question_ids=asked_question_state.asked_question_ids,
                has_new_evidence=asked_question_state.has_new_evidence,
                question_ids_with_new_evidence=(
                    asked_question_state.question_ids_with_new_evidence
                ),
                action_policy=action_policy,
            )

            if prepared_request.server_output is not None and isinstance(
                prepared_request.server_output.planner_action,
                AskQuestionAction,
            ):
                events = await self._dispatch_server_question(
                    action=prepared_request.server_output.planner_action,
                    session_id=session_id,
                    conversation=conversation,
                    new_messages_start=new_messages_start,
                    flow=flow,
                    request_uuid=request_uuid,
                    lock_token=lock_token,
                )
                for event in events:
                    yield event
                yield {"event": SSE_EVENT_DONE, "data": ""}
                return

            if prepared_request.proposal_mode:
                resource_catalog = build_ai_builder_resource_catalog(
                    available_models=available_models,
                    available_kbs=available_kbs,
                )
                async for event in self.proposal_processor.propose_plan(
                    session_id=session_id,
                    conversation=conversation,
                    new_messages_start=new_messages_start,
                    llm_messages=prepared_request.llm_messages,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    available_models=available_models,
                    available_kbs=available_kbs,
                    available_model_refs=resource_catalog.model_refs,
                    available_kb_refs=resource_catalog.knowledge_base_refs,
                    resource_catalog=resource_catalog,
                    max_output_tokens=max_output_tokens,
                    proposal_temperature=self.planner_temperature,
                    request_id=request_id,
                    flow=flow,
                    assistant_snapshots=assistant_snapshots,
                    assistant_metadata=build_assistant_message_metadata(conversation),
                    planning_state=session_state,
                    lease_request_id=request_uuid,
                    lease_lock_token=lock_token,
                ):
                    yield event
                yield {"event": SSE_EVENT_DONE, "data": ""}
                return

            def _build_new_messages(
                accepted: PlannerOutput,
                telemetry: TurnTelemetry,
            ) -> list[ConversationMessage]:
                action = accepted.planner_action
                base_metadata: dict[str, Any] | None = None
                if isinstance(action, AskQuestionAction):
                    assistant_content = action.payload.prompt
                    # Persist the question_id so a future turn's
                    # OrchestrationContext can derive asked_question_ids
                    # and block the LLM from repeating the same question
                    # without new evidence.
                    base_metadata = {"question_id": action.payload.question_id}
                elif isinstance(action, CommitArchitectureAction):
                    return [*conversation[new_messages_start:]]
                else:
                    assistant_content = action.payload.summary
                    requirements_payload = RequirementsSummaryPayload.model_validate(
                        action.payload.model_dump()
                    )
                    base_metadata = {
                        "requirements_summary": requirements_payload.model_dump(
                            mode="json"
                        ),
                        "requirements_version": build_requirements_version(
                            requirements_payload
                        ),
                    }
                planner_telemetry = build_planner_telemetry_from_turn(
                    telemetry,
                    used_auxiliary_llm=metadata_resolution.used_auxiliary_llm,
                )
                return [
                    *conversation[new_messages_start:],
                    ConversationMessage(
                        role="assistant",
                        content=assistant_content,
                        metadata=build_assistant_message_metadata(
                            conversation,
                            planner_telemetry=planner_telemetry,
                            base_metadata=base_metadata,
                        ),
                    ),
                ]

            precomputed_output = prepared_request.server_output

            try:
                turn_result = await run_planner_turn(
                    repo=self.repo,
                    litellm_client=self.litellm_client,
                    litellm_model=litellm_model,
                    litellm_kwargs={
                        **litellm_kwargs,
                        "max_tokens": max_output_tokens,
                        "temperature": (
                            self.discovery_temperature
                            if not requirements_state.confirmed
                            else self.planner_temperature
                        ),
                        "response_format": {"type": "json_object"},
                        # `drop_params=True` lets litellm silently strip
                        # `response_format` for providers that don't support
                        # JSON mode, turning an unsupported-param provider
                        # error into a plain completion the pipeline still
                        # parses. Without this the v1 fallback path was
                        # lost.
                        "drop_params": True,
                    },
                    session_id=session_id,
                    tenant_id=self.user.tenant_id,
                    flow=flow,
                    base_messages=prepared_request.llm_messages,
                    orchestration_context=orchestration_context,
                    build_new_messages=_build_new_messages,
                    precomputed_output=precomputed_output,
                    request_id=request_uuid,
                    lock_token=lock_token,
                )
            except BadRequestException as error:
                if error.code == "session_send_lease_lost":
                    yield build_error_event(
                        message=(
                            "The AI Builder session lock was lost while the "
                            "planner was running. Please try again."
                        ),
                        code="session_send_lease_lost",
                        phase="planner",
                        request_id=request_id,
                    )
                    yield {"event": SSE_EVENT_DONE, "data": ""}
                    return
                raise
            except Exception as error:
                logger.error(
                    "AI Builder planner turn failed",
                    exc_info=error,
                    extra={"request_id": request_id},
                )
                yield build_error_event(
                    message="The AI planner failed. Please try again.",
                    code="planner_upstream_error",
                    phase="planner",
                    request_id=request_id,
                )
                yield {"event": SSE_EVENT_DONE, "data": ""}
                return

            if lease_lost_event.is_set():
                yield build_error_event(
                    message=(
                        "The AI Builder session lock was lost while the planner "
                        "was running. Please try again."
                    ),
                    code="session_send_lease_lost",
                    phase="planner",
                    request_id=request_id,
                )
                yield {"event": SSE_EVENT_DONE, "data": ""}
                return

            parse_failure_diagnostics: dict[str, Any] = {}
            if (
                turn_result.kind == "parse_failed"
                and turn_result.parse_failure_diagnostics is not None
            ):
                parse_failure_diagnostics = turn_result.parse_failure_diagnostics

            system_prompt_content = next(
                (
                    msg.get("content", "")
                    for msg in prepared_request.llm_messages
                    if msg.get("role") == "system"
                ),
                "",
            )
            planner_prompt_hash = stable_hash(str(system_prompt_content))
            logger.info(
                "AI Builder planner turn metrics",
                extra={
                    "outcome_kind": turn_result.kind,
                    "llm_calls_made": turn_result.llm_calls_made,
                    "repair_attempts": turn_result.repair_attempts,
                    "parse_repair_attempts": turn_result.parse_repair_attempts,
                    "architecture_commit_populated": (
                        turn_result.turn_telemetry.architecture_commit_populated
                    ),
                    "wall_clock_ms": turn_result.turn_telemetry.wall_clock_ms,
                    "prompt_tokens": turn_result.turn_telemetry.prompt_tokens,
                    "completion_tokens": (turn_result.turn_telemetry.completion_tokens),
                    "total_tokens": turn_result.turn_telemetry.total_tokens,
                    "finish_reason": turn_result.turn_telemetry.finish_reason,
                    "request_id": request_id,
                    "planner_prompt_hash": planner_prompt_hash,
                    "planner_output_schema_hash": _PLANNER_OUTPUT_SCHEMA_HASH,
                    "pattern_registry_version": PATTERN_REGISTRY_VERSION,
                    "fcm_version": FCM_VERSION,
                    "planner_contract_version": PLANNER_CONTRACT_VERSION,
                    "builder_schema_version": BUILDER_SCHEMA_VERSION,
                    "planning_state_version": session.planning_state_version,
                    "response_format_requested": "json_object",
                    "drop_params": True,
                    "json_mode_requested": True,
                    **parse_failure_diagnostics,
                },
            )

            if turn_result.kind in ("parse_failed", "rejected"):
                _emit_planner_failure_event(
                    turn_result=turn_result,
                    request_id=request_id,
                    session_id=session_id,
                    tenant_id=self.user.tenant_id,
                    planning_state_version=session.planning_state_version,
                    planner_prompt_hash=planner_prompt_hash,
                    parse_failure_diagnostics=parse_failure_diagnostics,
                )

            if turn_result.kind == "parse_failed":
                completion = turn_result.final_completion
                if completion is not None and completion.finish_reason == "length":
                    logger.warning(
                        "LLM response truncated (finish_reason=length) — "
                        f"max_tokens={max_output_tokens} may be too low for this model"
                    )
                    yield build_error_event(
                        message=(
                            "The flow was too complex for the current model's "
                            "output limit. Try simplifying the flow or using a "
                            "more capable model."
                        ),
                        code="planner_output_too_long",
                        phase="planner",
                        request_id=request_id,
                    )
                else:
                    yield build_error_event(
                        message=(
                            "The AI planner response could not be parsed. "
                            "Please try again."
                        ),
                        code="planner_parse_error",
                        phase="planner",
                        request_id=request_id,
                    )
            elif turn_result.kind == "rejected":
                yield build_error_event(
                    message=(
                        "The assistant couldn't complete that step. "
                        "Please rephrase your request or try again."
                    ),
                    code="planner_rejected",
                    phase="planner",
                    request_id=request_id,
                )
            elif turn_result.kind == "dispatched":
                assert turn_result.accepted_output is not None
                action = turn_result.accepted_output.planner_action
                if isinstance(action, AskQuestionAction):
                    yield build_text_event(action.payload.prompt)
                elif isinstance(action, CommitArchitectureAction):
                    yield build_status_event("architecture_committed")
                    if turn_result.dispatch_result is not None:
                        chained_result = await self._dispatch_chained_server_action_after_commit(
                            session_id=session_id,
                            conversation=conversation,
                            litellm_model=litellm_model,
                            litellm_kwargs=litellm_kwargs,
                            flow=flow,
                            base_planning_state_version=(
                                turn_result.dispatch_result.new_planning_state_version
                            ),
                            requirements_confirmed=requirements_state.confirmed,
                            ui_language=ui_language,
                            request_id=request_id,
                            request_uuid=request_uuid,
                            lock_token=lock_token,
                        )
                        if (
                            chained_result is not None
                            and chained_result.kind == "dispatched"
                            and chained_result.accepted_output is not None
                            and isinstance(
                                chained_result.accepted_output.planner_action,
                                ConfirmRequirementsAction,
                            )
                        ):
                            chained_action = (
                                chained_result.accepted_output.planner_action
                            )
                            confirmed_payload = (
                                RequirementsSummaryPayload.model_validate(
                                    chained_action.payload.model_dump()
                                )
                            )
                            confirmed_data = confirmed_payload.model_dump(mode="json")
                            confirmed_data["requirements_version"] = (
                                build_requirements_version(confirmed_payload)
                            )
                            yield build_requirements_summary_event(confirmed_data)
                else:
                    confirmed_payload = RequirementsSummaryPayload.model_validate(
                        action.payload.model_dump()
                    )
                    confirmed_data = confirmed_payload.model_dump(mode="json")
                    confirmed_data["requirements_version"] = build_requirements_version(
                        confirmed_payload
                    )
                    yield build_requirements_summary_event(confirmed_data)

            yield {"event": SSE_EVENT_DONE, "data": ""}
        finally:
            lease_stop_event.set()
            try:
                await lease_task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.warning(
                    "AI Builder lease task exited with an unexpected error.",
                    exc_info=error,
                    extra={"session_id": str(session_id), "request_id": request_id},
                )
            await self.repo.release_session_send(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
                request_id=request_uuid,
                lock_token=lock_token,
            )


def _extract_first_validation_loc(locs: Any) -> str | None:
    """Pull a locus string off the first entry of `validation_locs` if any.

    `summarize_parse_failure` emits `validation_locs` as a list of
    `{"loc": "...", "type": "..."}` dicts on ValidationError, or omits
    the field entirely otherwise. A single best-effort locus feeds the
    failure fingerprint; the loop is bounded at one entry because
    fingerprint stability matters more than completeness.
    """
    if not isinstance(locs, list) or not locs:
        return None
    first = cast(Any, locs[0])
    if not isinstance(first, dict):
        return None
    loc_value = cast(Any, first).get("loc")
    return None if loc_value is None else str(loc_value)


def _emit_planner_failure_event(
    *,
    turn_result: Any,
    request_id: Any,
    session_id: UUID,
    tenant_id: UUID,
    planning_state_version: int,
    planner_prompt_hash: str,
    parse_failure_diagnostics: dict[str, Any],
) -> None:
    """Emit one structured failure event per terminal non-success turn.

    The turn-metrics log carries the outcome; this adds the "why" in a
    grep-friendly shape. `failure_code` is the `RejectionCode` on
    `rejected`, or the `parse_error_kind` on `parse_failed` — the fine
    discriminator a human or an agent pivots on. `failure_fingerprint`
    clusters recurring failures by `(kind, code, locus)` so repeated
    incidents hash to the same 12-char id without carrying any raw
    body. `safe_detail` is always sanitized by upstream producers
    (`summarize_parse_failure` / `RejectionReason.detail`) — never the
    raw LLM response.
    """
    failure_kind = turn_result.kind
    failure_code: str | None = None
    fingerprint_locus: str | None = None
    safe_detail: dict[str, Any] = {}

    if failure_kind == "parse_failed":
        parse_error_kind = parse_failure_diagnostics.get("parse_error_kind")
        failure_code = str(parse_error_kind) if parse_error_kind is not None else None
        fingerprint_locus = _extract_first_validation_loc(
            parse_failure_diagnostics.get("validation_locs")
        )
        safe_detail = dict(parse_failure_diagnostics)
    elif failure_kind == "rejected" and turn_result.rejection is not None:
        rejection = turn_result.rejection
        failure_code = rejection.code
        fingerprint_locus = rejection.code
        safe_detail = {
            "rejection_code": rejection.code,
            "rejection_detail": rejection.detail,
            "current_version": rejection.current_version,
        }

    log_failure_event(
        logger,
        event="ai_builder.failure",
        component="ai_builder",
        operation="planner_turn",
        failure_kind=failure_kind,
        failure_code=failure_code,
        failure_fingerprint=make_failure_fingerprint(
            failure_kind, failure_code, fingerprint_locus
        ),
        request_id=str(request_id) if request_id is not None else None,
        session_id=str(session_id),
        tenant_id=str(tenant_id),
        replay_handle={
            "session_id": str(session_id),
            "request_id": str(request_id) if request_id is not None else None,
            "planning_state_version": planning_state_version,
            "planner_prompt_hash": planner_prompt_hash,
            "planner_output_schema_hash": _PLANNER_OUTPUT_SCHEMA_HASH,
            "pattern_registry_version": PATTERN_REGISTRY_VERSION,
            "fcm_version": FCM_VERSION,
            "planner_contract_version": PLANNER_CONTRACT_VERSION,
            "builder_schema_version": BUILDER_SCHEMA_VERSION,
        },
        safe_detail=safe_detail,
    )


def _resolve_ui_language(conversation: list[ConversationMessage]) -> str | None:
    for message in reversed(conversation):
        if message.role != "user":
            continue
        metadata = message.metadata if isinstance(message.metadata, dict) else None
        ui_language = metadata.get("ui_language") if metadata else None
        if ui_language in {"sv", "en"}:
            return ui_language
    return None


def _count_free_discovery_turns(conversation: list[ConversationMessage]) -> int:
    """Count consecutive assistant text turns without a new structured answer.

    Walks backward from the latest message. Counts assistant text messages
    that are NOT followed by a user message with a question_answer metadata.
    Stops counting at the first user message with a structured answer.
    """
    count = 0
    for msg in reversed(conversation):
        if msg.role == "assistant" and msg.content and not msg.tool_calls:
            count += 1
        elif msg.role == "user":
            metadata = msg.metadata if isinstance(msg.metadata, dict) else None
            if metadata and metadata.get("question_answer"):
                break  # Found a structured answer — stop counting
    return count


def _get_mvs_forced_followup(
    conversation: list[ConversationMessage],
    *,
    flow: "Flow | None" = None,
) -> str | None:
    """Get the highest-priority missing MVS dimension as a forced question.

    Returns a message string if a forced question should be emitted, None otherwise.
    """
    from intric.flows.ai_builder.ai_builder_discovery import build_discovery_followup

    followup = build_discovery_followup(conversation, flow=flow)
    if followup is not None:
        return followup[2]  # assistant_text
    return None

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator
from uuid import UUID

from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_ERROR,
    build_error_event,
    build_plan_event,
    build_requirements_summary_event,
    build_status_event,
    build_text_event,
    error_payload,
)
from intric.flows.ai_builder.ai_builder_discovery import build_registry_question_followup
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_discovery_block_message_runtime,
)
from intric.flows.ai_builder.ai_builder_discovery_followup import (
    emit_discovery_followup_if_needed,
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_interaction_utils import (
    analyze_discovery_ready,
    build_question_fallback_text,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    is_supported_structured_question_id,
    normalize_structured_question_payload,
)
from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    RequirementsSummaryPayload,
)
from intric.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_aware_quality_feedback,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    append_retry_feedback_turn as build_append_retry_feedback_turn,
    build_tool_retry_messages as build_proposal_tool_retry_messages,
    request_self_correction as run_request_self_correction,
    retry_forced_proposal_after_text as run_retry_forced_proposal_after_text,
)
from intric.flows.ai_builder.ai_builder_plan_store import (
    append_session_messages,
    format_revision_feedback,
    format_validation_feedback,
    store_plan_and_update_conversation,
    warnings_for_quality_retry,
)
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
    resolve_requirements_state,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    PROPOSE_FLOW_TOOL_NAME,
    build_discovery_complete_tool_schemas,
    extract_assumptions,
    extract_plan_rationale,
    extract_reasoning,
    parse_confirm_requirements,
    parse_propose_flow_arguments,
    parse_structured_question,
)
from intric.flows.ai_builder.ai_builder_edit_compiler import compile_edit_draft
from intric.flows.ai_builder.ai_builder_edit_models import FlowEditDraft
from intric.flows.ai_builder.ai_builder_edit_tool_schema import EDIT_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_edit_validator import validate_edit_draft
from intric.flows.ai_builder.ai_builder_session_spec_validator import (
    normalize_compiled_spec_for_session,
    validate_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_validator import validate_spec
from intric.flows.ai_builder.ai_builder_models import TargetKind
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.flow import Flow
    from intric.users.user import UserInDB

logger = get_logger(__name__)
MAX_SELF_CORRECTION_RETRIES = 1


@dataclass(frozen=True)
class ProposalDraftProcessingResult:
    plan_event: dict[str, str] | None = None
    feedback: str | None = None
    failure_kind: str | None = None


class AIBuilderProposalProcessor:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        litellm_client: Any,
        self_correction_temperature: float,
        forced_proposal_temperature: float,
        quality_retry_warning_codes: set[str],
    ) -> None:
        self.user = user
        self.repo = repo
        self.litellm_client = litellm_client
        self.self_correction_temperature = self_correction_temperature
        self.forced_proposal_temperature = forced_proposal_temperature
        self.quality_retry_warning_codes = quality_retry_warning_codes

    def _format_quality_feedback(self, validation) -> str | None:
        quality_warnings = warnings_for_quality_retry(
            validation,
            retry_warning_codes=self.quality_retry_warning_codes,
        )
        if not quality_warnings:
            return None
        return format_revision_feedback(
            "Quality issues",
            [warning.message for warning in quality_warnings],
        )

    def _format_contextual_quality_feedback(
        self,
        *,
        conversation: list[ConversationMessage],
        spec,
        flow=None,
    ) -> str | None:
        return build_conversation_aware_quality_feedback(
            conversation,
            spec,
            flow=flow,
        )

    async def _process_proposal_arguments(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        arguments: dict[str, Any],
        assistant_content: str,
        tool_call_id: str,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        flow=None,
    ) -> ProposalDraftProcessingResult:
        try:
            spec = parse_propose_flow_arguments(arguments)
            assumptions = extract_assumptions(arguments)
            reasoning = extract_reasoning(arguments)
            plan_rationale = extract_plan_rationale(arguments)
        except Exception as error:
            return ProposalDraftProcessingResult(
                feedback=f"Invalid flow specification: {error}",
                failure_kind="parse",
            )

        target_kind = TargetKind.EDIT if flow is not None else TargetKind.CREATE
        spec = normalize_compiled_spec_for_session(
            spec,
            target_kind=target_kind,
        )
        validation = validate_spec(
            spec,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
        )
        session_validation = validate_compiled_spec_for_session(
            spec,
            target_kind=target_kind,
            valid_existing_step_refs=(
                [f"existing_step_{step.step_order}" for step in flow.steps]
                if flow is not None
                else None
            ),
        )
        for error in session_validation.errors:
            validation.add_error(
                step_ref=error.step_ref,
                code=error.code,
                message=error.message,
            )
        if not validation.valid:
            quality_hint = self._format_quality_feedback(validation)
            contextual_hint = self._format_contextual_quality_feedback(
                conversation=conversation,
                spec=spec,
                flow=flow,
            )
            hard_feedback = format_validation_feedback(
                spec=spec,
                errors=validation.errors,
            )
            combined_feedback = "\n\n".join(
                feedback
                for feedback in (hard_feedback, quality_hint, contextual_hint)
                if feedback
            )
            return ProposalDraftProcessingResult(
                feedback=combined_feedback,
                failure_kind="validation",
            )

        quality_feedback = self._format_quality_feedback(validation)
        contextual_quality_feedback = self._format_contextual_quality_feedback(
            conversation=conversation,
            spec=spec,
            flow=flow,
        )
        combined_quality_feedback = "\n\n".join(
            feedback
            for feedback in (quality_feedback, contextual_quality_feedback)
            if feedback is not None
        ) or None
        if combined_quality_feedback is not None:
            return ProposalDraftProcessingResult(
                feedback=combined_quality_feedback,
                failure_kind="quality",
            )

        plan, envelope = await store_plan_and_update_conversation(
            repo=self.repo,
            tenant_id=self.user.tenant_id,
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            assistant_content=assistant_content,
            tool_call_id=tool_call_id,
            arguments=arguments,
            spec=spec,
            assumptions=assumptions,
            plan_rationale=plan_rationale,
            reasoning=reasoning,
            validation=validation,
        )
        return ProposalDraftProcessingResult(
            plan_event=build_plan_event(plan_id=plan.id, envelope=envelope)
        )

    @staticmethod
    def _build_self_correction_error_event(
        *,
        feedback: str | None,
        failure_kind: str | None,
    ) -> dict[str, str]:
        if failure_kind == "parse":
            return build_error_event(
                message=f"Self-correction failed: {feedback or 'Invalid flow specification.'}",
                code="self_correction_invalid_payload",
                phase="self_correction",
            )

        message = "Plan still invalid after correction."
        if feedback:
            message = f"{message}\n{feedback}"
        return build_error_event(
            message=message,
            code=(
                "self_correction_quality_failure"
                if failure_kind == "quality"
                else "self_correction_invalid_plan"
            ),
            phase="self_correction",
        )

    async def handle_tool_call(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        tool_calls: list[Any],
        text_content: str | None,
        llm_messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        request_id: str,
        flow=None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        if text_content:
            yield build_text_event(text_content)

        for tool_call in tool_calls:
            dispatched = self._dispatch_known_tool_call(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                tool_call=tool_call,
                text_content=text_content,
                llm_messages=llm_messages,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                max_output_tokens=max_output_tokens,
                request_id=request_id,
                flow=flow,
                assistant_snapshots=assistant_snapshots,
            )
            if dispatched is not None:
                async for event in dispatched:
                    yield event
                continue

            if tool_call.function.name != PROPOSE_FLOW_TOOL_NAME:
                continue

            async for event in self._handle_propose_flow_tool_call(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                tool_call=tool_call,
                text_content=text_content,
                llm_messages=llm_messages,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                max_output_tokens=max_output_tokens,
                request_id=request_id,
                flow=flow,
            ):
                yield event

    def _dispatch_known_tool_call(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        tool_call: Any,
        text_content: str | None,
        llm_messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        request_id: str,
        flow=None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, str], None] | None:
        tool_name = tool_call.function.name
        if tool_name == ASK_STRUCTURED_QUESTION_TOOL_NAME:
            return self._handle_structured_question(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                tool_call=tool_call,
                llm_messages=llm_messages,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                max_output_tokens=max_output_tokens,
                flow=flow,
                assistant_snapshots=assistant_snapshots,
            )
        if tool_name == CONFIRM_REQUIREMENTS_TOOL_NAME:
            return self._handle_confirm_requirements(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                tool_call=tool_call,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                flow=flow,
            )
        if tool_name == EDIT_FLOW_TOOL_NAME:
            return self._handle_edit_flow(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                tool_call=tool_call,
                text_content=text_content,
                llm_messages=llm_messages,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                max_output_tokens=max_output_tokens,
                request_id=request_id,
                flow=flow,
                assistant_snapshots=assistant_snapshots,
            )
        return None

    async def _handle_propose_flow_tool_call(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        tool_call: Any,
        text_content: str | None,
        llm_messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        request_id: str,
        flow=None,
    ) -> AsyncGenerator[dict[str, str], None]:
        requirements_state = resolve_requirements_state(conversation)
        if not requirements_state.confirmed:
            for event in await self.emit_discovery_followup_if_needed(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                flow=flow,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
            ):
                yield event
            if not analyze_discovery_ready(conversation, flow=flow):
                return
            yield build_error_event(
                message="Requirements must be confirmed before proposing a flow.",
                code="requirements_not_confirmed",
                phase="requirements",
                request_id=request_id,
            )
            return

        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            yield build_error_event(
                message="Invalid tool call arguments.",
                code="invalid_tool_call_arguments",
                phase="tool_call",
                request_id=request_id,
            )
            return

        proposal_result = await self._process_proposal_arguments(
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            arguments=arguments,
            assistant_content=text_content or "Här är mitt förslag:",
            tool_call_id=tool_call.id,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            flow=flow,
        )
        if proposal_result.plan_event is None:
            async for event in self.request_self_correction(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                error_message=proposal_result.feedback or "Invalid flow specification.",
                llm_messages=llm_messages,
                tool_call=tool_call,
                tool_schemas=tool_schemas,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                available_model_refs=available_model_refs,
                available_kb_refs=available_kb_refs,
                max_output_tokens=max_output_tokens,
                flow=flow,
            ):
                yield event
            return

        yield proposal_result.plan_event

    @staticmethod
    def _build_tool_retry_messages(
        *,
        llm_messages: list[dict[str, Any]],
        tool_call: Any,
        tool_feedback: str,
        assistant_content: str | None = None,
    ) -> list[dict[str, Any]]:
        return build_proposal_tool_retry_messages(
            llm_messages=llm_messages,
            tool_call=tool_call,
            tool_feedback=tool_feedback,
            assistant_content=assistant_content,
        )

    @staticmethod
    def _append_retry_feedback_turn(
        *,
        llm_messages: list[dict[str, Any]],
        tool_call: Any,
        assistant_content: str | None,
        tool_feedback: str,
    ) -> list[dict[str, Any]]:
        return build_append_retry_feedback_turn(
            llm_messages=llm_messages,
            tool_call=tool_call,
            assistant_content=assistant_content,
            tool_feedback=tool_feedback,
        )

    async def _call_repair_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        temperature: float,
        tool_choice: dict[str, Any] | None = None,
    ) -> Any:
        return await self.litellm_client.acompletion(
            model=litellm_model,
            messages=messages,
            tools=tool_schemas,
            tool_choice=tool_choice,
            stream=False,
            drop_params=True,
            max_tokens=max_output_tokens,
            temperature=temperature,
            **litellm_kwargs,
        )

    async def _persist_tool_turn(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        tool_call: Any,
        arguments: dict[str, Any],
        tool_content: str,
        metadata: dict[str, Any] | None = None,
        assistant_content: str | None = None,
    ) -> None:
        conversation.append(
            ConversationMessage(
                role="assistant",
                content=assistant_content,
                tool_calls=[{
                    "id": tool_call.id,
                    "name": tool_call.function.name,
                    "arguments": arguments,
                }],
            )
        )
        conversation.append(
            ConversationMessage(
                role="tool",
                content=tool_content,
                tool_call_id=tool_call.id,
                metadata=metadata,
            )
        )
        await append_session_messages(
            repo=self.repo,
            tenant_id=self.user.tenant_id,
            session_id=session_id,
            conversation=conversation,
            start_index=new_messages_start,
        )

    async def request_self_correction(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        error_message: str,
        llm_messages: list[dict[str, Any]],
        tool_call: Any,
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        flow=None,
    ) -> AsyncGenerator[dict[str, str], None]:
        async for event in run_request_self_correction(
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            error_message=error_message,
            llm_messages=llm_messages,
            tool_call=tool_call,
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            max_output_tokens=max_output_tokens,
            self_correction_temperature=self.self_correction_temperature,
            max_self_correction_retries=MAX_SELF_CORRECTION_RETRIES,
            call_repair_completion=self._call_repair_completion,
            process_proposal_arguments=self._process_proposal_arguments,
            build_self_correction_error_event=self._build_self_correction_error_event,
            retry_forced_proposal_after_text=self.retry_forced_proposal_after_text,
            flow=flow,
        ):
            yield event

    async def retry_forced_proposal_after_text(
        self,
        *,
        correction_messages: list[dict[str, Any]],
        assistant_text: str,
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        flow=None,
    ) -> dict[str, str] | None:
        return await run_retry_forced_proposal_after_text(
            correction_messages=correction_messages,
            assistant_text=assistant_text,
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            max_output_tokens=max_output_tokens,
            forced_proposal_temperature=self.forced_proposal_temperature,
            call_repair_completion=self._call_repair_completion,
            process_proposal_arguments=self._process_proposal_arguments,
            flow=flow,
        )

    async def request_non_question_continuation(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        llm_messages: list[dict[str, Any]],
        tool_call: Any,
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        flow=None,
        original_question_id: str | None = None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        filtered_tool_schemas = [
            schema
            for schema in tool_schemas
            if schema.get("function", {}).get("name") != ASK_STRUCTURED_QUESTION_TOOL_NAME
        ]
        discovery_ready = analyze_discovery_ready(conversation, flow=flow)
        if not filtered_tool_schemas:
            followup_events = await self.emit_discovery_followup_if_needed(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                flow=flow,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
            )
            if followup_events:
                for event in followup_events:
                    yield event
                return

            if discovery_ready:
                filtered_tool_schemas = build_discovery_complete_tool_schemas()
            if not filtered_tool_schemas:
                yield build_error_event(
                    message=(
                        "The AI planner lost track of the next clarification step. "
                        "Please try again."
                    ),
                    code="question_recovery_unavailable",
                    phase="question_recovery",
                )
                return

        yield build_status_event("repairing")
        forced_tool_choice = (
            {"type": "function", "function": {"name": CONFIRM_REQUIREMENTS_TOOL_NAME}}
            if discovery_ready
            else None
        )
        correction_messages = self._build_tool_retry_messages(
            llm_messages=llm_messages,
            tool_call=tool_call,
            tool_feedback=(
                "Structured discovery questions are backend-owned. "
                f"Do not call {ASK_STRUCTURED_QUESTION_TOOL_NAME} again"
                + (
                    f" for question_id '{original_question_id}'."
                    if original_question_id
                    else "."
                )
                + " Continue without inventing a new user-facing question. "
                "If enough information exists, call confirm_requirements. "
                "If requirements are already confirmed, call propose_flow. "
                "Otherwise ask for clarification in concise free text only."
            ),
        )

        retries_remaining = 1
        active_messages = correction_messages
        while True:
            try:
                response = await self._call_repair_completion(
                    messages=active_messages,
                    tool_schemas=filtered_tool_schemas,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    max_output_tokens=max_output_tokens,
                    temperature=self.self_correction_temperature,
                    tool_choice=forced_tool_choice,
                )
            except Exception as error:
                logger.error(
                    "Unexpected structured-question continuation retry failed",
                    exc_info=error,
                )
                yield build_error_event(
                    message="The AI planner failed. Please try again.",
                    code="planner_upstream_error",
                    phase="question_recovery",
                )
                return

            message = response.choices[0].message
            tool_calls = message.tool_calls if hasattr(message, "tool_calls") else None
            if tool_calls:
                repeated_question_call = next(
                    (
                        tc
                        for tc in tool_calls
                        if tc.function.name == ASK_STRUCTURED_QUESTION_TOOL_NAME
                    ),
                    None,
                )
                if repeated_question_call is not None:
                    if retries_remaining <= 0:
                        yield build_error_event(
                            message="The AI planner kept proposing unsupported discovery questions.",
                            code="question_recovery_exhausted",
                            phase="question_recovery",
                        )
                        return
                    retries_remaining -= 1
                    active_messages = self._append_retry_feedback_turn(
                        llm_messages=active_messages,
                        tool_call=repeated_question_call,
                        assistant_content=message.content,
                        tool_feedback=(
                            "Structured discovery questions remain backend-owned. "
                            "Do not call ask_structured_question. "
                            "Continue with confirm_requirements, propose_flow, or concise free text only."
                        ),
                    )
                    continue

                async for event in self.handle_tool_call(
                    session_id=session_id,
                    conversation=conversation,
                    new_messages_start=new_messages_start,
                    tool_calls=tool_calls,
                    text_content=message.content,
                    llm_messages=active_messages,
                    tool_schemas=filtered_tool_schemas,
                    litellm_model=litellm_model,
                    litellm_kwargs=litellm_kwargs,
                    available_model_refs=available_model_refs,
                    available_kb_refs=available_kb_refs,
                    max_output_tokens=max_output_tokens,
                    request_id="question-recovery",
                    flow=flow,
                    assistant_snapshots=assistant_snapshots,
                ):
                    yield event
                return

            if message.content:
                yield build_text_event(message.content)
            return

    async def _handle_structured_question(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        tool_call: Any,
        llm_messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        flow=None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        followup_events = await self.emit_discovery_followup_if_needed(
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            flow=flow,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
        )
        if followup_events:
            for event in followup_events:
                yield event
            return

        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            yield build_error_event(
                message=f"Invalid question: {error}",
                code="invalid_question_payload",
                phase="question",
            )
            return

        try:
            question_data = parse_structured_question(arguments)
        except ValueError:
            fallback_text = build_question_fallback_text(arguments)
            if not fallback_text:
                yield {
                    "event": SSE_EVENT_ERROR,
                    "data": error_payload(
                        message="Invalid question: could not build fallback prompt",
                        code="invalid_question_payload",
                        phase="question",
                    ),
                }
                return

            await self._persist_tool_turn(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                tool_call=tool_call,
                arguments=arguments,
                tool_content=(
                    "Structured question payload was invalid; rendered fallback text question."
                ),
            )
            yield build_text_event(fallback_text)
            return

        question_data = normalize_structured_question_payload(question_data)
        question_id = question_data["question_id"]
        registry_followup = (
            build_registry_question_followup(
                question_id,
                conversation,
                flow=flow,
            )
            if is_supported_structured_question_id(question_id)
            else None
        )
        if registry_followup is not None:
            backend_question_data, assistant_text = registry_followup
            for event in await persist_backend_question(
                repo=self.repo,
                tenant_id=self.user.tenant_id,
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                question_data=backend_question_data,
                assistant_text=assistant_text,
                tool_content=(
                    "Backend-owned discovery question presented to user after model signal."
                ),
            ):
                yield event
            return

        async for event in self.request_non_question_continuation(
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            llm_messages=llm_messages,
            tool_call=tool_call,
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            max_output_tokens=max_output_tokens,
            flow=flow,
            original_question_id=question_id,
            assistant_snapshots=assistant_snapshots,
        ):
            yield event

    async def _handle_confirm_requirements(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        tool_call: Any,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        flow=None,
    ) -> AsyncGenerator[dict[str, str], None]:
        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            yield build_error_event(
                message=f"Invalid requirements summary: {error}",
                code="invalid_requirements_payload",
                phase="requirements",
            )
            return

        try:
            requirements_data = parse_confirm_requirements(arguments)
        except ValueError as error:
            yield build_error_event(
                message=f"Invalid requirements summary: {error}",
                code="invalid_requirements_payload",
                phase="requirements",
            )
            return

        discovery_block_message, discovery_analysis = await build_discovery_block_message_runtime(
            conversation,
            flow=flow,
            litellm_client=self.litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
        )
        if discovery_block_message is not None:
            for event in await self.emit_discovery_followup_if_needed(
                session_id=session_id,
                conversation=conversation,
                new_messages_start=new_messages_start,
                flow=flow,
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
            ):
                yield event
            return

        merged_assumptions = list(dict.fromkeys([
            *discovery_analysis.assumptions,
            *requirements_data.get("assumptions", []),
        ]))
        requirements_data["assumptions"] = merged_assumptions

        requirements_payload_model = RequirementsSummaryPayload.model_validate(
            requirements_data
        )
        requirements_version = build_requirements_version(requirements_payload_model)
        requirements_payload = {
            **requirements_data,
            "requirements_version": requirements_version,
        }

        await self._persist_tool_turn(
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            tool_call=tool_call,
            arguments=arguments,
            tool_content="Requirements presented to user. Awaiting confirmation.",
            metadata={
                "requirements_summary": requirements_payload,
                "requirements_version": requirements_version,
            },
        )
        yield build_requirements_summary_event(requirements_payload)

    async def _handle_edit_flow(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        tool_call: Any,
        text_content: str | None,
        llm_messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        max_output_tokens: int,
        request_id: str,
        flow: "Flow | None" = None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        """Handle the edit_flow tool call — validate, compile, store, and emit plan."""
        if flow is None:
            yield build_error_event(
                message="edit_flow requires an existing flow context.",
                code="edit_no_flow",
                phase="proposal",
                request_id=request_id,
            )
            return

        # Parse arguments
        try:
            raw_args = json.loads(tool_call.function.arguments)
            draft = FlowEditDraft.model_validate(raw_args)
        except Exception as exc:
            logger.warning("Failed to parse edit_flow arguments: %s", exc)
            yield build_error_event(
                message=f"Invalid edit_flow arguments: {exc}",
                code="edit_parse_error",
                phase="proposal",
                request_id=request_id,
            )
            return

        # Validate draft structure
        valid_step_refs = [
            f"existing_step_{step.step_order}" for step in flow.steps
        ]
        edit_validation = validate_edit_draft(draft, valid_step_refs)
        if edit_validation.errors:
            error_messages = [err.message for err in edit_validation.errors]
            logger.info("Edit draft validation failed: %s", error_messages)
            # Attempt self-correction by feeding errors back
            yield build_error_event(
                message=f"Edit validation failed: {'; '.join(error_messages)}",
                code="edit_validation_error",
                phase="proposal",
                request_id=request_id,
            )
            return

        # Compile draft into concrete spec
        yield build_status_event("finalizing_plan")
        try:
            edit_result = compile_edit_draft(
                draft,
                current_steps=list(flow.steps),
                base_flow_revision=flow.draft_revision,
                flow_name=flow.name,
                flow_description=flow.description,
                current_metadata_json=flow.metadata_json,
                assistant_snapshots=assistant_snapshots,
            )
        except Exception as exc:
            logger.error("Edit compilation failed: %s", exc, exc_info=True)
            yield build_error_event(
                message=f"Failed to compile edit: {exc}",
                code="edit_compile_error",
                phase="proposal",
                request_id=request_id,
            )
            return

        # Validate the compiled spec
        compiled_spec = edit_result.compiled_spec
        validation = validate_spec(compiled_spec)
        session_validation = validate_compiled_spec_for_session(
            compiled_spec,
            target_kind=TargetKind.EDIT,
            valid_existing_step_refs=valid_step_refs,
        )
        for error in session_validation.errors:
            validation.add_error(
                step_ref=error.step_ref,
                code=error.code,
                message=error.message,
            )
        if validation.errors:
            error_messages = [err.message for err in validation.errors]
            yield build_error_event(
                message=f"Compiled edit spec validation failed: {'; '.join(error_messages)}",
                code="edit_spec_validation_error",
                phase="proposal",
                request_id=request_id,
            )
            return

        # Store plan with the compiled spec (not the raw draft)
        assumptions = list(draft.assumptions) if draft.assumptions else []
        plan, envelope = await store_plan_and_update_conversation(
            repo=self.repo,
            tenant_id=self.user.tenant_id,
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            assistant_content=text_content or "",
            tool_call_id=tool_call.id,
            arguments=raw_args,
            spec=compiled_spec,
            assumptions=assumptions,
            plan_rationale=draft.plan_rationale,
            reasoning=None,
            validation=validation,
        )

        yield build_plan_event(
            plan_id=plan.id,
            envelope=envelope,
            edit_result=edit_result,
        )

    async def emit_discovery_followup_if_needed(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        litellm_model: str | None = None,
        litellm_kwargs: dict[str, Any] | None = None,
        ui_language: str | None = None,
        flow=None,
    ) -> list[dict[str, str]]:
        return await emit_discovery_followup_if_needed(
            repo=self.repo,
            tenant_id=self.user.tenant_id,
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            flow=flow,
            litellm_client=self.litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            ui_language=ui_language,
        )

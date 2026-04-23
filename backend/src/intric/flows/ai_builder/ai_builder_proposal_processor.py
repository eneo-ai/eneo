from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator, Awaitable, Callable, cast
from uuid import UUID

from intric.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from intric.flows.ai_builder.ai_builder_create_compiler import compile_create_draft
from intric.flows.ai_builder.ai_builder_create_feedback import (
    format_create_argument_error,
    format_create_quality_feedback,
    format_create_validation_feedback,
)
from intric.flows.ai_builder.ai_builder_create_validator import validate_create_draft
from intric.flows.ai_builder.ai_builder_description_semantics import (
    DescriptionProvenance,
)
from intric.flows.ai_builder.ai_builder_discovery import (
    build_registry_question_followup,
)
from intric.flows.ai_builder.ai_builder_discovery_followup import (
    emit_discovery_followup_if_needed,
    persist_backend_question,
)
from intric.flows.ai_builder.ai_builder_discovery_runtime import (
    build_discovery_block_message_runtime,
)
from intric.flows.ai_builder.ai_builder_edit_compiler import compile_edit_draft
from intric.flows.ai_builder.ai_builder_edit_models import FlowEditDraft
from intric.flows.ai_builder.ai_builder_edit_repair import (
    should_attempt_description_repair,
    validate_repair_invariance,
)
from intric.flows.ai_builder.ai_builder_edit_tool_schema import EDIT_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_edit_validator import validate_edit_draft
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_ERROR,
    build_error_event,
    build_plan_event,
    build_requirements_summary_event,
    build_status_event,
    build_text_event,
    error_payload,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    is_supported_structured_question_id,
    normalize_structured_question_payload,
)
from intric.flows.ai_builder.ai_builder_interaction_utils import (
    analyze_discovery_ready,
    build_question_fallback_text,
)
from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    FlowDraftSpecCore,
    RequirementsSummaryPayload,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_aware_quality_feedback,
)
from intric.flows.ai_builder.ai_builder_plan_store import (
    format_revision_feedback,
    format_validation_feedback,
    store_plan_and_update_conversation,
    warnings_for_quality_retry,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    request_self_correction as run_request_self_correction,
)
from intric.flows.ai_builder.ai_builder_proposal_repair import (
    retry_forced_tool_after_text as run_retry_forced_tool_after_text,
)
from intric.flows.ai_builder.ai_builder_repair_transport import (
    append_tool_retry_feedback_turn,
    build_persisted_tool_call_stub,
    build_tool_retry_messages,
    persist_tool_turn,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_requirements_state import (
    build_requirements_version,
    resolve_requirements_state,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    canonicalize_create_draft_resources,
    canonicalize_edit_draft_resources,
    format_resource_resolution_feedback,
)
from intric.flows.ai_builder.ai_builder_telemetry import (
    build_assistant_message_metadata,
)
from intric.flows.ai_builder.ai_builder_tools import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
    CREATE_FLOW_TOOL_NAME,
    RecoverableToolPayloadError,
    build_discovery_complete_tool_schemas,
    parse_confirm_requirements,
    parse_create_flow_arguments,
    parse_structured_question,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow
    from intric.users.user import UserInDB

logger = get_logger(__name__)
MAX_SELF_CORRECTION_RETRIES = 3
SUBMISSION_TOOL_NAMES = frozenset({CREATE_FLOW_TOOL_NAME, EDIT_FLOW_TOOL_NAME})


def _tool_calls_contain_submission(tool_calls: list[Any]) -> bool:
    return any(
        getattr(getattr(call, "function", None), "name", None) in SUBMISSION_TOOL_NAMES
        for call in tool_calls
    )


@dataclass(frozen=True)
class ToolProcessingResult:
    event: dict[str, str] | None = None
    feedback: str | None = None
    failure_kind: str | None = None


@dataclass(frozen=True)
class ProposalContext:
    session_id: UUID
    conversation: list[ConversationMessage]
    new_messages_start: int
    llm_messages: list[dict[str, Any]]
    tool_schemas: list[dict[str, Any]]
    litellm_model: str
    litellm_kwargs: dict[str, Any]
    available_model_refs: set[str] | None
    available_kb_refs: set[str] | None
    resource_catalog: AIBuilderResourceCatalog | None
    max_output_tokens: int
    request_id: str
    lease_request_id: UUID | None = None
    lease_lock_token: UUID | None = None
    flow: "Flow | None" = None
    assistant_snapshots: dict[UUID, dict[str, Any]] | None = None
    text_content: str | None = None
    assistant_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SubmissionToolHandlerConfig:
    target_tool_name: str
    requirements_not_confirmed_message: str
    parse_error_prefix: str
    invalid_result_message: str
    forced_tool_prompt: str
    process_tool_arguments: Callable[..., Awaitable[ToolProcessingResult]]
    include_flow_context: bool = False


@dataclass(frozen=True)
class ToolRetryConfig:
    target_tool_name: str
    forced_tool_prompt: str
    process_tool_arguments: Callable[..., Awaitable[ToolProcessingResult]]
    process_tool_kwargs: dict[str, Any]


class AIBuilderProposalProcessor:
    def __init__(
        self,
        *,
        user: "UserInDB",
        repo: AIBuilderRepository,
        litellm_client: Any,
        self_correction_temperature: float,
        self_correction_bumped_temperature: float,
        forced_proposal_temperature: float,
        quality_retry_warning_codes: set[str],
    ) -> None:
        self.user = user
        self.repo = repo
        self.litellm_client = litellm_client
        self.self_correction_temperature = self_correction_temperature
        self.self_correction_bumped_temperature = self_correction_bumped_temperature
        self.forced_proposal_temperature = forced_proposal_temperature
        self.quality_retry_warning_codes = quality_retry_warning_codes

    def _format_quality_feedback(self, validation: SpecValidationResult) -> str | None:
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
        spec: FlowDraftSpecCore,
        flow: "Flow | None" = None,
    ) -> str | None:
        return build_conversation_aware_quality_feedback(
            conversation,
            spec,
            flow=flow,
        )

    async def _process_create_arguments(
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
        assistant_metadata: dict[str, Any] | None = None,
        resource_catalog: AIBuilderResourceCatalog | None = None,
        flow: "Flow | None" = None,
        lease_request_id: UUID | None = None,
        lease_lock_token: UUID | None = None,
    ) -> ToolProcessingResult:
        try:
            draft = parse_create_flow_arguments(arguments)
        except RecoverableToolPayloadError as error:
            return ToolProcessingResult(
                feedback=format_create_argument_error(error),
                failure_kind="recoverable_parse",
            )
        except Exception as error:
            return ToolProcessingResult(
                feedback=format_create_argument_error(error),
                failure_kind="parse",
            )

        if resource_catalog is not None:
            draft, resolution_issues = canonicalize_create_draft_resources(
                draft,
                catalog=resource_catalog,
            )
            if resolution_issues:
                return ToolProcessingResult(
                    feedback=format_resource_resolution_feedback(resolution_issues),
                    failure_kind="validation",
                )

        create_validation = validate_create_draft(draft)
        if create_validation.errors:
            return ToolProcessingResult(
                feedback=format_create_validation_feedback(create_validation),
                failure_kind="validation",
            )

        try:
            spec = compile_create_draft(draft)
        except Exception as error:
            logger.error("Create draft compilation failed: %s", error, exc_info=error)
            return ToolProcessingResult(
                feedback=f"Failed to compile create_flow draft: {error}",
                failure_kind="validation",
            )

        prepared = prepare_compiled_spec_for_session(
            spec=spec,
            target_kind=TargetKind.CREATE,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            valid_existing_step_refs=None,
        )
        if prepared.failure_feedback is not None:
            return ToolProcessingResult(
                feedback=prepared.failure_feedback,
                failure_kind="validation",
            )
        assert prepared.spec is not None
        assert prepared.validation is not None
        spec = prepared.spec
        validation = prepared.validation
        if not validation.valid:
            quality_hint = self._format_quality_feedback(validation)
            contextual_hint = self._format_contextual_quality_feedback(
                conversation=conversation,
                spec=spec,
                flow=None,
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
            combined_feedback = format_create_quality_feedback(combined_feedback)
            return ToolProcessingResult(
                feedback=combined_feedback,
                failure_kind="validation",
            )

        quality_feedback = self._format_quality_feedback(validation)
        contextual_quality_feedback = self._format_contextual_quality_feedback(
            conversation=conversation,
            spec=spec,
            flow=None,
        )
        combined_quality_feedback = (
            "\n\n".join(
                feedback
                for feedback in (quality_feedback, contextual_quality_feedback)
                if feedback is not None
            )
            or None
        )
        combined_quality_feedback = format_create_quality_feedback(
            combined_quality_feedback
        )
        if combined_quality_feedback is not None:
            return ToolProcessingResult(
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
            assistant_metadata=assistant_metadata,
            tool_call_id=tool_call_id,
            tool_name=CREATE_FLOW_TOOL_NAME,
            arguments=arguments,
            spec=spec,
            assumptions=list(draft.assumptions),
            plan_rationale=draft.plan_rationale,
            reasoning=None,
            validation=validation,
            lease_request_id=lease_request_id,
            lease_lock_token=lease_lock_token,
            flow=flow,
        )
        return ToolProcessingResult(
            event=build_plan_event(plan_id=plan.id, envelope=envelope)
        )

    @staticmethod
    def _build_self_correction_error_event(
        *,
        feedback: str | None,
        failure_kind: str | None,
    ) -> dict[str, str]:
        if failure_kind in {"parse", "recoverable_parse"}:
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
        assistant_metadata: dict[str, Any] | None = None,
        lease_request_id: UUID | None = None,
        lease_lock_token: UUID | None = None,
        resource_catalog: AIBuilderResourceCatalog | None = None,
        flow: "Flow | None" = None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        ctx = ProposalContext(
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            llm_messages=llm_messages,
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            max_output_tokens=max_output_tokens,
            request_id=request_id,
            lease_request_id=lease_request_id,
            lease_lock_token=lease_lock_token,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            text_content=text_content,
            assistant_metadata=assistant_metadata,
        )
        if ctx.text_content and not _tool_calls_contain_submission(tool_calls):
            yield build_text_event(ctx.text_content)

        for tool_call in tool_calls:
            dispatched = self._dispatch_known_tool_call(ctx=ctx, tool_call=tool_call)
            if dispatched is None:
                continue
            async for event in dispatched:
                yield event

    def _dispatch_known_tool_call(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None] | None:
        tool_name = tool_call.function.name
        if tool_name == ASK_STRUCTURED_QUESTION_TOOL_NAME:
            return self._handle_structured_question(
                ctx=ctx,
                tool_call=tool_call,
            )
        if tool_name == CREATE_FLOW_TOOL_NAME:
            return self._handle_create_flow_tool_call(
                ctx=ctx,
                tool_call=tool_call,
            )
        if tool_name == CONFIRM_REQUIREMENTS_TOOL_NAME:
            return self._handle_confirm_requirements(
                ctx=ctx,
                tool_call=tool_call,
            )
        if tool_name == EDIT_FLOW_TOOL_NAME:
            return self._handle_edit_flow(
                ctx=ctx,
                tool_call=tool_call,
            )
        return None

    async def _resolve_submission_prerequisite_events(
        self,
        *,
        ctx: ProposalContext,
        requirements_not_confirmed_message: str,
    ) -> tuple[bool, list[dict[str, str]]]:
        requirements_state = resolve_requirements_state(ctx.conversation)
        if requirements_state.confirmed:
            return False, []

        followup_events = await self.emit_discovery_followup_if_needed(
            session_id=ctx.session_id,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            flow=ctx.flow,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            assistant_metadata=build_assistant_message_metadata(
                ctx.conversation,
                base_metadata=ctx.assistant_metadata,
                tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
            ),
            lease_request_id=ctx.lease_request_id,
            lease_lock_token=ctx.lease_lock_token,
        )
        if followup_events:
            return True, followup_events
        if not analyze_discovery_ready(ctx.conversation, flow=ctx.flow):
            return True, []
        return True, [
            build_error_event(
                message=requirements_not_confirmed_message,
                code="requirements_not_confirmed",
                phase="requirements",
                request_id=ctx.request_id,
            )
        ]

    async def _handle_submission_tool_call(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
        config: SubmissionToolHandlerConfig,
    ) -> AsyncGenerator[dict[str, str], None]:
        (
            blocked,
            prerequisite_events,
        ) = await self._resolve_submission_prerequisite_events(
            ctx=ctx,
            requirements_not_confirmed_message=config.requirements_not_confirmed_message,
        )
        for event in prerequisite_events:
            yield event
        if blocked:
            return

        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            logger.info(
                "ai_builder_submission_first_attempt tool=%s request_id=%s success=false failure_kind=parse",
                config.target_tool_name,
                ctx.request_id,
            )
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=f"{config.parse_error_prefix}: {error}",
                tool_call=tool_call,
                retry_config=ToolRetryConfig(
                    target_tool_name=config.target_tool_name,
                    forced_tool_prompt=config.forced_tool_prompt,
                    process_tool_arguments=config.process_tool_arguments,
                    process_tool_kwargs={},
                ),
            ):
                yield event
            return

        submission_kwargs = self._build_submission_processing_kwargs(
            session_id=ctx.session_id,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            arguments=arguments,
            assistant_content="Här är mitt förslag:",
            assistant_metadata=ctx.assistant_metadata,
            tool_call_id=tool_call.id,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            resource_catalog=ctx.resource_catalog,
            flow=ctx.flow,
            include_flow_context=config.include_flow_context,
            lease_request_id=ctx.lease_request_id,
            lease_lock_token=ctx.lease_lock_token,
        )
        submission_result = await config.process_tool_arguments(**submission_kwargs)
        logger.info(
            "ai_builder_submission_first_attempt tool=%s request_id=%s success=%s failure_kind=%s",
            config.target_tool_name,
            ctx.request_id,
            str(submission_result.event is not None).lower(),
            submission_result.failure_kind or "none",
        )
        if submission_result.event is None:
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=submission_result.feedback
                or config.invalid_result_message,
                tool_call=tool_call,
                retry_config=ToolRetryConfig(
                    target_tool_name=config.target_tool_name,
                    forced_tool_prompt=config.forced_tool_prompt,
                    process_tool_arguments=config.process_tool_arguments,
                    process_tool_kwargs={},
                ),
            ):
                yield event
            return

        yield submission_result.event

    @staticmethod
    def _build_submission_processing_kwargs(
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        arguments: dict[str, Any],
        assistant_content: str,
        assistant_metadata: dict[str, Any] | None = None,
        tool_call_id: str,
        available_model_refs: set[str] | None,
        available_kb_refs: set[str] | None,
        resource_catalog: AIBuilderResourceCatalog | None,
        flow: "Flow | None",
        include_flow_context: bool,
        lease_request_id: UUID | None,
        lease_lock_token: UUID | None,
    ) -> dict[str, Any]:
        processing_kwargs: dict[str, Any] = {
            "session_id": session_id,
            "conversation": conversation,
            "new_messages_start": new_messages_start,
            "arguments": arguments,
            "assistant_content": assistant_content,
            "assistant_metadata": assistant_metadata,
            "tool_call_id": tool_call_id,
            "available_model_refs": available_model_refs,
            "available_kb_refs": available_kb_refs,
            "resource_catalog": resource_catalog,
            "lease_request_id": lease_request_id,
            "lease_lock_token": lease_lock_token,
        }
        if include_flow_context:
            processing_kwargs["flow"] = flow
        return processing_kwargs

    async def _handle_create_flow_tool_call(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        async for event in self._handle_submission_tool_call(
            ctx=ctx,
            tool_call=tool_call,
            config=SubmissionToolHandlerConfig(
                target_tool_name=CREATE_FLOW_TOOL_NAME,
                requirements_not_confirmed_message="Requirements must be confirmed before creating a flow.",
                parse_error_prefix="Invalid create_flow arguments",
                invalid_result_message="Invalid create_flow draft.",
                forced_tool_prompt=(
                    "Your previous reply was prose only. "
                    "Now call create_flow with one complete typed draft. "
                    "Do not answer with prose."
                ),
                process_tool_arguments=self._process_create_arguments,
            ),
        ):
            yield event

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
        resource_catalog: AIBuilderResourceCatalog | None = None,
        flow: "Flow | None" = None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        ctx = ProposalContext(
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            llm_messages=llm_messages,
            tool_schemas=tool_schemas,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=resource_catalog,
            max_output_tokens=max_output_tokens,
            request_id="self-correction",
            flow=flow,
        )
        retry_config = self._submission_retry_config(
            flow=flow,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            assistant_snapshots=assistant_snapshots,
            resource_catalog=resource_catalog,
        )
        async for event in self._request_tool_self_correction(
            ctx=ctx,
            error_message=error_message,
            tool_call=tool_call,
            retry_config=retry_config,
        ):
            yield event

    async def _request_tool_self_correction(
        self,
        *,
        ctx: ProposalContext,
        error_message: str,
        tool_call: Any,
        retry_config: ToolRetryConfig,
    ) -> AsyncGenerator[dict[str, str], None]:
        merged_process_kwargs = dict(retry_config.process_tool_kwargs)
        merged_process_kwargs.setdefault("resource_catalog", ctx.resource_catalog)
        async for event in run_request_self_correction(
            session_id=ctx.session_id,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            error_message=error_message,
            llm_messages=ctx.llm_messages,
            tool_call=tool_call,
            tool_schemas=ctx.tool_schemas,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            max_output_tokens=ctx.max_output_tokens,
            self_correction_temperature=self.self_correction_temperature,
            self_correction_bumped_temperature=self.self_correction_bumped_temperature,
            max_self_correction_retries=MAX_SELF_CORRECTION_RETRIES,
            call_repair_completion=self._call_repair_completion,
            process_tool_arguments=retry_config.process_tool_arguments,
            target_tool_name=retry_config.target_tool_name,
            forced_tool_prompt=retry_config.forced_tool_prompt,
            build_self_correction_error_event=self._build_self_correction_error_event,
            retry_forced_tool_after_text=self.retry_forced_tool_after_text,
            process_tool_kwargs=merged_process_kwargs,
            flow=ctx.flow,
        ):
            yield event

    async def retry_forced_tool_after_text(
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
        target_tool_name: str,
        forced_tool_prompt: str,
        process_tool_arguments: Any,
        process_tool_kwargs: dict[str, Any] | None = None,
        flow: "Flow | None" = None,
        resource_catalog: AIBuilderResourceCatalog | None = None,
    ) -> dict[str, str] | None:
        merged_process_kwargs = dict(process_tool_kwargs or {})
        if resource_catalog is not None:
            merged_process_kwargs.setdefault("resource_catalog", resource_catalog)
        return await run_retry_forced_tool_after_text(
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
            target_tool_name=target_tool_name,
            forced_tool_prompt=forced_tool_prompt,
            forced_proposal_temperature=self.forced_proposal_temperature,
            call_repair_completion=self._call_repair_completion,
            process_tool_arguments=process_tool_arguments,
            process_tool_kwargs=merged_process_kwargs,
            flow=flow,
        )

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
        resource_catalog: AIBuilderResourceCatalog | None = None,
        max_output_tokens: int,
        flow: "Flow | None" = None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
        lease_request_id: UUID | None = None,
        lease_lock_token: UUID | None = None,
    ) -> dict[str, str] | None:
        retry_config = self._submission_retry_config(
            flow=flow,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
            max_output_tokens=max_output_tokens,
            assistant_snapshots=assistant_snapshots,
            resource_catalog=resource_catalog,
        )
        return await self.retry_forced_tool_after_text(
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
            target_tool_name=retry_config.target_tool_name,
            forced_tool_prompt=retry_config.forced_tool_prompt,
            process_tool_arguments=retry_config.process_tool_arguments,
            process_tool_kwargs=retry_config.process_tool_kwargs,
            resource_catalog=resource_catalog,
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
        resource_catalog: AIBuilderResourceCatalog | None = None,
        flow: "Flow | None" = None,
        original_question_id: str | None = None,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
    ) -> AsyncGenerator[dict[str, str], None]:
        submission_tool_name = _active_submission_tool_name(flow)
        filtered_tool_schemas = [
            schema
            for schema in tool_schemas
            if schema.get("function", {}).get("name")
            != ASK_STRUCTURED_QUESTION_TOOL_NAME
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
                assistant_metadata=build_assistant_message_metadata(
                    conversation,
                    tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
                ),
                lease_request_id=None,
                lease_lock_token=None,
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
        correction_messages = build_tool_retry_messages(
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
                f"If requirements are already confirmed, call {submission_tool_name}. "
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
                    active_messages = append_tool_retry_feedback_turn(
                        llm_messages=active_messages,
                        tool_call=repeated_question_call,
                        assistant_content=message.content,
                        tool_feedback=(
                            "Structured discovery questions remain backend-owned. "
                            "Do not call ask_structured_question. "
                            f"Continue with confirm_requirements, {submission_tool_name}, or concise free text only."
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
                    resource_catalog=resource_catalog,
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
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        followup_events = await self.emit_discovery_followup_if_needed(
            session_id=ctx.session_id,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            flow=ctx.flow,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            assistant_metadata=build_assistant_message_metadata(
                ctx.conversation,
                base_metadata=ctx.assistant_metadata,
                tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
            ),
            lease_request_id=ctx.lease_request_id,
            lease_lock_token=ctx.lease_lock_token,
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

            await persist_tool_turn(
                repo=self.repo,
                tenant_id=self.user.tenant_id,
                session_id=ctx.session_id,
                conversation=ctx.conversation,
                new_messages_start=ctx.new_messages_start,
                tool_call=tool_call,
                arguments=arguments,
                tool_content=(
                    "Structured question payload was invalid; rendered fallback text question."
                ),
                assistant_metadata=ctx.assistant_metadata,
                flow=ctx.flow,
                lease_request_id=ctx.lease_request_id,
                lease_lock_token=ctx.lease_lock_token,
            )
            yield build_text_event(fallback_text)
            return

        question_data = normalize_structured_question_payload(question_data)
        question_id = question_data["question_id"]
        registry_followup = (
            build_registry_question_followup(
                question_id,
                ctx.conversation,
                flow=ctx.flow,
            )
            if is_supported_structured_question_id(question_id)
            else None
        )
        if registry_followup is not None:
            backend_question_data, assistant_text = registry_followup
            for event in await persist_backend_question(
                repo=self.repo,
                tenant_id=self.user.tenant_id,
                session_id=ctx.session_id,
                conversation=ctx.conversation,
                new_messages_start=ctx.new_messages_start,
                question_data=backend_question_data,
                assistant_text=assistant_text,
                assistant_metadata=ctx.assistant_metadata,
                tool_content=(
                    "Backend-owned discovery question presented to user after model signal."
                ),
                flow=ctx.flow,
                lease_request_id=ctx.lease_request_id,
                lease_lock_token=ctx.lease_lock_token,
            ):
                yield event
            return

        async for event in self.request_non_question_continuation(
            session_id=ctx.session_id,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            llm_messages=ctx.llm_messages,
            tool_call=tool_call,
            tool_schemas=ctx.tool_schemas,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            resource_catalog=ctx.resource_catalog,
            max_output_tokens=ctx.max_output_tokens,
            flow=ctx.flow,
            original_question_id=question_id,
            assistant_snapshots=ctx.assistant_snapshots,
        ):
            yield event

    async def _process_confirm_requirements_arguments(
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
        flow: "Flow | None" = None,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        assistant_metadata: dict[str, Any] | None = None,
        lease_request_id: UUID | None = None,
        lease_lock_token: UUID | None = None,
    ) -> ToolProcessingResult:
        del assistant_content, available_model_refs, available_kb_refs

        try:
            requirements_data = parse_confirm_requirements(arguments)
        except ValueError as error:
            return ToolProcessingResult(
                feedback=f"Invalid requirements summary: {error}",
                failure_kind="parse",
            )

        (
            discovery_block_message,
            discovery_analysis,
        ) = await build_discovery_block_message_runtime(
            conversation,
            flow=flow,
            litellm_client=self.litellm_client,
            litellm_model=litellm_model,
            litellm_kwargs=litellm_kwargs,
        )
        if discovery_block_message is not None:
            return ToolProcessingResult(
                feedback=discovery_block_message,
                failure_kind="validation",
            )

        merged_assumptions = list(
            dict.fromkeys(
                [
                    *discovery_analysis.assumptions,
                    *requirements_data.get("assumptions", []),
                ]
            )
        )
        requirements_data["assumptions"] = merged_assumptions

        requirements_payload_model = RequirementsSummaryPayload.model_validate(
            requirements_data
        )
        requirements_version = build_requirements_version(requirements_payload_model)
        requirements_payload = {
            **requirements_data,
            "requirements_version": requirements_version,
        }

        tool_call = build_persisted_tool_call_stub(
            tool_call_id=tool_call_id,
            tool_name=CONFIRM_REQUIREMENTS_TOOL_NAME,
        )
        await persist_tool_turn(
            repo=self.repo,
            tenant_id=self.user.tenant_id,
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
            assistant_metadata=assistant_metadata,
            flow=flow,
            lease_request_id=lease_request_id,
            lease_lock_token=lease_lock_token,
        )
        return ToolProcessingResult(
            event=build_requirements_summary_event(requirements_payload)
        )

    async def _process_edit_arguments(
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
        flow: "Flow | None",
        assistant_snapshots: dict[UUID, dict[str, Any]] | None,
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        assistant_metadata: dict[str, Any] | None = None,
        resource_catalog: AIBuilderResourceCatalog | None = None,
        lease_request_id: UUID | None = None,
        lease_lock_token: UUID | None = None,
    ) -> ToolProcessingResult:
        if flow is None:
            return ToolProcessingResult(
                feedback="edit_flow requires an existing flow context.",
                failure_kind="validation",
            )

        try:
            draft = FlowEditDraft.model_validate(arguments)
        except Exception as exc:
            logger.warning("Failed to parse edit_flow arguments: %s", exc)
            return ToolProcessingResult(
                feedback=f"Invalid edit_flow arguments: {exc}",
                failure_kind="parse",
            )

        if resource_catalog is not None:
            draft, resolution_issues = canonicalize_edit_draft_resources(
                draft,
                catalog=resource_catalog,
            )
            if resolution_issues:
                return ToolProcessingResult(
                    feedback=format_resource_resolution_feedback(resolution_issues),
                    failure_kind="validation",
                )

        valid_step_refs = [f"existing_step_{step.step_order}" for step in flow.steps]
        edit_validation = validate_edit_draft(
            draft,
            valid_step_refs,
            current_steps=list(flow.steps),
            current_metadata_json=flow.metadata_json,
        )
        if edit_validation.errors:
            error_messages = [err.message for err in edit_validation.errors]
            logger.info("Edit draft validation failed: %s", error_messages)
            return ToolProcessingResult(
                feedback=f"Edit validation failed: {'; '.join(error_messages)}",
                failure_kind="validation",
            )

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
            return ToolProcessingResult(
                feedback=f"Failed to compile edit: {exc}",
                failure_kind="validation",
            )

        compiled_spec = edit_result.compiled_spec
        prepared = prepare_compiled_spec_for_session(
            spec=compiled_spec,
            target_kind=TargetKind.EDIT,
            available_model_refs=available_model_refs,
            available_kb_refs=available_kb_refs,
            resource_catalog=None,
            valid_existing_step_refs=valid_step_refs,
        )
        if prepared.failure_feedback is not None:
            return ToolProcessingResult(
                feedback=prepared.failure_feedback,
                failure_kind="validation",
            )
        assert prepared.spec is not None
        assert prepared.validation is not None
        compiled_spec = prepared.spec
        validation = prepared.validation
        if validation.errors:
            error_messages = [err.message for err in validation.errors]
            return ToolProcessingResult(
                feedback=(
                    "Compiled edit spec validation failed: " + "; ".join(error_messages)
                ),
                failure_kind="validation",
            )

        current_provenance = _extract_description_provenance(flow.metadata_json)
        if should_attempt_description_repair(
            advisories=edit_result.advisories,
            current_description=flow.description,
            current_provenance=current_provenance,
        ):
            repaired_spec = await self._attempt_description_repair(
                compiled_spec=compiled_spec,
                flow=flow,
                llm_messages=[],
                tool_schemas=[],
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                max_output_tokens=min(max_output_tokens, 256),
            )
            if repaired_spec is not None:
                compiled_spec = repaired_spec
                edit_result = edit_result.model_copy(
                    update={
                        "compiled_spec": compiled_spec,
                        "advisories": [
                            advisory
                            for advisory in edit_result.advisories
                            if advisory.code != "flow_description_update_required"
                        ],
                    }
                )

        quality_feedback = self._format_quality_feedback(validation)
        contextual_quality_feedback = self._format_contextual_quality_feedback(
            conversation=conversation,
            spec=compiled_spec,
            flow=flow,
        )
        combined_quality_feedback = "\n\n".join(
            feedback
            for feedback in (quality_feedback, contextual_quality_feedback)
            if feedback
        )
        if combined_quality_feedback:
            return ToolProcessingResult(
                feedback=combined_quality_feedback,
                failure_kind="quality",
            )

        assumptions = list(draft.assumptions) if draft.assumptions else []
        serialized_edit_result = edit_result.model_dump(mode="json")
        plan, envelope = await store_plan_and_update_conversation(
            repo=self.repo,
            tenant_id=self.user.tenant_id,
            session_id=session_id,
            conversation=conversation,
            new_messages_start=new_messages_start,
            assistant_content=assistant_content,
            assistant_metadata=assistant_metadata,
            tool_call_id=tool_call_id,
            tool_name=EDIT_FLOW_TOOL_NAME,
            arguments=arguments,
            spec=compiled_spec,
            assumptions=assumptions,
            plan_rationale=draft.plan_rationale,
            reasoning=None,
            validation=validation,
            edit_result_json=serialized_edit_result,
            lease_request_id=lease_request_id,
            lease_lock_token=lease_lock_token,
            flow=flow,
        )
        return ToolProcessingResult(
            event=build_plan_event(
                plan_id=plan.id,
                envelope=envelope,
                edit_result=edit_result,
            )
        )

    async def _handle_confirm_requirements(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=f"Invalid requirements summary: {error}",
                tool_call=tool_call,
                retry_config=self._confirm_requirements_retry_config(ctx),
            ):
                yield event
            return

        confirm_result = await self._process_confirm_requirements_arguments(
            session_id=ctx.session_id,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            arguments=arguments,
            assistant_content=ctx.text_content or "",
            assistant_metadata=ctx.assistant_metadata,
            tool_call_id=tool_call.id,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            flow=ctx.flow,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
        )
        if confirm_result.event is None:
            if confirm_result.failure_kind == "validation":
                for event in await self.emit_discovery_followup_if_needed(
                    session_id=ctx.session_id,
                    conversation=ctx.conversation,
                    new_messages_start=ctx.new_messages_start,
                    flow=ctx.flow,
                    litellm_model=ctx.litellm_model,
                    litellm_kwargs=ctx.litellm_kwargs,
                    assistant_metadata=build_assistant_message_metadata(
                        ctx.conversation,
                        base_metadata=ctx.assistant_metadata,
                        tool_calls=[{"name": ASK_STRUCTURED_QUESTION_TOOL_NAME}],
                    ),
                    lease_request_id=ctx.lease_request_id,
                    lease_lock_token=ctx.lease_lock_token,
                ):
                    yield event
                return

            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=confirm_result.feedback
                or "Invalid requirements summary.",
                tool_call=tool_call,
                retry_config=self._confirm_requirements_retry_config(ctx),
            ):
                yield event
            return

        yield confirm_result.event

    async def _handle_edit_flow(
        self,
        *,
        ctx: ProposalContext,
        tool_call: Any,
    ) -> AsyncGenerator[dict[str, str], None]:
        try:
            raw_args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=f"Invalid edit_flow arguments: {error}",
                tool_call=tool_call,
                retry_config=self._edit_flow_retry_config(ctx),
            ):
                yield event
            return

        edit_result = await self._process_edit_arguments(
            session_id=ctx.session_id,
            conversation=ctx.conversation,
            new_messages_start=ctx.new_messages_start,
            arguments=raw_args,
            assistant_content=ctx.text_content or "",
            tool_call_id=tool_call.id,
            available_model_refs=ctx.available_model_refs,
            available_kb_refs=ctx.available_kb_refs,
            flow=ctx.flow,
            assistant_snapshots=ctx.assistant_snapshots,
            litellm_model=ctx.litellm_model,
            litellm_kwargs=ctx.litellm_kwargs,
            max_output_tokens=ctx.max_output_tokens,
            resource_catalog=ctx.resource_catalog,
        )
        if edit_result.event is None:
            async for event in self._request_tool_self_correction(
                ctx=ctx,
                error_message=edit_result.feedback or "Invalid edit_flow arguments.",
                tool_call=tool_call,
                retry_config=self._edit_flow_retry_config(ctx),
            ):
                yield event
            return

        yield edit_result.event

    async def _attempt_description_repair(
        self,
        *,
        compiled_spec: "FlowDraftSpecCore",
        flow: "Flow",
        llm_messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
    ) -> "FlowDraftSpecCore | None":
        """Ask the LLM to generate ONLY a new flow description. Max 1 attempt.

        Returns the repaired spec if successful (only description changed),
        or None if the repair failed or changed non-description fields.
        """

        repair_prompt = (
            "The flow's input or output type changed but the description was not updated. "
            "Generate ONLY a new flow_description that accurately reflects the current flow. "
            f"Current flow name: {compiled_spec.flow_name}\n"
            f"Current description (stale): {compiled_spec.flow_description}\n"
            f"Steps: {', '.join(s.name for s in compiled_spec.steps)}\n"
            f"Entry input: {compiled_spec.steps[0].input_type.value if compiled_spec.steps else 'none'}\n"
            f"Terminal output: {compiled_spec.steps[-1].output_type.value if compiled_spec.steps else 'none'}\n"
            "Respond with ONLY the new description text, nothing else."
        )

        try:
            response = await self._call_repair_completion(
                messages=[{"role": "user", "content": repair_prompt}],
                tool_schemas=[],
                litellm_model=litellm_model,
                litellm_kwargs=litellm_kwargs,
                max_output_tokens=256,
                temperature=0.3,
            )
            new_description = (response.choices[0].message.content or "").strip()
            if not new_description:
                return None

            repaired = compiled_spec.model_copy(
                update={"flow_description": new_description}
            )
            if not validate_repair_invariance(compiled_spec, repaired):
                logger.warning(
                    "Description repair changed non-description fields, rejecting"
                )
                return None

            return repaired
        except Exception as exc:
            logger.warning("Description repair failed: %s", exc)
            return None

    async def emit_discovery_followup_if_needed(
        self,
        *,
        session_id: UUID,
        conversation: list[ConversationMessage],
        new_messages_start: int,
        litellm_model: str | None = None,
        litellm_kwargs: dict[str, Any] | None = None,
        ui_language: str | None = None,
        flow: "Flow | None" = None,
        assistant_metadata: dict[str, Any] | None = None,
        lease_request_id: UUID | None = None,
        lease_lock_token: UUID | None = None,
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
            assistant_metadata=assistant_metadata,
            lease_request_id=lease_request_id,
            lease_lock_token=lease_lock_token,
        )

    def _submission_retry_config(
        self,
        *,
        flow: "Flow | None",
        litellm_model: str,
        litellm_kwargs: dict[str, Any],
        max_output_tokens: int,
        assistant_snapshots: dict[UUID, dict[str, Any]] | None = None,
        resource_catalog: AIBuilderResourceCatalog | None = None,
    ) -> ToolRetryConfig:
        if flow is None:
            return ToolRetryConfig(
                target_tool_name=CREATE_FLOW_TOOL_NAME,
                forced_tool_prompt=(
                    "Your previous reply was prose only. "
                    "Now call create_flow with one complete typed draft. "
                    "Do not answer with prose."
                ),
                process_tool_arguments=self._process_create_arguments,
                process_tool_kwargs={},
            )

        return ToolRetryConfig(
            target_tool_name=EDIT_FLOW_TOOL_NAME,
            forced_tool_prompt=(
                "Your previous reply was prose only. "
                "Return one valid edit_flow tool call that keeps the flow coherent. "
                "Do not answer with prose."
            ),
            process_tool_arguments=self._process_edit_arguments,
            process_tool_kwargs={
                "assistant_snapshots": assistant_snapshots,
                "litellm_model": litellm_model,
                "litellm_kwargs": litellm_kwargs,
                "max_output_tokens": max_output_tokens,
                "resource_catalog": resource_catalog,
            },
        )

    def _confirm_requirements_retry_config(
        self, ctx: ProposalContext
    ) -> ToolRetryConfig:
        return ToolRetryConfig(
            target_tool_name=CONFIRM_REQUIREMENTS_TOOL_NAME,
            forced_tool_prompt=(
                "Return one valid confirm_requirements tool call. "
                "Do not answer with prose."
            ),
            process_tool_arguments=self._process_confirm_requirements_arguments,
            process_tool_kwargs={
                "litellm_model": ctx.litellm_model,
                "litellm_kwargs": ctx.litellm_kwargs,
            },
        )

    def _edit_flow_retry_config(self, ctx: ProposalContext) -> ToolRetryConfig:
        return ToolRetryConfig(
            target_tool_name=EDIT_FLOW_TOOL_NAME,
            forced_tool_prompt=(
                "Return one valid edit_flow tool call that keeps the flow coherent. "
                "Do not answer with prose."
            ),
            process_tool_arguments=self._process_edit_arguments,
            process_tool_kwargs={
                "assistant_snapshots": ctx.assistant_snapshots,
                "litellm_model": ctx.litellm_model,
                "litellm_kwargs": ctx.litellm_kwargs,
                "max_output_tokens": ctx.max_output_tokens,
                "resource_catalog": ctx.resource_catalog,
            },
        )


def _extract_description_provenance(
    metadata_json: dict[str, Any] | None,
) -> DescriptionProvenance | None:
    """Extract description provenance from flow metadata, if present."""
    if not isinstance(metadata_json, dict):
        return None
    ai_builder = metadata_json.get("ai_builder")
    if not isinstance(ai_builder, dict):
        return None
    desc_raw = cast(dict[str, Any], ai_builder).get("description")
    if not isinstance(desc_raw, dict):
        return None
    try:
        return DescriptionProvenance.model_validate(desc_raw)
    except Exception:
        return None


def _active_submission_tool_name(flow: "Flow | None") -> str:
    return EDIT_FLOW_TOOL_NAME if flow is not None else CREATE_FLOW_TOOL_NAME

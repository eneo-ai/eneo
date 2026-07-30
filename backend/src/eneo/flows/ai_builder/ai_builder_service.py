"""AI Builder service facade.

This module is intentionally small: session CRUD stays here, while the planner
conversation loop and plan lifecycle live in focused collaborators.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, AsyncGenerator, cast
from uuid import UUID

import litellm
from pydantic import ValidationError

from eneo.authentication.auth_models import ApiKeyPermission, ApiKeyScopeType
from eneo.files.file_models import File
from eneo.flows.ai_builder.ai_builder_api_models import (
    ApplyResultResponse,
    SessionListItemResponse,
)
from eneo.flows.ai_builder.ai_builder_attachment_context import (
    AIBuilderAttachmentContextPolicy,
    readable_attachment_text,
)
from eneo.flows.ai_builder.ai_builder_context import (
    AIBuilderPlannerContext,
    build_planner_context,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    AIBuilderQuestionAnswerInput,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderStreamEvent
from eneo.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_DONE as _SSE_EVENT_DONE,
)
from eneo.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_ERROR as _SSE_EVENT_ERROR,
)
from eneo.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_PLAN as _SSE_EVENT_PLAN,
)
from eneo.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_QUESTION as _SSE_EVENT_QUESTION,
)
from eneo.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_STATUS as _SSE_EVENT_STATUS,
)
from eneo.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_TEXT as _SSE_EVENT_TEXT,
)
from eneo.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_USAGE as _SSE_EVENT_USAGE,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from eneo.flows.ai_builder.ai_builder_plan_lifecycle import (
    AIBuilderPlanLifecycle,
    CreateFromPlanOutcome,
    raise_persisted_flow_mcp_plan_error,
)
from eneo.flows.ai_builder.ai_builder_planner import AIBuilderPlanner
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableKnowledgeBaseResource,
    AIBuilderAvailableModelResource,
)
from eneo.flows.ai_builder.ai_builder_session_turn import SessionTurnPreflight
from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshots
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.main.exceptions import NotFoundException
from eneo.model_providers.infrastructure.litellm_runtime_config import (
    configure_litellm_runtime,
)

if TYPE_CHECKING:
    from eneo.completion_models.infrastructure.completion_service import (
        CompletionService,
        ResolvedCompletionModelRoute,
    )
    from eneo.files.file_service import FileService
    from eneo.flows.application.flow_service import FlowService
    from eneo.flows.domain.flow import Flow
    from eneo.flows.flow_template_asset_service import FlowTemplateAssetService
    from eneo.spaces.space import Space
    from eneo.spaces.space_service import SpaceService
    from eneo.users.user import UserInDB

PLANNER_TEMPERATURE = 0.4  # Lower for precise proposal generation
SELF_CORRECTION_TEMPERATURE = 0.35
SELF_CORRECTION_BUMPED_TEMPERATURE = 0.6
FORCED_PROPOSAL_TEMPERATURE = 0.1
QUALITY_RETRY_WARNING_CODES = {
    "json_output_no_contract",
}

SSE_EVENT_TEXT = _SSE_EVENT_TEXT
SSE_EVENT_PLAN = _SSE_EVENT_PLAN
SSE_EVENT_QUESTION = _SSE_EVENT_QUESTION
SSE_EVENT_ERROR = _SSE_EVENT_ERROR
SSE_EVENT_STATUS = _SSE_EVENT_STATUS
SSE_EVENT_USAGE = _SSE_EVENT_USAGE
SSE_EVENT_DONE = _SSE_EVENT_DONE

_AI_BUILDER_CONTROLLED_TOOL_KEYS = frozenset({"tools", "tool_choice", "function_call"})

configure_litellm_runtime(litellm)


def _sanitize_ai_builder_litellm_kwargs(
    litellm_kwargs: dict[str, object],
) -> dict[str, object]:
    """Keep provider credentials separate from AI Builder tool-call control.

    Proposal generation intentionally uses LiteLLM tool calls for the internal
    `propose_flow` tool. That schema is passed by the proposal
    boundary itself, not by tenant model credential resolution. Dropping inherited
    tool-call keys here prevents accidental provider/MCP tool execution during
    planner turns and avoids duplicate keyword conflicts in proposal calls.
    """
    return {
        key: value
        for key, value in litellm_kwargs.items()
        if key not in _AI_BUILDER_CONTROLLED_TOOL_KEYS
    }


@dataclass(frozen=True)
class PreparedMessageContext:
    """Pre-fetched planner and flow context for AI Builder message handling."""

    planner_context: AIBuilderPlannerContext
    completion_model_route: ResolvedCompletionModelRoute
    flow: "Flow | None"
    assistant_snapshots: AssistantAuthoringSnapshots | None
    attachment_files: list[File]
    session_attachment_file_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class SessionAttachmentSnapshot:
    files: list[File]
    warnings: list[str]


def _format_attachment_name_list(names: list[str], *, limit: int = 3) -> str:
    unique_names = list(dict.fromkeys(name for name in names if name))
    shown = unique_names[:limit]
    if not shown:
        return "unknown files"
    if len(unique_names) <= limit:
        return ", ".join(shown)
    remaining = len(unique_names) - limit
    return f"{', '.join(shown)}, and {remaining} more"


class AIBuilderService:
    """Composition root for AI Builder session, planner, and apply flows."""

    def __init__(
        self,
        user: "UserInDB",
        repo: AIBuilderRepository,
        flow_service: "FlowService",
        completion_service: "CompletionService",
        space_service: "SpaceService",
        template_asset_service: "FlowTemplateAssetService",
        file_service: "FileService | None" = None,
    ) -> None:
        self.user = user
        self.repo = repo
        self.flow_service = flow_service
        self.completion_service = completion_service
        self.file_service = file_service
        self.space_service = space_service
        self.template_asset_service = template_asset_service

    async def create_session(
        self,
        *,
        space_id: UUID,
        target_kind: TargetKind,
        flow_id: UUID | None = None,
        force_new: bool = False,
    ) -> BuilderSession:
        if target_kind == TargetKind.EDIT and flow_id is None:
            raise AIBuilderBadRequestException(
                "flow_id is required for edit sessions.",
                code=AIBuilderErrorCode.EDIT_SESSION_FLOW_REQUIRED,
            )

        if flow_id is not None:
            flow = await self.flow_service.get_flow(flow_id)
            self._assert_flow_in_space(flow=flow, space_id=space_id)

        await self.repo.acquire_session_creation_lock(tenant_id=self.user.tenant_id)

        should_resume_existing = target_kind == TargetKind.EDIT and not force_new
        if should_resume_existing:
            existing_session = await self.repo.find_latest_resumable_session(
                tenant_id=self.user.tenant_id,
                actor_user_id=self.user.id,
                space_id=space_id,
                target_kind=target_kind,
                flow_id=flow_id,
            )
            if existing_session is not None:
                return existing_session

        if force_new:
            cancelled_session_ids = await self.repo.cancel_matching_active_sessions(
                tenant_id=self.user.tenant_id,
                actor_user_id=self.user.id,
                space_id=space_id,
                target_kind=target_kind,
                flow_id=flow_id,
            )
            await self._supersede_cancelled_session_plans(cancelled_session_ids)

        return await self.repo.create_session(
            tenant_id=self.user.tenant_id,
            space_id=space_id,
            actor_user_id=self.user.id,
            target_kind=target_kind,
            flow_id=flow_id,
        )

    async def _supersede_cancelled_session_plans(
        self,
        cancelled_session_ids: object,
    ) -> None:
        """Supersede actionable plans from sessions replaced by a fresh start."""

        if not isinstance(cancelled_session_ids, list | tuple | set):
            return

        for session_id in cast(
            list[object] | tuple[object, ...] | set[object], cancelled_session_ids
        ):
            if isinstance(session_id, UUID):
                await self.repo.supersede_existing_plans(
                    session_id=session_id,
                    tenant_id=self.user.tenant_id,
                )

    async def get_session(self, session_id: UUID) -> BuilderSession:
        return await self.repo.get_session(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )

    async def preflight_message_turn(
        self,
        *,
        session_id: UUID,
        client_turn_id: UUID,
        request_fingerprint: str,
        acknowledge_duplicate_provider_spend: bool,
    ) -> SessionTurnPreflight:
        return await self.repo.preflight_session_turn(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            client_turn_id=client_turn_id,
            request_fingerprint=request_fingerprint,
            acknowledge_duplicate_provider_spend=(acknowledge_duplicate_provider_spend),
        )

    async def get_plan(self, plan_id: UUID) -> BuilderPlan:
        try:
            return await self.repo.get_plan(
                plan_id=plan_id,
                tenant_id=self.user.tenant_id,
            )
        except ValidationError as exc:
            raise_persisted_flow_mcp_plan_error(exc)
            raise

    async def list_session_plans(self, session_id: UUID) -> list[BuilderPlan]:
        try:
            return await self.repo.list_session_plans(
                session_id=session_id,
                tenant_id=self.user.tenant_id,
            )
        except ValidationError as exc:
            raise_persisted_flow_mcp_plan_error(exc)
            raise

    async def list_sessions(self) -> list[SessionListItemResponse]:
        active_api_key = self.user.active_api_key
        scoped_space_id: UUID | None = None
        if active_api_key is not None:
            if active_api_key.permission not in {
                ApiKeyPermission.WRITE,
                ApiKeyPermission.ADMIN,
            }:
                return []

            scope_type = active_api_key.scope_type
            scope_id = active_api_key.scope_id
            if scope_type != ApiKeyScopeType.TENANT and scope_id is None:
                return []
            if scope_type == ApiKeyScopeType.SPACE:
                scoped_space_id = scope_id
            elif scope_type in {ApiKeyScopeType.ASSISTANT, ApiKeyScopeType.APP}:
                if scope_id is None:
                    return []
                try:
                    if scope_type == ApiKeyScopeType.ASSISTANT:
                        space = await self.space_service.get_space_by_assistant(
                            scope_id
                        )
                    else:
                        space = await self.space_service.get_space_by_app(scope_id)
                except NotFoundException:
                    return []
                scoped_space_id = space.id
            elif scope_type != ApiKeyScopeType.TENANT:
                return []

        sessions = await self.repo.list_sessions_with_draft_titles(
            tenant_id=self.user.tenant_id,
            actor_user_id=self.user.id,
            actor_user_group_ids=self.user.user_groups_ids,
            scoped_space_id=scoped_space_id,
        )
        return [
            (
                SessionListItemResponse(
                    session_id=session.id,
                    space_id=session.space_id,
                    status=session.status,
                    target_kind=session.target_kind,
                    flow_id=session.flow_id,
                    latest_plan_id=session.latest_plan_id,
                    draft_title=draft_title,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                )
            )
            for session, draft_title in sessions
        ]

    async def cancel_session(self, session_id: UUID) -> BuilderSession:
        await self.get_session(session_id)
        await self.repo.cancel_session(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )
        return await self.get_session(session_id)

    async def prepare_message_context(
        self,
        *,
        session: BuilderSession,
        space: "Space",
        model_id: UUID | None,
        tenant_flow_settings: dict[str, Any] | None,
        message: str | None = None,
        message_file_ids: list[UUID] | None = None,
    ) -> PreparedMessageContext:
        """Pre-fetch planner, provider, and flow-edit context before SSE streaming."""
        planner_context = build_planner_context(
            space,
            model_id=model_id,
            tenant_flow_settings=tenant_flow_settings,
        )
        if (
            message is not None
            and len(message) > planner_context.budget_policy.max_message_chars
        ):
            raise AIBuilderBadRequestException(
                "AI Builder messages support at most "
                f"{planner_context.budget_policy.max_message_chars} characters. "
                "Shorten the message or ask an administrator to review the Builder limit.",
                code=AIBuilderErrorCode.BAD_REQUEST,
                context={
                    "actual_chars": len(message),
                    "max_chars": planner_context.budget_policy.max_message_chars,
                },
            )
        session_file_ids = await self.repo.list_session_file_ids(
            session_id=session.id,
            tenant_id=self.user.tenant_id,
        )
        merged_file_ids = set(session_file_ids)
        merged_file_ids.update(message_file_ids or ())
        if len(merged_file_ids) > planner_context.budget_policy.max_attachments:
            raise AIBuilderBadRequestException(
                "AI Builder sessions support at most "
                f"{planner_context.budget_policy.max_attachments} attachments. "
                "Detach an existing attachment or ask an administrator to review "
                "the Builder limit.",
                code=AIBuilderErrorCode.BAD_REQUEST,
                context={
                    "actual_attachments": len(merged_file_ids),
                    "max_attachments": planner_context.budget_policy.max_attachments,
                },
            )

        route = await self.completion_service.resolve_model_route(
            planner_context.model,
        )
        route = replace(
            route,
            litellm_kwargs=_sanitize_ai_builder_litellm_kwargs(route.litellm_kwargs),
        )

        flow = None
        assistant_snapshots = None
        if session.flow_id is not None:
            flow = await self.flow_service.get_flow(session.flow_id)
            self._assert_flow_in_space(flow=flow, space_id=session.space_id)
            assistant_snapshots = await self.flow_service.get_flow_assistant_snapshots(
                flow
            )

        validated_files: list[File] = []
        if message_file_ids:
            if self.file_service is None:
                raise RuntimeError(
                    "FileService is required for AI Builder attachments."
                )
            validated_files = await self.file_service.get_files_by_ids(message_file_ids)
            if len({file.id for file in validated_files}) != len(set(message_file_ids)):
                raise AIBuilderBadRequestException(
                    "One or more referenced files are unavailable for this AI Builder session.",
                    code=AIBuilderErrorCode.BUILDER_ATTACHMENT_UNAVAILABLE,
                )

        attachment_files: list[File] = []
        if session_file_ids:
            if self.file_service is None:
                raise RuntimeError(
                    "FileService is required for AI Builder attachments."
                )
            attachment_files = await self.file_service.get_files_by_ids(
                session_file_ids
            )
        merged_files: dict[UUID, File] = {file.id: file for file in attachment_files}
        for file in validated_files:
            merged_files[file.id] = file
        attachment_files = list(merged_files.values())

        return PreparedMessageContext(
            planner_context=planner_context,
            completion_model_route=route,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            attachment_files=attachment_files,
            session_attachment_file_ids=tuple(session_file_ids),
        )

    @staticmethod
    def _assert_flow_in_space(*, flow: Any, space_id: UUID) -> None:
        if getattr(flow, "space_id", None) != space_id:
            raise AIBuilderBadRequestException(
                "Flow space does not match the AI builder session space.",
                code=AIBuilderErrorCode.FLOW_SPACE_MISMATCH,
            )

    async def send_message(
        self,
        *,
        session_id: UUID,
        client_turn_id: UUID,
        request_fingerprint: str,
        request_snapshot: FlowPersistedJsonObject,
        acknowledge_duplicate_provider_spend: bool = False,
        message: str,
        file_ids: list[UUID] | None = None,
        question_answer: AIBuilderQuestionAnswerInput | None = None,
        edit_context: AIBuilderPlanEditContext | None = None,
        ui_language: str | None = None,
        completion_model_route: ResolvedCompletionModelRoute,
        available_models: list[AIBuilderAvailableModelResource] | None = None,
        available_kbs: list[AIBuilderAvailableKnowledgeBaseResource] | None = None,
        flow: "Flow | None" = None,
        assistant_snapshots: AssistantAuthoringSnapshots | None = None,
        attachment_files: list[File] | None = None,
        max_input_tokens: int | None = None,
        max_output_tokens: int | None = None,
        budget_policy: AIBuilderBudgetPolicy | None = None,
        attachment_context_policy: AIBuilderAttachmentContextPolicy | None = None,
        mapped_execution_policy: FlowMappedExecutionPolicy | None = None,
        turn_preflight: SessionTurnPreflight | None = None,
    ) -> AsyncGenerator[AIBuilderStreamEvent, None]:
        if turn_preflight is None:
            turn_preflight = await self.preflight_message_turn(
                session_id=session_id,
                client_turn_id=client_turn_id,
                request_fingerprint=request_fingerprint,
                acknowledge_duplicate_provider_spend=(
                    acknowledge_duplicate_provider_spend
                ),
            )
        planner = self._build_planner()
        async for event in planner.send_message(
            session_id=session_id,
            client_turn_id=client_turn_id,
            request_fingerprint=request_fingerprint,
            request_snapshot=request_snapshot,
            acknowledge_duplicate_provider_spend=(acknowledge_duplicate_provider_spend),
            message=message,
            question_answer=question_answer,
            edit_context=edit_context,
            ui_language=ui_language,
            completion_model_route=completion_model_route,
            available_models=available_models,
            available_kbs=available_kbs,
            flow=flow,
            assistant_snapshots=assistant_snapshots,
            attachment_files=attachment_files or [],
            file_ids=file_ids,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            budget_policy=budget_policy,
            attachment_context_policy=attachment_context_policy,
            mapped_execution_policy=mapped_execution_policy,
            turn_preflight=turn_preflight,
        ):
            yield event

    async def get_session_attachment_snapshot(
        self,
        *,
        session_id: UUID,
    ) -> SessionAttachmentSnapshot:
        if self.file_service is None:
            return SessionAttachmentSnapshot(files=[], warnings=[])
        file_ids = await self.repo.list_session_file_ids(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
        )
        if not file_ids:
            return SessionAttachmentSnapshot(files=[], warnings=[])

        files = await self.file_service.get_files_by_ids(file_ids)
        warnings: list[str] = []
        if len({file.id for file in files}) != len(set(file_ids)):
            warnings.append(
                "One or more previously attached reference files are no longer available to this AI Builder session."
            )
        unreadable_files = [
            file.name for file in files if readable_attachment_text(file) is None
        ]
        if unreadable_files:
            warnings.append(
                "Attached reference files do not currently contain readable extracted text or transcription for AI Builder planning: "
                f"{_format_attachment_name_list(unreadable_files)}."
            )
        return SessionAttachmentSnapshot(files=files, warnings=warnings)

    async def detach_session_attachment(
        self,
        *,
        session_id: UUID,
        file_id: UUID,
    ) -> None:
        await self.repo.detach_session_file(
            session_id=session_id,
            tenant_id=self.user.tenant_id,
            file_id=file_id,
        )

    async def approve_plan(self, *, plan_id: UUID) -> BuilderPlan:
        return await self._build_plan_lifecycle().approve_plan(plan_id=plan_id)

    async def approve_and_apply_create_plan(
        self, *, plan_id: UUID
    ) -> CreateFromPlanOutcome:
        return await self._build_plan_lifecycle().approve_and_apply_create_plan(
            plan_id=plan_id
        )

    async def apply_plan(
        self,
        *,
        plan_id: UUID,
        expected_revision: int | None = None,
    ) -> ApplyResultResponse:
        return await self._build_plan_lifecycle().apply_plan(
            plan_id=plan_id,
            expected_revision=expected_revision,
        )

    async def revise_plan(
        self,
        *,
        plan_id: UUID,
        revision_type: str,
    ) -> BuilderPlan:
        return await self._build_plan_lifecycle().revise_plan(
            plan_id=plan_id,
            revision_type=revision_type,
        )

    def _build_planner(self) -> AIBuilderPlanner:
        return AIBuilderPlanner(
            user=self.user,
            repo=self.repo,
            litellm_client=litellm,
            planner_temperature=PLANNER_TEMPERATURE,
            self_correction_temperature=SELF_CORRECTION_TEMPERATURE,
            self_correction_bumped_temperature=SELF_CORRECTION_BUMPED_TEMPERATURE,
            forced_proposal_temperature=FORCED_PROPOSAL_TEMPERATURE,
            quality_retry_warning_codes=QUALITY_RETRY_WARNING_CODES,
        )

    def _build_plan_lifecycle(self) -> AIBuilderPlanLifecycle:
        return AIBuilderPlanLifecycle(
            user=self.user,
            repo=self.repo,
            flow_service=self.flow_service,
            space_service=self.space_service,
            template_asset_service=self.template_asset_service,
        )

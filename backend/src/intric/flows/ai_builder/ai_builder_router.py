"""API endpoints for the AI Flow Builder."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status
from fastapi.responses import JSONResponse, Response
from sse_starlette import EventSourceResponse, ServerSentEvent

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.files.file_models import FilePublic
from intric.flows.ai_builder.ai_builder_api_models import (
    ApplyPlanRequest,
    ApplyResultResponse,
    CreateSessionRequest,
    PlanApprovalResponse,
    PlanResponse,
    RevisePlanRequest,
    SendMessageRequest,
    SessionListResponse,
    SessionModelOption,
    SessionModelsResponse,
    SessionPlansResponse,
    SessionResponse,
    SessionTelemetrySummary,
)
from intric.flows.ai_builder.ai_builder_context import (
    resolve_planner_model,
    serialize_space_kbs,
    serialize_space_models,
)
from intric.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_DONE,
    SSE_EVENT_ERROR,
    SSE_EVENT_STATUS,
    SSE_EVENT_USAGE,
    build_error_event,
    build_usage_event,
)
from intric.flows.ai_builder.ai_builder_models import (
    ApplyResultResponse as ApplyResult,
)
from intric.flows.ai_builder.ai_builder_models import (
    BuilderPlan,
    BuilderSession,
    SessionListItemResponse,
)
from intric.flows.ai_builder.ai_builder_service import (
    AIBuilderService,
    PreparedMessageContext,
)
from intric.flows.ai_builder.ai_builder_telemetry import (
    summarize_session_telemetry,
)
from intric.flows.flow_permissions import ensure_can_use_flow_ai_builder
from intric.main.container.container import Container
from intric.main.exceptions import (
    BadRequestException,
    ErrorCodes,
    NotFoundException,
    UnauthorizedException,
)
from intric.main.models import GeneralError
from intric.server.dependencies.container import get_container

if TYPE_CHECKING:
    from intric.audit.application.audit_service import AuditService
    from intric.spaces.space import Space
    from intric.tenants.tenant_repo import TenantRepository

router = APIRouter(prefix="/ai-builder", tags=["ai-builder"])
logger = logging.getLogger(__name__)


EventStream = AsyncGenerator[dict[str, str], None]


def _scope_type_to_str(scope_type: object) -> str | None:
    if isinstance(scope_type, str):
        return scope_type
    value = getattr(scope_type, "value", None)
    if isinstance(value, str):
        return value
    return None


async def _coerce_event_stream(
    stream: EventStream | Awaitable[EventStream],
) -> EventStream:
    if hasattr(stream, "__aiter__"):
        return cast(EventStream, stream)
    return await cast(Awaitable[EventStream], stream)


async def _current_usage_event(
    *,
    service: "AIBuilderService",
    session_id: UUID,
) -> dict[str, str] | None:
    session = await service.get_session(session_id)
    telemetry = summarize_session_telemetry(session.conversation)
    if telemetry is None:
        return None
    return build_usage_event(
        SessionTelemetrySummary.model_validate(telemetry).model_dump(mode="json")
    )


async def _resolve_litellm_params(
    service: Any, model: Any
) -> tuple[str, dict[str, object]]:
    """Compatibility seam for tests and thin router-level planner resolution."""
    return await service.resolve_planner_params(model)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_flow_edit_permission(container: Container, space: "Space") -> None:
    ensure_can_use_flow_ai_builder(container.user())
    actor = container.actor_manager().get_space_actor_from_space(space)
    if not actor.can_edit_flows():
        raise UnauthorizedException(
            "You do not have permission to use the AI builder in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )


async def _require_flow_edit_permission(
    container: Container,
    space_id: UUID,
    *,
    space: "Space | None" = None,
) -> "Space":
    """Check that the current user can edit flows in the given space."""
    resolved_space = space
    if resolved_space is None:
        resolved_space = await container.space_service().get_space(space_id)
    _ensure_flow_edit_permission(container, resolved_space)
    return resolved_space


def _ensure_session_creator(
    container: Container,
    session: BuilderSession,
) -> None:
    if session.actor_user_id != container.user().id:
        raise UnauthorizedException(
            "Only the session creator can access this AI builder session.",
            code="session_creator_required",
            context={"auth_layer": "session_creator"},
        )


def _raise_scope_mismatch() -> None:
    raise UnauthorizedException(
        "API key space scope does not match requested AI builder resource.",
        code="insufficient_scope",
        context={"auth_layer": "api_key_scope"},
    )


def _request_correlation_id(request: Request) -> str | None:
    request_id = request.headers.get("x-correlation-id") or request.headers.get(
        "x-request-id"
    )
    return request_id if isinstance(request_id, str) else None


def _require_ai_builder_scope(request: Request, *, space_id: UUID) -> None:
    """Enforce space-scoped API key compatibility for AI Builder routes."""
    state = getattr(request, "state", None)
    if state is None or getattr(state, "scope_enforcement_enabled", True) is False:
        return

    scope_type = getattr(state, "api_key_scope_type", None)
    scope_id = getattr(state, "api_key_scope_id", None)
    if not isinstance(scope_id, UUID):
        return

    scope_type_str = _scope_type_to_str(scope_type)
    if scope_type_str == "space" and scope_id != space_id:
        _raise_scope_mismatch()


def _get_ai_builder_scoped_space_id(request: Request) -> UUID | None:
    """Return the enforced space scope for API keys, if present."""
    state = getattr(request, "state", None)
    if state is None or getattr(state, "scope_enforcement_enabled", True) is False:
        return None

    scope_type = getattr(state, "api_key_scope_type", None)
    scope_id = getattr(state, "api_key_scope_id", None)
    if not isinstance(scope_id, UUID):
        return None

    scope_type_str = _scope_type_to_str(scope_type)
    if scope_type_str != "space":
        return None
    return scope_id


def _get_ai_builder_service(container: Container) -> AIBuilderService:
    return container.ai_builder_service()


async def _get_space_models(
    container: Container, space_id: UUID
) -> list[dict[str, str]]:
    """Get available completion models for a space."""
    space = await container.space_service().get_space(space_id)
    return serialize_space_models(space)


async def _get_space_kbs(container: Container, space_id: UUID) -> list[dict[str, str]]:
    """Get available knowledge bases for a space."""
    space = await container.space_service().get_space(space_id)
    return serialize_space_kbs(space)


async def _get_planner_model(container: Container, space_id: UUID) -> object:
    """Get a completion model to use for the AI builder planner."""
    space = await container.space_service().get_space(space_id)
    return resolve_planner_model(space)


_ROUTER_TEST_COMPAT_HELPERS = (
    _get_space_models,
    _get_space_kbs,
    _get_planner_model,
)


def _get_audit_service(container: Container) -> "AuditService":
    return container.audit_service()


def _get_tenant_repo(container: Container) -> "TenantRepository":
    return container.tenant_repo()


def _to_plan_response(plan: BuilderPlan) -> PlanResponse:
    public_envelope = plan.envelope.model_copy(update={"reasoning": None}, deep=True)
    return PlanResponse(
        plan_id=plan.id,
        session_id=plan.session_id,
        status=plan.status,
        spec_hash=plan.spec_hash,
        envelope=public_envelope,
        edit_result_json=plan.edit_result_json,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _to_file_public(file: object) -> FilePublic:
    if isinstance(file, FilePublic):
        return file
    return FilePublic(**cast(Any, file).model_dump())


def _to_session_response(
    session: BuilderSession,
    *,
    attachments: list[FilePublic] | None = None,
    attachment_warnings: list[str] | None = None,
) -> SessionResponse:
    telemetry = summarize_session_telemetry(session.conversation)
    return SessionResponse(
        session_id=session.id,
        status=session.status,
        target_kind=session.target_kind,
        flow_id=session.flow_id,
        latest_plan_id=session.latest_plan_id,
        telemetry=(
            SessionTelemetrySummary.model_validate(telemetry)
            if telemetry is not None
            else None
        ),
        conversation=session.conversation,
        attachments=attachments or [],
        attachment_warnings=attachment_warnings or [],
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _ai_builder_error_response(
    *,
    description: str,
    message: str,
    intric_error_code: ErrorCodes,
    code: str | None = None,
    context: dict[str, object] | None = None,
) -> dict[str, Any]:
    example: dict[str, Any] = {
        "message": message,
        "intric_error_code": int(intric_error_code),
    }
    if code is not None:
        example["code"] = code
    if context is not None:
        example["context"] = context
    return {
        "model": GeneralError,
        "description": description,
        "content": {"application/json": {"example": example}},
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_ai_builder_session",
    summary="Create AI Builder Session",
    description="Start or resume an AI Builder session for a space-scoped flow drafting workflow.",
    responses={
        201: {"description": "AI Builder session created."},
        400: _ai_builder_error_response(
            description="The request payload is valid JSON but cannot start a builder session in its current state.",
            message="A planner model is required to start an AI Builder session.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this space.",
            message="API key space scope does not match requested AI builder resource.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
    },
)
async def create_session(
    request: Request,
    body: CreateSessionRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    _require_ai_builder_scope(request, space_id=body.space_id)
    space = await _require_flow_edit_permission(container, body.space_id)
    resolve_planner_model(space)

    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.create_session(
        space_id=body.space_id,
        target_kind=body.target_kind,
        flow_id=body.flow_id,
        force_new=body.force_new,
    )
    attachment_snapshot = await service.get_session_attachment_snapshot(
        session_id=session.id
    )

    # Audit
    user = container.user()
    audit_service = _get_audit_service(container)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.AI_BUILDER_SESSION_CREATED,
        entity_type=EntityType.AI_BUILDER_SESSION,
        entity_id=session.id,
        description=f"Started AI builder session ({session.target_kind.value})",
        metadata=AuditMetadata.standard(
            actor=user,
            target=session,
            extra={
                "target_kind": session.target_kind.value,
                "flow_id": str(session.flow_id) if session.flow_id else None,
            },
        ),
    )

    return _to_session_response(
        session,
        attachments=[_to_file_public(file) for file in attachment_snapshot.files],
        attachment_warnings=list(attachment_snapshot.warnings),
    )


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    operation_id="list_ai_builder_sessions",
    summary="List AI Builder Sessions",
    description="List AI Builder sessions visible to the caller within their permitted spaces.",
    responses={
        200: {"description": "Visible AI Builder sessions."},
        403: _ai_builder_error_response(
            description="Caller lacks permission to use the AI Builder.",
            message="You do not have permission to use the AI builder in this space.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        ),
    },
)
async def list_sessions(
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    ensure_can_use_flow_ai_builder(container.user())
    service = _get_ai_builder_service(container)
    sessions: list[SessionListItemResponse] = await service.list_sessions()
    scoped_space_id = _get_ai_builder_scoped_space_id(request)

    visible_sessions: list[SessionListItemResponse] = []
    for session in sessions:
        if scoped_space_id is not None and session.space_id != scoped_space_id:
            continue
        try:
            space = await container.space_service().get_space(session.space_id)
        except NotFoundException:
            logger.warning(
                "Skipping AI builder session because its space could not be loaded.",
                extra={
                    "session_id": str(session.session_id),
                    "space_id": str(session.space_id),
                },
                exc_info=True,
            )
            continue

        try:
            _ensure_flow_edit_permission(container, space)
        except UnauthorizedException:
            continue
        visible_sessions.append(session)

    return SessionListResponse(sessions=visible_sessions)


@router.post(
    "/sessions/{session_id}/messages",
    operation_id="send_ai_builder_message",
    summary="Send AI Builder Message",
    description=(
        "Send a user message to an AI Builder session and receive planner events as "
        "a server-sent event stream."
    ),
    responses={
        200: {
            "description": "Server-sent event stream with planner status, text, question, plan, error, and done events.",
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": (
                        "event: status\n"
                        'data: {"status":"thinking"}\n\n'
                        "event: text\n"
                        'data: {"text":"I need one more detail."}\n\n'
                        "event: done\n"
                        "data: \n\n"
                    ),
                }
            },
        },
        400: _ai_builder_error_response(
            description="The AI Builder session cannot accept a new message in its current state.",
            message="Cannot send messages in this AI Builder session right now.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this session.",
            message="API key space scope does not match requested AI builder resource.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session or referenced flow context was not found.",
            message="AI Builder session not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def send_message(
    request: Request,
    session_id: Annotated[
        UUID,
        Path(
            description="Identifier of the AI Builder session that will receive the message."
        ),
    ],
    body: SendMessageRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    _require_ai_builder_scope(request, space_id=session.space_id)
    space = await _require_flow_edit_permission(container, session.space_id)
    _ensure_session_creator(container, session)
    tenant = await _get_tenant_repo(container).get(container.user().tenant_id)
    prepared_context: PreparedMessageContext = await service.prepare_message_context(
        session=session,
        space=space,
        model_id=body.model_id,
        tenant_flow_settings=tenant.flow_settings if tenant else None,
        message_file_ids=body.file_ids,
        planner_params_resolver=lambda model: _resolve_litellm_params(service, model),
    )

    async def event_stream() -> AsyncGenerator[ServerSentEvent, None]:
        try:
            stream = await _coerce_event_stream(
                service.send_message(
                    session_id=session_id,
                    message=body.message,
                    file_ids=body.file_ids,
                    question_answer=body.question_answer,
                    edit_context=body.edit_context,
                    ui_language=body.ui_language,
                    litellm_model=prepared_context.litellm_model,
                    litellm_kwargs=prepared_context.litellm_kwargs,
                    available_models=prepared_context.planner_context.available_models,
                    available_kbs=prepared_context.planner_context.available_kbs,
                    available_mcps=prepared_context.planner_context.available_mcps,
                    flow=prepared_context.flow,
                    assistant_snapshots=prepared_context.assistant_snapshots,
                    attachment_files=prepared_context.attachment_files,
                    max_input_tokens=prepared_context.planner_context.max_input_tokens,
                    max_output_tokens=prepared_context.planner_context.max_output_tokens,
                    budget_policy=prepared_context.planner_context.budget_policy,
                )
            )

            has_committed_event = False
            usage_event_emitted = False
            stream_error_seen = False
            # Keep DONE terminal. Usage can become available only after the
            # planner stream has committed its final conversation metadata.
            done_event: dict[str, str] | None = None
            async for event in stream:
                event_name = event["event"]
                if event_name == SSE_EVENT_DONE:
                    done_event = event
                    continue

                yield ServerSentEvent(
                    data=event["data"],
                    event=event_name,
                )

                if event_name not in {
                    SSE_EVENT_DONE,
                    SSE_EVENT_ERROR,
                    SSE_EVENT_STATUS,
                    SSE_EVENT_USAGE,
                }:
                    has_committed_event = True
                elif event_name == SSE_EVENT_ERROR:
                    stream_error_seen = True
                elif event_name == SSE_EVENT_USAGE:
                    usage_event_emitted = True

            if (
                has_committed_event
                and not usage_event_emitted
                and not stream_error_seen
            ):
                usage_event = await _current_usage_event(
                    service=service,
                    session_id=session_id,
                )
                if usage_event is not None:
                    yield ServerSentEvent(
                        data=usage_event["data"],
                        event=usage_event["event"],
                    )
            if done_event is not None:
                yield ServerSentEvent(
                    data=done_event["data"],
                    event=done_event["event"],
                )
        except BadRequestException as error:
            code = error.code or "bad_request"
            message = str(error) or "The AI Builder request could not be processed."
            logger.info(
                "AI Builder event stream rejected.",
                extra={
                    "session_id": str(session_id),
                    "space_id": str(session.space_id),
                    "code": code,
                },
            )
            error_event = build_error_event(
                message=message,
                code=code,
                phase="router",
                intric_error_code=ErrorCodes.BAD_REQUEST,
                request_id=_request_correlation_id(request),
            )
            yield ServerSentEvent(data=error_event["data"], event=error_event["event"])
            yield ServerSentEvent(data="", event=SSE_EVENT_DONE)
        except Exception as error:
            logger.error(
                "AI Builder event stream failed.",
                exc_info=error,
                extra={
                    "session_id": str(session_id),
                    "space_id": str(session.space_id),
                },
            )
            error_event = build_error_event(
                message="The AI Builder stream failed. Please try again.",
                code="planner_stream_failed",
                phase="router",
                request_id=_request_correlation_id(request),
            )
            yield ServerSentEvent(data=error_event["data"], event=error_event["event"])
            yield ServerSentEvent(data="", event=SSE_EVENT_DONE)

    return EventSourceResponse(event_stream(), ping=15)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    operation_id="get_ai_builder_session",
    summary="Get AI Builder Session",
    description="Return the current state and conversation for a single AI Builder session.",
    responses={
        200: {"description": "AI Builder session details."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this session.",
            message="API key space scope does not match requested AI builder resource.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_session(
    request: Request,
    session_id: Annotated[
        UUID,
        Path(description="Identifier of the AI Builder session to return."),
    ],
    container: Container = Depends(get_container(with_user=True)),
):
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    attachment_snapshot = await service.get_session_attachment_snapshot(
        session_id=session.id
    )
    _require_ai_builder_scope(request, space_id=session.space_id)
    await _require_flow_edit_permission(container, session.space_id)
    _ensure_session_creator(container, session)

    return _to_session_response(
        session,
        attachments=[_to_file_public(file) for file in attachment_snapshot.files],
        attachment_warnings=list(attachment_snapshot.warnings),
    )


@router.delete(
    "/sessions/{session_id}/attachments/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="detach_ai_builder_attachment",
    summary="Detach AI Builder Attachment",
    description="Remove a previously attached reference file from an AI Builder session without deleting the underlying file globally.",
)
async def detach_session_attachment(
    request: Request,
    session_id: UUID,
    file_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    _require_ai_builder_scope(request, space_id=session.space_id)
    await _require_flow_edit_permission(container, session.space_id)
    _ensure_session_creator(container, session)
    await service.detach_session_attachment(session_id=session.id, file_id=file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/sessions/{session_id}/models",
    response_model=SessionModelsResponse,
    operation_id="get_ai_builder_models",
    summary="List Session Models",
    description="Return the completion models available to the AI Builder in the session's space.",
    responses={
        200: {"description": "Available completion models and default planner model."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this session.",
            message="API key space scope does not match requested AI builder resource.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_session_models(
    request: Request,
    session_id: Annotated[
        UUID,
        Path(
            description="Identifier of the AI Builder session whose planner models should be listed."
        ),
    ],
    container: Container = Depends(get_container(with_user=True)),
):
    """Return the completion models available in the session's space."""
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    _require_ai_builder_scope(request, space_id=session.space_id)
    space = await _require_flow_edit_permission(container, session.space_id)
    _ensure_session_creator(container, session)
    models = serialize_space_models(space)
    default_model = resolve_planner_model(space)
    default_model_id = default_model.id if default_model else None

    return SessionModelsResponse(
        models=[SessionModelOption.model_validate(model) for model in models],
        default_model_id=default_model_id,
    )


@router.get(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    operation_id="get_ai_builder_plan",
    summary="Get AI Builder Plan",
    description="Fetch a stored AI Builder plan proposal for review or approval.",
    responses={
        200: {"description": "Stored AI Builder plan."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for the plan's session.",
            message="API key space scope does not match requested AI builder resource.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder plan not found.",
            message="AI Builder plan not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_plan(
    request: Request,
    plan_id: Annotated[
        UUID,
        Path(description="Identifier of the stored AI Builder plan revision to fetch."),
    ],
    container: Container = Depends(get_container(with_user=True)),
):
    service = _get_ai_builder_service(container)
    plan: BuilderPlan = await service.get_plan(plan_id)
    session: BuilderSession = await service.get_session(plan.session_id)
    _require_ai_builder_scope(request, space_id=session.space_id)
    await _require_flow_edit_permission(container, session.space_id)
    _ensure_session_creator(container, session)
    return _to_plan_response(plan)


@router.get(
    "/sessions/{session_id}/plans",
    response_model=SessionPlansResponse,
    operation_id="list_ai_builder_session_plans",
    summary="List Session Plans",
    description="List all plan revisions generated within a specific AI Builder session.",
    responses={
        200: {"description": "Stored plan revisions for the session."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this session.",
            message="API key space scope does not match requested AI builder resource.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def list_session_plans(
    request: Request,
    session_id: Annotated[
        UUID,
        Path(
            description="Identifier of the AI Builder session whose stored plans should be listed."
        ),
    ],
    container: Container = Depends(get_container(with_user=True)),
):
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    _require_ai_builder_scope(request, space_id=session.space_id)
    await _require_flow_edit_permission(container, session.space_id)
    _ensure_session_creator(container, session)
    plans: list[BuilderPlan] = await service.list_session_plans(session_id)
    return SessionPlansResponse(plans=[_to_plan_response(plan) for plan in plans])


@router.post(
    "/sessions/{session_id}/cancel",
    response_model=SessionResponse,
    operation_id="cancel_ai_builder_session",
    summary="Cancel AI Builder Session",
    description="Cancel an active AI Builder session and stop further planning work in that session.",
    responses={
        200: {"description": "AI Builder session cancelled."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this session.",
            message="API key space scope does not match requested AI builder resource.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def cancel_session(
    request: Request,
    session_id: Annotated[
        UUID,
        Path(description="Identifier of the active AI Builder session to cancel."),
    ],
    container: Container = Depends(get_container(with_user=True)),
):
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    _require_ai_builder_scope(request, space_id=session.space_id)
    await _require_flow_edit_permission(container, session.space_id)
    _ensure_session_creator(container, session)
    session = await service.cancel_session(session_id)

    user = container.user()
    audit_service = _get_audit_service(container)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.AI_BUILDER_SESSION_CANCELLED,
        entity_type=EntityType.AI_BUILDER_SESSION,
        entity_id=session.id,
        description="Cancelled AI builder session",
        metadata=AuditMetadata.standard(
            actor=user,
            target=session,
            extra={"target_kind": session.target_kind.value},
        ),
    )

    return _to_session_response(session)


@router.post(
    "/plans/{plan_id}/approve",
    response_model=PlanApprovalResponse,
    operation_id="approve_ai_builder_plan",
    summary="Approve AI Builder Plan",
    description="Mark a plan revision as approved so it can be applied to a flow.",
    responses={
        200: {"description": "Plan approved."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for the plan's session.",
            message="API key space scope does not match requested AI builder resource.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder plan not found.",
            message="AI Builder plan not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def approve_plan(
    request: Request,
    plan_id: Annotated[
        UUID,
        Path(description="Identifier of the AI Builder plan revision to approve."),
    ],
    container: Container = Depends(get_container(with_user=True)),
):
    service = _get_ai_builder_service(container)
    plan: BuilderPlan = await service.get_plan(plan_id)
    session: BuilderSession = await service.get_session(plan.session_id)
    _require_ai_builder_scope(request, space_id=session.space_id)
    await _require_flow_edit_permission(container, session.space_id)
    plan = await service.approve_plan(plan_id=plan_id)

    # Audit
    user = container.user()
    audit_service = _get_audit_service(container)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.AI_BUILDER_PLAN_APPROVED,
        entity_type=EntityType.AI_BUILDER_SESSION,
        entity_id=plan.session_id,
        description="Approved AI builder plan",
        metadata=AuditMetadata.standard(
            actor=user,
            target=plan,
            extra={"plan_id": str(plan.id)},
        ),
    )

    return PlanApprovalResponse(
        plan_id=plan.id,
        status=plan.status,
    )


@router.post(
    "/plans/{plan_id}/apply",
    response_model=ApplyResultResponse,
    operation_id="apply_ai_builder_plan",
    summary="Apply AI Builder Plan",
    description="Materialize an approved AI Builder plan into the target flow definition.",
    responses={
        200: {"description": "Plan applied to the target flow."},
        400: _ai_builder_error_response(
            description=(
                "The approved plan cannot be materialized in the current space configuration. "
                "Representative machine-readable codes include: transcription_model_required, "
                "invalid_existing_step_ref."
            ),
            message="A transcription model must be selected when using audio input steps.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="transcription_model_required",
        ),
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for the plan's session.",
            message="API key space scope does not match requested AI builder resource.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder plan not found.",
            message="AI Builder plan not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        409: _ai_builder_error_response(
            description="The target flow revision changed before apply completed.",
            message="Flow revision changed while applying the plan.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="stale_revision",
        ),
    },
)
async def apply_plan(
    request: Request,
    plan_id: Annotated[
        UUID,
        Path(
            description="Identifier of the approved AI Builder plan revision to apply to the target flow."
        ),
    ],
    body: ApplyPlanRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = _get_ai_builder_service(container)

    # Verify plan exists and get session for permission check
    plan: BuilderPlan = await service.get_plan(plan_id)
    session: BuilderSession = await service.get_session(plan.session_id)
    _require_ai_builder_scope(request, space_id=session.space_id)
    await _require_flow_edit_permission(container, session.space_id)

    try:
        result: ApplyResult = await service.apply_plan(
            plan_id=plan_id,
            expected_revision=body.expected_revision,
        )
    except BadRequestException as e:
        if getattr(e, "code", None) == "stale_revision":
            return JSONResponse(
                status_code=409,
                content=GeneralError(
                    message=str(e),
                    intric_error_code=ErrorCodes.BAD_REQUEST,
                    code="stale_revision",
                    context=getattr(e, "context", None),
                    request_id=_request_correlation_id(request),
                ).model_dump(exclude_none=True),
            )
        raise

    # Audit
    user = container.user()
    audit_service = _get_audit_service(container)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.AI_BUILDER_FLOW_APPLIED,
        entity_type=EntityType.FLOW,
        entity_id=result.flow_id,
        description=f"Applied AI builder plan: {result.steps_created} created, "
        f"{result.steps_updated} updated, {result.steps_removed} removed",
        metadata=AuditMetadata.standard(
            actor=user,
            target=SimpleNamespace(id=result.flow_id, name=result.flow_name),
            extra={
                "plan_id": str(plan_id),
                "steps_created": result.steps_created,
                "steps_updated": result.steps_updated,
                "steps_removed": result.steps_removed,
            },
        ),
    )

    return result


@router.post(
    "/plans/{plan_id}/revise",
    response_model=PlanResponse,
    operation_id="revise_ai_builder_plan",
    summary="Revise AI Builder Plan",
    description=(
        "Create a new plan revision with a structured change. "
        "Supports 'keep_current_description' (marks description as manually owned)."
    ),
    responses={
        200: {"description": "New plan revision created."},
        400: _ai_builder_error_response(
            description="Invalid revision request.",
            message="Can only revise proposed plans.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="plan_not_proposed",
        ),
        403: _ai_builder_error_response(
            description="Caller lacks permission.",
            message="Only the session creator can revise plans.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="session_creator_required",
        ),
    },
)
async def revise_plan(
    request: Request,
    plan_id: Annotated[
        UUID,
        Path(description="Identifier of the proposed AI Builder plan to revise."),
    ],
    body: RevisePlanRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = _get_ai_builder_service(container)

    # Verify plan exists and get session for permission check
    plan: BuilderPlan = await service.get_plan(plan_id)
    session: BuilderSession = await service.get_session(plan.session_id)
    _require_ai_builder_scope(request, space_id=session.space_id)
    await _require_flow_edit_permission(container, session.space_id)

    new_plan: BuilderPlan = await service.revise_plan(
        plan_id=plan_id,
        revision_type=body.type,
    )

    return _to_plan_response(new_plan)

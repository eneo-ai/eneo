"""API endpoints for the AI Flow Builder."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Annotated, Any, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette import EventSourceResponse, ServerSentEvent

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import get_scope_filter
from eneo.files.file_models import FilePublic
from eneo.flows.ai_builder.ai_builder_api_models import (
    AIBuilderClassifierDiagnostic,
    AIBuilderClassifierDiagnosticsResponse,
    AIBuilderConversationMessage,
    AIBuilderTurnLifecycleResponse,
    ApplyPlanRequest,
    ApplyResultResponse,
    CreateSessionRequest,
    PlanApprovalResponse,
    PlanResponse,
    RevisePlanRequest,
    SendMessageRequest,
    SessionListItemResponse,
    SessionListResponse,
    SessionModelOption,
    SessionModelsResponse,
    SessionPlansResponse,
    SessionResponse,
    SessionTelemetrySummary,
)
from eneo.flows.ai_builder.ai_builder_api_models import (
    ApplyResultResponse as ApplyResult,
)
from eneo.flows.ai_builder.ai_builder_context import (
    resolve_planner_model,
    serialize_space_models,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    question_answer_from_metadata,
    requirements_confirmation_from_metadata,
    requirements_summary_from_metadata,
    slot_classification_from_metadata,
    structured_question_payload_from_tool_arguments,
    tool_calls_from_message,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    BuilderTurnState,
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AI_BUILDER_ERROR_REGISTRY,
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
    AIBuilderErrorPhase,
    AIBuilderNotFoundException,
    AIBuilderPublicError,
    AIBuilderUnauthorizedException,
    ai_builder_error_example,
    build_ai_builder_error,
    build_ai_builder_error_event,
    coerce_ai_builder_error_code,
    split_ai_builder_error_context,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    AIBuilderDoneEvent,
    AIBuilderStreamEvent,
    AIBuilderUsageEvent,
    RequirementsSummaryPayload,
    StructuredQuestionPayload,
    ai_builder_stream_event_schema,
)
from eneo.flows.ai_builder.ai_builder_events import (
    SSE_EVENT_ERROR,
    SSE_EVENT_STATUS,
    SSE_EVENT_USAGE,
    build_committed_turn_replay_events,
    build_done_event,
    build_usage_event,
    encode_ai_builder_stream_event,
)
from eneo.flows.ai_builder.ai_builder_service import (
    AIBuilderService,
    PreparedMessageContext,
)
from eneo.flows.ai_builder.ai_builder_telemetry import (
    summarize_session_telemetry,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    ASK_STRUCTURED_QUESTION_TOOL_NAME,
    CONFIRM_REQUIREMENTS_TOOL_NAME,
)
from eneo.flows.flow_access_policy import (
    FlowAccessFilterMode,
    FlowApiAction,
    ai_builder_scoped_space_id,
    require_ai_builder_space_scope,
    require_flow_action,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.server.dependencies.container import (
    get_container,
    get_container_for_explicit_transaction,
)
from eneo.server.exception_handlers import extract_request_id

if TYPE_CHECKING:
    from eneo.audit.application.audit_service import AuditService
    from eneo.spaces.space import Space
    from eneo.tenants.tenant_repo import TenantRepository

logger = logging.getLogger(__name__)


def _public_error_code_from_exception(
    error: BadRequestException | UnauthorizedException | NotFoundException,
    *,
    default: AIBuilderErrorCode,
    request_id: str | None,
    surface: str,
) -> AIBuilderErrorCode:
    if isinstance(
        error,
        (
            AIBuilderBadRequestException,
            AIBuilderNotFoundException,
            AIBuilderUnauthorizedException,
        ),
    ):
        return error.code
    logger.error(
        "AI Builder raw public exception reached adapter.",
        extra={
            "request_id": request_id,
            "surface": surface,
            "raw_error_code": getattr(error, "code", None),
            "fallback_error_code": default.value,
        },
    )
    return coerce_ai_builder_error_code(getattr(error, "code", None), default=default)


class AIBuilderEnvelopedError(Exception):
    """Carries a prepared AI Builder error response past the dependency stack.

    The route adapter must RAISE (not return) on domain errors: only an
    exception reaches FastAPI's dependency teardown, where the request
    transaction rolls back. The app-level handler registered in server setup
    then returns the prepared envelope unchanged.
    """

    def __init__(self, response: Response) -> None:
        super().__init__("AI Builder request failed")
        self.response = response


def ai_builder_enveloped_error_handler(_request: Request, exc: Exception) -> Response:
    """App-level handler for AIBuilderEnvelopedError — register in server setup."""
    if not isinstance(exc, AIBuilderEnvelopedError):
        raise exc
    return exc.response


class AIBuilderPublicErrorRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_route_handler = super().get_route_handler()

        async def ai_builder_route_handler(request: Request) -> Response:
            try:
                return await original_route_handler(request)
            except BadRequestException as error:
                request_id = extract_request_id(request)
                raise AIBuilderEnvelopedError(
                    _ai_builder_json_error_response(
                        request=request,
                        message=str(error)
                        or "The AI Builder request could not be processed.",
                        code=_public_error_code_from_exception(
                            error,
                            default=AIBuilderErrorCode.BAD_REQUEST,
                            request_id=request_id,
                            surface="route_bad_request",
                        ),
                        exception_context=error.context,
                    )
                ) from error
            except UnauthorizedException as error:
                request_id = extract_request_id(request)
                raise AIBuilderEnvelopedError(
                    _ai_builder_json_error_response(
                        request=request,
                        message=str(error)
                        or "You do not have permission to use this AI Builder resource.",
                        code=_public_error_code_from_exception(
                            error,
                            default=AIBuilderErrorCode.INSUFFICIENT_SPACE_PERMISSION,
                            request_id=request_id,
                            surface="route_unauthorized",
                        ),
                        exception_context=error.context,
                    )
                ) from error
            except NotFoundException as error:
                request_id = extract_request_id(request)
                raise AIBuilderEnvelopedError(
                    _ai_builder_json_error_response(
                        request=request,
                        message=str(error) or "AI Builder resource not found.",
                        code=_public_error_code_from_exception(
                            error,
                            default=AIBuilderErrorCode.NOT_FOUND,
                            request_id=request_id,
                            surface="route_not_found",
                        ),
                        exception_context=error.context,
                    )
                ) from error

        return ai_builder_route_handler


router = APIRouter(
    prefix="/ai-builder",
    tags=["ai-builder"],
    route_class=AIBuilderPublicErrorRoute,
)


EventStream = AsyncGenerator[AIBuilderStreamEvent, None]
ContainerWithUserDep = Annotated[Container, Depends(get_container(with_user=True))]
ContainerWithUserExplicitTransactionDep = Annotated[
    Container,
    Depends(get_container_for_explicit_transaction(with_user=True)),
]


@dataclass(frozen=True)
class AIBuilderAuthorization:
    space: "Space | None" = None
    scoped_space_id: UUID | None = None


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
) -> AIBuilderUsageEvent | None:
    session = await service.get_session(session_id)
    telemetry = summarize_session_telemetry(session.conversation)
    if telemetry is None:
        return None
    return build_usage_event(SessionTelemetrySummary.model_validate(telemetry))


async def _resolve_litellm_params(
    service: Any, model: Any
) -> tuple[str, dict[str, object]]:
    """Compatibility seam for tests and thin router-level planner resolution."""
    return await service.resolve_planner_params(model)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_space_flow_edit_permission(container: Container, space: "Space") -> None:
    actor = container.actor_manager().get_space_actor_from_space(space)
    if not actor.can_edit_flows():
        raise AIBuilderUnauthorizedException(
            "You do not have permission to use the AI builder in this space.",
            code=AIBuilderErrorCode.INSUFFICIENT_SPACE_PERMISSION,
            context={"auth_layer": "space_membership"},
        )


async def _authorize_ai_builder_request(
    request: Request,
    container: Container,
    *,
    action: FlowApiAction,
    space_id: UUID | None = None,
    session: BuilderSession | None = None,
    require_creator: bool = False,
    filter_mode: FlowAccessFilterMode | None = None,
) -> AIBuilderAuthorization:
    require_flow_action(container.user(), action)
    scope_filter = get_scope_filter(request)

    if filter_mode == FlowAccessFilterMode.VISIBLE:
        return AIBuilderAuthorization(
            scoped_space_id=ai_builder_scoped_space_id(scope_filter)
        )

    if space_id is None:
        if require_creator and session is not None:
            _ensure_session_creator(container, session)
        return AIBuilderAuthorization()

    require_ai_builder_space_scope(
        scope_filter,
        space_id=space_id,
        raise_scope_mismatch=_raise_scope_mismatch,
    )
    space = await container.space_service().get_space(space_id)
    _ensure_space_flow_edit_permission(container, space)
    if require_creator and session is not None:
        _ensure_session_creator(container, session)
    return AIBuilderAuthorization(space=space)


def _authorized_space(authorization: AIBuilderAuthorization) -> "Space":
    if authorization.space is None:
        raise RuntimeError("AI Builder authorization did not load a space.")
    return authorization.space


def _ensure_session_creator(
    container: Container,
    session: BuilderSession,
) -> None:
    if session.actor_user_id != container.user().id:
        raise AIBuilderUnauthorizedException(
            "Only the session creator can access this AI builder session.",
            code=AIBuilderErrorCode.SESSION_CREATOR_REQUIRED,
            context={"auth_layer": "session_creator"},
        )


def _raise_scope_mismatch() -> NoReturn:
    raise AIBuilderUnauthorizedException(
        "API key space scope does not match requested AI builder resource.",
        code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
        context={"auth_layer": "api_key_scope"},
    )


def _get_ai_builder_service(container: Container) -> AIBuilderService:
    return container.ai_builder_service()


def _get_audit_service(container: Container) -> "AuditService":
    return container.audit_service()


def _get_tenant_repo(container: Container) -> "TenantRepository":
    return container.tenant_repo()


def _to_plan_response(plan: BuilderPlan) -> PlanResponse:
    return PlanResponse(
        plan_id=plan.id,
        session_id=plan.session_id,
        status=plan.status,
        spec_hash=plan.spec_hash,
        proposal=plan.proposal.content,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def _to_file_public(file: object) -> FilePublic:
    if isinstance(file, FilePublic):
        return file
    return FilePublic(**cast(Any, file).model_dump())


def _to_public_conversation(
    conversation: list[ConversationMessage],
) -> list[AIBuilderConversationMessage]:
    public_conversation: list[AIBuilderConversationMessage] = []
    for index, message in enumerate(conversation):
        if message.role == "user":
            public_conversation.append(_to_public_user_message(message))
            continue
        if message.role == "assistant":
            public_conversation.append(
                _to_public_assistant_message(conversation, index, message)
            )
    return public_conversation


def _classifier_diagnostic_runs(
    conversation: list[ConversationMessage],
) -> list[AIBuilderClassifierDiagnostic]:
    runs: list[AIBuilderClassifierDiagnostic] = []
    for message in conversation:
        classification = slot_classification_from_metadata(message.metadata)
        if classification is None:
            continue
        runs.append(
            AIBuilderClassifierDiagnostic.model_validate(
                {
                    **classification.model_dump(mode="json"),
                    "message_id": message.message_id,
                }
            )
        )
    return runs


def _to_public_user_message(
    message: ConversationMessage,
) -> AIBuilderConversationMessage:
    return AIBuilderConversationMessage(
        message_id=message.message_id,
        role="user",
        content=message.content,
        timestamp=message.timestamp,
        question_answer=question_answer_from_metadata(message.metadata),
        requirements_confirmation=requirements_confirmation_from_metadata(
            message.metadata
        ),
    )


def _to_public_assistant_message(
    conversation: list[ConversationMessage],
    index: int,
    message: ConversationMessage,
) -> AIBuilderConversationMessage:
    return AIBuilderConversationMessage(
        message_id=message.message_id,
        role="assistant",
        content=message.content,
        timestamp=message.timestamp,
        question=_structured_question_from_assistant_message(message),
        requirements_summary=_requirements_summary_for_assistant_message(
            conversation,
            index,
            message,
        ),
    )


def _structured_question_from_assistant_message(
    message: ConversationMessage,
) -> StructuredQuestionPayload | None:
    for tool_call in tool_calls_from_message(message):
        if tool_call.name != ASK_STRUCTURED_QUESTION_TOOL_NAME:
            continue
        payload = structured_question_payload_from_tool_arguments(tool_call.arguments)
        if payload is None:
            continue
        try:
            return StructuredQuestionPayload.model_validate(payload)
        except ValidationError:
            continue
    return None


def _requirements_summary_for_assistant_message(
    conversation: list[ConversationMessage],
    index: int,
    message: ConversationMessage,
) -> RequirementsSummaryPayload | None:
    parsed = requirements_summary_from_metadata(message.metadata)
    requirements_summary = parsed.requirements_summary if parsed is not None else None
    requirements_tool_call_ids = {
        tool_call.id
        for tool_call in tool_calls_from_message(message)
        if tool_call.name == CONFIRM_REQUIREMENTS_TOOL_NAME and tool_call.id
    }
    if not requirements_tool_call_ids:
        return requirements_summary

    for tool_message in conversation[index + 1 :]:
        if tool_message.role != "tool":
            break
        if tool_message.tool_call_id not in requirements_tool_call_ids:
            continue
        parsed_tool_summary = requirements_summary_from_metadata(tool_message.metadata)
        if parsed_tool_summary is not None:
            requirements_summary = parsed_tool_summary.requirements_summary
    return requirements_summary


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
        latest_turn=(
            AIBuilderTurnLifecycleResponse(
                client_turn_id=session.latest_turn.client_turn_id,
                state=session.latest_turn.state,
                user_message_id=session.latest_turn.user_message_id,
                error=session.latest_turn.error,
                requires_duplicate_provider_spend_acknowledgement=(
                    session.latest_turn.state
                    is BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN
                ),
                retry_request=SendMessageRequest.model_validate(
                    session.latest_turn.request
                ),
            )
            if session.latest_turn is not None
            else None
        ),
        telemetry=(
            SessionTelemetrySummary.model_validate(telemetry)
            if telemetry is not None
            else None
        ),
        conversation=_to_public_conversation(session.conversation),
        attachments=attachments or [],
        attachment_warnings=attachment_warnings or [],
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _ai_builder_error_response(
    *,
    description: str,
    message: str,
    code: AIBuilderErrorCode,
    details: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    return {
        "model": AIBuilderPublicError,
        "description": description,
        "content": {
            "application/json": {
                "example": ai_builder_error_example(
                    message=message,
                    code=code,
                    details=details,
                )
            }
        },
    }


def _merged_ai_builder_error_fields(
    *,
    exception_context: Mapping[str, object] | None = None,
    diagnostic_context: Mapping[str, object] | None = None,
    details: Mapping[str, object] | None = None,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    merged_diagnostic_context, merged_details = split_ai_builder_error_context(
        exception_context
    )
    if diagnostic_context is not None:
        merged_diagnostic_context = {
            **(merged_diagnostic_context or {}),
            **diagnostic_context,
        }
    if details is not None:
        merged_details = {**(merged_details or {}), **details}
    return merged_diagnostic_context, merged_details


def _ai_builder_json_error_response(
    *,
    request: Request,
    message: str,
    code: AIBuilderErrorCode,
    exception_context: Mapping[str, object] | None = None,
    diagnostic_context: Mapping[str, object] | None = None,
    details: Mapping[str, object] | None = None,
    phase: AIBuilderErrorPhase | None = None,
) -> JSONResponse:
    diagnostic_context, details = _merged_ai_builder_error_fields(
        exception_context=exception_context,
        diagnostic_context=diagnostic_context,
        details=details,
    )
    error = build_ai_builder_error(
        message=message,
        code=code,
        phase=phase,
        diagnostic_context=diagnostic_context,
        details=details,
        request_id=extract_request_id(request),
    )
    return JSONResponse(
        status_code=AI_BUILDER_ERROR_REGISTRY[code].http_status,
        content=error.model_dump(mode="json", exclude_none=True),
    )


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
            code=AIBuilderErrorCode.BAD_REQUEST,
        ),
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this space.",
            message="API key space scope does not match requested AI builder resource.",
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
    },
)
async def create_session(
    request: Request,
    body: CreateSessionRequest,
    container: ContainerWithUserDep,
):
    authorization = await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_SESSION_CREATE,
        space_id=body.space_id,
    )
    space = _authorized_space(authorization)
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
            code=AIBuilderErrorCode.INSUFFICIENT_SPACE_PERMISSION,
            details={"auth_layer": "space_membership"},
        ),
    },
)
async def list_sessions(
    request: Request,
    container: ContainerWithUserDep,
) -> SessionListResponse:
    authorization = await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_SESSION_LIST,
        filter_mode=FlowAccessFilterMode.VISIBLE,
    )
    service = _get_ai_builder_service(container)
    sessions: list[SessionListItemResponse] = await service.list_sessions()
    scoped_space_id = authorization.scoped_space_id

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
            _ensure_space_flow_edit_permission(container, space)
        except UnauthorizedException:
            continue
        visible_sessions.append(session)

    return SessionListResponse(sessions=visible_sessions)


@router.post(
    "/sessions/{session_id}/messages",
    operation_id="send_ai_builder_message",
    response_class=EventSourceResponse,
    response_model=None,
    summary="Send AI Builder Message",
    description=(
        "Send a user message to an AI Builder session and receive planner events as "
        "a server-sent event stream. One caller-generated client turn ID identifies "
        "one logical send: retry the same payload with the same ID, while a changed "
        "payload conflicts. This protection covers the latest accepted turn until a "
        "different turn is accepted or the session is deleted. A failed-before-provider "
        "turn can be retried safely. A provider-outcome-unknown turn is never retried "
        "automatically and requires explicit acknowledgement that provider work and cost "
        "may be repeated. Reload the session and use latest_turn.retry_request to replay "
        "the exact accepted request."
    ),
    responses={
        200: {
            "description": "Server-sent event stream with planner status, text, question, plan, error, and done events.",
            "content": {
                "text/event-stream": {
                    "schema": ai_builder_stream_event_schema(),
                    "example": (
                        "event: status\n"
                        'data: {"status":"repairing"}\n\n'
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
            code=AIBuilderErrorCode.BAD_REQUEST,
        ),
        409: _ai_builder_error_response(
            description=(
                "The client turn ID conflicts with a different payload, another turn "
                "is active, or the provider outcome is unknown and requires explicit "
                "duplicate-spend acknowledgement before retry."
            ),
            message=(
                "The provider outcome is unknown. Explicitly acknowledge possible "
                "duplicate provider work before retrying this turn."
            ),
            code=AIBuilderErrorCode.SESSION_TURN_PROVIDER_OUTCOME_UNKNOWN,
        ),
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this session.",
            message="API key space scope does not match requested AI builder resource.",
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session or referenced flow context was not found.",
            message="AI Builder session not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
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
    container: ContainerWithUserExplicitTransactionDep,
):
    service = _get_ai_builder_service(container)
    database_session = cast(AsyncSession, container.session())
    async with database_session.begin():
        session: BuilderSession = await service.get_session(session_id)
        authorization = await _authorize_ai_builder_request(
            request,
            container,
            action=FlowApiAction.BUILDER_MESSAGE_SEND,
            space_id=session.space_id,
            session=session,
            require_creator=True,
        )
        space = _authorized_space(authorization)
        tenant = await _get_tenant_repo(container).get(container.user().tenant_id)
        request_fingerprint = body.request_fingerprint()
        turn_preflight = await service.preflight_message_turn(
            session_id=session_id,
            client_turn_id=body.client_turn_id,
            request_fingerprint=request_fingerprint,
            acknowledge_duplicate_provider_spend=(
                body.acknowledge_duplicate_provider_spend
            ),
        )

    async def event_stream() -> AsyncGenerator[ServerSentEvent, None]:
        try:
            if turn_preflight.replayed:
                latest_turn = turn_preflight.session.latest_turn
                replay_error = latest_turn.error if latest_turn is not None else None
                for replay_event in build_committed_turn_replay_events(replay_error):
                    wire_event = encode_ai_builder_stream_event(replay_event)
                    yield ServerSentEvent(
                        data=wire_event["data"],
                        event=wire_event["event"],
                    )
                return
            try:
                async with database_session.begin():
                    prepared_context: PreparedMessageContext = (
                        await service.prepare_message_context(
                            session=turn_preflight.session,
                            space=space,
                            model_id=body.model_id,
                            tenant_flow_settings=(
                                tenant.flow_settings if tenant else None
                            ),
                            message_file_ids=body.file_ids,
                            planner_params_resolver=(
                                lambda model: _resolve_litellm_params(service, model)
                            ),
                        )
                    )
            except Exception:
                replay_preflight = await service.preflight_message_turn(
                    session_id=session_id,
                    client_turn_id=body.client_turn_id,
                    request_fingerprint=request_fingerprint,
                    acknowledge_duplicate_provider_spend=(
                        body.acknowledge_duplicate_provider_spend
                    ),
                )
                if replay_preflight.replayed:
                    latest_turn = replay_preflight.session.latest_turn
                    replay_error = (
                        latest_turn.error if latest_turn is not None else None
                    )
                    for replay_event in build_committed_turn_replay_events(
                        replay_error
                    ):
                        wire_event = encode_ai_builder_stream_event(replay_event)
                        yield ServerSentEvent(
                            data=wire_event["data"],
                            event=wire_event["event"],
                        )
                    return
                raise
            if (
                prepared_context.session_attachment_file_ids
                != turn_preflight.baseline.attachment_file_ids
            ):
                raise AIBuilderBadRequestException(
                    "The AI Builder session attachments changed while this turn was being prepared. Reload and retry the same turn.",
                    code=AIBuilderErrorCode.SESSION_MESSAGE_IN_PROGRESS,
                )
            stream = await _coerce_event_stream(
                service.send_message(
                    session_id=session_id,
                    client_turn_id=body.client_turn_id,
                    request_fingerprint=request_fingerprint,
                    request_snapshot=body.retry_snapshot(),
                    acknowledge_duplicate_provider_spend=(
                        body.acknowledge_duplicate_provider_spend
                    ),
                    message=body.message,
                    file_ids=body.file_ids,
                    question_answer=body.question_answer,
                    edit_context=body.edit_context,
                    ui_language=body.ui_language,
                    litellm_model=prepared_context.litellm_model,
                    litellm_kwargs=prepared_context.litellm_kwargs,
                    available_models=(
                        prepared_context.planner_context.available_models
                    ),
                    available_kbs=prepared_context.planner_context.available_kbs,
                    available_mcps=prepared_context.planner_context.available_mcps,
                    flow=prepared_context.flow,
                    assistant_snapshots=prepared_context.assistant_snapshots,
                    attachment_files=prepared_context.attachment_files,
                    max_input_tokens=(
                        prepared_context.planner_context.max_input_tokens
                    ),
                    max_output_tokens=(
                        prepared_context.planner_context.max_output_tokens
                    ),
                    budget_policy=prepared_context.planner_context.budget_policy,
                    turn_preflight=turn_preflight,
                )
            )

            has_committed_event = False
            usage_event_emitted = False
            stream_error_seen = False
            # Keep DONE terminal. Usage can become available only after the
            # planner stream has committed its final conversation metadata.
            done_event: AIBuilderDoneEvent | None = None
            async for event in stream:
                if isinstance(event, AIBuilderDoneEvent):
                    done_event = event
                    continue

                event_name = event.event
                wire_event = encode_ai_builder_stream_event(event)
                yield ServerSentEvent(
                    data=wire_event["data"],
                    event=wire_event["event"],
                )

                if event_name not in {
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
                    wire_usage_event = encode_ai_builder_stream_event(usage_event)
                    yield ServerSentEvent(
                        data=wire_usage_event["data"],
                        event=wire_usage_event["event"],
                    )
            if done_event is not None:
                wire_done_event = encode_ai_builder_stream_event(done_event)
                yield ServerSentEvent(
                    data=wire_done_event["data"],
                    event=wire_done_event["event"],
                )
        except BadRequestException as error:
            message = str(error) or "The AI Builder request could not be processed."
            request_id = extract_request_id(request)
            code = _public_error_code_from_exception(
                error,
                default=AIBuilderErrorCode.BAD_REQUEST,
                request_id=request_id,
                surface="event_stream_bad_request",
            )
            diagnostic_context, details = _merged_ai_builder_error_fields(
                exception_context=getattr(error, "context", None),
                diagnostic_context={
                    "session_id": str(session_id),
                    "space_id": str(session.space_id),
                },
            )
            logger.info(
                "AI Builder event stream rejected.",
                extra={
                    "request_id": request_id,
                    "session_id": str(session_id),
                    "space_id": str(session.space_id),
                    "error_code": code.value,
                },
            )
            error_event = build_ai_builder_error_event(
                message=message,
                code=code,
                diagnostic_context=diagnostic_context,
                details=details,
                request_id=request_id,
            )
            wire_error_event = encode_ai_builder_stream_event(error_event)
            yield ServerSentEvent(
                data=wire_error_event["data"],
                event=wire_error_event["event"],
            )
            done_event = build_done_event()
            wire_done_event = encode_ai_builder_stream_event(done_event)
            yield ServerSentEvent(
                data=wire_done_event["data"],
                event=wire_done_event["event"],
            )
        except Exception as error:
            request_id = extract_request_id(request)
            logger.error(
                "AI Builder event stream failed.",
                exc_info=error,
                extra={
                    "request_id": request_id,
                    "session_id": str(session_id),
                    "space_id": str(session.space_id),
                    "error_code": AIBuilderErrorCode.PLANNER_STREAM_FAILED.value,
                },
            )
            error_event = build_ai_builder_error_event(
                message="The AI Builder stream failed. Please try again.",
                code=AIBuilderErrorCode.PLANNER_STREAM_FAILED,
                diagnostic_context={
                    "session_id": str(session_id),
                    "space_id": str(session.space_id),
                },
                request_id=request_id,
            )
            wire_error_event = encode_ai_builder_stream_event(error_event)
            yield ServerSentEvent(
                data=wire_error_event["data"],
                event=wire_error_event["event"],
            )
            done_event = build_done_event()
            wire_done_event = encode_ai_builder_stream_event(done_event)
            yield ServerSentEvent(
                data=wire_done_event["data"],
                event=wire_done_event["event"],
            )

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
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
        ),
    },
)
async def get_session(
    request: Request,
    session_id: Annotated[
        UUID,
        Path(description="Identifier of the AI Builder session to return."),
    ],
    container: ContainerWithUserDep,
):
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    attachment_snapshot = await service.get_session_attachment_snapshot(
        session_id=session.id
    )
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_SESSION_READ,
        space_id=session.space_id,
        session=session,
        require_creator=True,
    )

    return _to_session_response(
        session,
        attachments=[_to_file_public(file) for file in attachment_snapshot.files],
        attachment_warnings=list(attachment_snapshot.warnings),
    )


@router.get(
    "/sessions/{session_id}/_diagnostics/classifier-slots",
    response_model=AIBuilderClassifierDiagnosticsResponse,
    description="Return comprehensive persisted classifier evidence for creator-only internal evaluation.",
    responses={
        200: {"description": "Persisted classifier diagnostics."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this session.",
            message="API key space scope does not match requested AI builder resource.",
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
        ),
    },
    include_in_schema=False,
)
async def get_session_classifier_diagnostics(
    request: Request,
    session_id: Annotated[
        UUID,
        Path(description="Identifier of the AI Builder session to inspect."),
    ],
    container: ContainerWithUserDep,
) -> AIBuilderClassifierDiagnosticsResponse:
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_SESSION_READ,
        space_id=session.space_id,
        session=session,
        require_creator=True,
    )
    return AIBuilderClassifierDiagnosticsResponse(
        session_id=session.id,
        classifier_runs=_classifier_diagnostic_runs(session.conversation),
    )


@router.delete(
    "/sessions/{session_id}/attachments/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    operation_id="detach_ai_builder_attachment",
    summary="Detach AI Builder Attachment",
    description="Remove a previously attached reference file from an AI Builder session without deleting the underlying file globally.",
    responses={
        204: {"description": "Attachment detached from the AI Builder session."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this session.",
            message="API key space scope does not match requested AI builder resource.",
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
        ),
        409: _ai_builder_error_response(
            description="Attachment detachment is blocked while an active send owns the session.",
            message="An active send is currently in progress for this session.",
            code=AIBuilderErrorCode.SESSION_SEND_IN_PROGRESS,
        ),
    },
)
async def detach_session_attachment(
    request: Request,
    session_id: UUID,
    file_id: UUID,
    container: ContainerWithUserDep,
):
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_ATTACHMENT_DETACH,
        space_id=session.space_id,
        session=session,
        require_creator=True,
    )
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
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
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
    container: ContainerWithUserDep,
):
    """Return the completion models available in the session's space."""
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    authorization = await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_MODELS_LIST,
        space_id=session.space_id,
        session=session,
        require_creator=True,
    )
    space = _authorized_space(authorization)
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
    response_model_exclude_none=True,
    operation_id="get_ai_builder_plan",
    summary="Get AI Builder Plan",
    description="Fetch a stored AI Builder plan proposal for review or approval.",
    responses={
        200: {"description": "Stored AI Builder plan."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for the plan's session.",
            message="API key space scope does not match requested AI builder resource.",
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder plan not found.",
            message="AI Builder plan not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
        ),
    },
)
async def get_plan(
    request: Request,
    plan_id: Annotated[
        UUID,
        Path(description="Identifier of the stored AI Builder plan revision to fetch."),
    ],
    container: ContainerWithUserDep,
):
    service = _get_ai_builder_service(container)
    plan: BuilderPlan = await service.get_plan(plan_id)
    session: BuilderSession = await service.get_session(plan.session_id)
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_PLAN_READ,
        space_id=session.space_id,
        session=session,
        require_creator=True,
    )
    return _to_plan_response(plan)


@router.get(
    "/sessions/{session_id}/plans",
    response_model=SessionPlansResponse,
    response_model_exclude_none=True,
    operation_id="list_ai_builder_session_plans",
    summary="List Session Plans",
    description="List all plan revisions generated within a specific AI Builder session.",
    responses={
        200: {"description": "Stored plan revisions for the session."},
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for this session.",
            message="API key space scope does not match requested AI builder resource.",
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
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
    container: ContainerWithUserDep,
):
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_PLAN_LIST,
        space_id=session.space_id,
        session=session,
        require_creator=True,
    )
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
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder session not found.",
            message="AI Builder session not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
        ),
    },
)
async def cancel_session(
    request: Request,
    session_id: Annotated[
        UUID,
        Path(description="Identifier of the active AI Builder session to cancel."),
    ],
    container: ContainerWithUserDep,
):
    service = _get_ai_builder_service(container)
    session: BuilderSession = await service.get_session(session_id)
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_SESSION_CANCEL,
        space_id=session.space_id,
        session=session,
        require_creator=True,
    )
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
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder plan not found.",
            message="AI Builder plan not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
        ),
    },
)
async def approve_plan(
    request: Request,
    plan_id: Annotated[
        UUID,
        Path(description="Identifier of the AI Builder plan revision to approve."),
    ],
    container: ContainerWithUserDep,
):
    service = _get_ai_builder_service(container)
    plan: BuilderPlan = await service.get_plan(plan_id)
    session: BuilderSession = await service.get_session(plan.session_id)
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_PLAN_APPROVE,
        space_id=session.space_id,
        session=session,
    )
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
            code=AIBuilderErrorCode.TRANSCRIPTION_MODEL_REQUIRED,
        ),
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for the plan's session.",
            message="API key space scope does not match requested AI builder resource.",
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder plan not found.",
            message="AI Builder plan not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
        ),
        409: _ai_builder_error_response(
            description="The target flow revision changed before apply completed.",
            message="Flow revision changed while applying the plan.",
            code=AIBuilderErrorCode.STALE_REVISION,
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
    container: ContainerWithUserDep,
):
    service = _get_ai_builder_service(container)

    # Verify plan exists and get session for permission check
    plan: BuilderPlan = await service.get_plan(plan_id)
    session: BuilderSession = await service.get_session(plan.session_id)
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_PLAN_APPLY,
        space_id=session.space_id,
        session=session,
    )

    result: ApplyResult = await service.apply_plan(
        plan_id=plan_id,
        expected_revision=body.expected_revision,
    )

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
    "/plans/{plan_id}/create",
    response_model=ApplyResultResponse,
    operation_id="approve_and_apply_ai_builder_create_plan",
    summary="Approve And Create Flow From AI Builder Plan",
    description=(
        "Approve a create-mode plan and materialize the flow in one atomic request. "
        "The approval and the flow creation commit or roll back together. Retrying "
        "an already-applied plan returns the original result instead of failing, so "
        "a client that lost the response can recover safely. Edit-mode plans are "
        "rejected; they keep the explicit approve and apply steps."
    ),
    responses={
        200: {"description": "Flow created from the plan."},
        400: _ai_builder_error_response(
            description=(
                "The plan cannot be created in one step. Representative machine-readable "
                "codes include: invalid_session_transition (edit-mode plan), "
                "invalid_plan_status, transcription_model_required."
            ),
            message="Approve-and-create is only available for create sessions.",
            code=AIBuilderErrorCode.INVALID_SESSION_TRANSITION,
        ),
        403: _ai_builder_error_response(
            description="Caller lacks space permission or API key scope for the plan's session.",
            message="API key space scope does not match requested AI builder resource.",
            code=AIBuilderErrorCode.INSUFFICIENT_SCOPE,
            details={"auth_layer": "api_key_scope"},
        ),
        404: _ai_builder_error_response(
            description="AI Builder plan not found.",
            message="AI Builder plan not found.",
            code=AIBuilderErrorCode.NOT_FOUND,
        ),
    },
)
async def approve_and_apply_create_plan(
    request: Request,
    plan_id: Annotated[
        UUID,
        Path(
            description=(
                "Identifier of the proposed or approved create-mode AI Builder plan "
                "to approve and materialize."
            )
        ),
    ],
    container: ContainerWithUserDep,
):
    service = _get_ai_builder_service(container)

    plan: BuilderPlan = await service.get_plan(plan_id)
    session: BuilderSession = await service.get_session(plan.session_id)
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_PLAN_APPLY,
        space_id=session.space_id,
        session=session,
    )

    outcome = await service.approve_and_apply_create_plan(plan_id=plan_id)
    result = outcome.result

    # Audit — a replay returns the original outcome without side effects, so
    # it must not emit a second creation event.
    if not outcome.replayed:
        user = container.user()
        audit_service = _get_audit_service(container)
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.AI_BUILDER_FLOW_APPLIED,
            entity_type=EntityType.FLOW,
            entity_id=result.flow_id,
            description=f"Approved and created flow from AI builder plan: "
            f"{result.steps_created} steps created",
            metadata=AuditMetadata.standard(
                actor=user,
                target=SimpleNamespace(id=result.flow_id, name=result.flow_name),
                extra={
                    "plan_id": str(plan_id),
                    "combined_approve_and_apply": True,
                    "steps_created": result.steps_created,
                },
            ),
        )

    return result


@router.post(
    "/plans/{plan_id}/revise",
    response_model=PlanResponse,
    response_model_exclude_none=True,
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
            code=AIBuilderErrorCode.PLAN_NOT_PROPOSED,
        ),
        403: _ai_builder_error_response(
            description="Caller lacks permission.",
            message="Only the session creator can revise plans.",
            code=AIBuilderErrorCode.SESSION_CREATOR_REQUIRED,
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
    container: ContainerWithUserDep,
):
    service = _get_ai_builder_service(container)

    # Verify plan exists and get session for permission check
    plan: BuilderPlan = await service.get_plan(plan_id)
    session: BuilderSession = await service.get_session(plan.session_id)
    await _authorize_ai_builder_request(
        request,
        container,
        action=FlowApiAction.BUILDER_PLAN_REVISE,
        space_id=session.space_id,
        session=session,
    )

    new_plan: BuilderPlan = await service.revise_plan(
        plan_id=plan_id,
        revision_type=body.type,
    )

    return _to_plan_response(new_plan)

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.database import AsyncSession
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.api.flow_live_transcription_models import (
    LIVE_TRANSCRIPTION_SOCKET_PATH,
    FlowLiveTranscriptionModelPublic,
    FlowLiveTranscriptionSessionPublic,
    FlowLiveTranscriptionUnavailableError,
)
from eneo.flows.api.flow_runtime_paths import FLOW_LIVE_TRANSCRIPTION_SESSIONS_PATH
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import get_container_for_explicit_transaction

router = APIRouter()
__all__ = ["router"]

_DESCRIPTION = """
Admit a live transcription preview for one audio step of a published flow and
return a single-use ticket for the WebSocket at `websocket_path`.

Connect within 30 seconds, offering the subprotocols `eneo-live.v1` and
`ticket.<ticket>`. Send the recording as binary frames of mono 16-bit
little-endian PCM at 16 kHz and a text frame `{"type": "stop"}` when it ends.
The socket answers `ready`, `transcript.delta` (text to append),
`transcript.done` (the full preview text) and `error` (`code`, `message`,
`retryable`) events.

The preview is not the run's transcript. Upload the recording as a runtime file
and create the run as usual; the flow's transcription model then produces the
transcript the run uses. Live preview is only available when the flow's own
transcription model transcribes and that model supports realtime; otherwise
this route answers 409 `flow_live_transcription_unavailable` with a `reason`.
"""


@router.post(
    FLOW_LIVE_TRANSCRIPTION_SESSIONS_PATH,
    response_model=FlowLiveTranscriptionSessionPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow_live_transcription_session",
    summary="Start a live transcription preview",
    description=_DESCRIPTION,
    responses={
        400: error_response(
            description="Flow is not published, or the step does not take audio.",
            message="Live transcription needs a published step that takes audio.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.RUN_UNKNOWN_STEP_INPUT,
        ),
        403: error_response(
            description="Forbidden: the caller may not run this flow.",
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found.",
            message="Not found",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        409: {
            **error_response(
                description="Live transcription is not available for this flow.",
                message="Live transcription is not available for this flow.",
                eneo_error_code=ErrorCodes.CONFLICT,
                code=FlowApiErrorCode.LIVE_TRANSCRIPTION_UNAVAILABLE,
                context={"reason": "model_not_realtime"},
            ),
            "model": FlowLiveTranscriptionUnavailableError,
        },
    },
)
async def create_flow_live_transcription_session(
    id: Annotated[UUID, Path(description="Identifier of the published flow.")],
    step_id: Annotated[
        UUID, Path(description="Identifier of the published step that takes audio.")
    ],
    request: Request,
    container: Container = Depends(
        get_container_for_explicit_transaction(
            with_user=True, with_module_user=True, with_upload_admission=True
        )
    ),
) -> FlowLiveTranscriptionSessionPublic:
    session = cast(AsyncSession, container.session())
    async with session.begin():
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.RUN,
            allow_service_key_principals=True,
            require_published_for_service_key=True,
        )
        live = await container.flow_live_transcription_session_service().open_session(
            flow_id=id, step_id=step_id
        )
        user = container.user()
        await container.audit_service().log(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.FLOW_LIVE_TRANSCRIPTION_STARTED,
            entity_type=EntityType.FLOW,
            entity_id=id,
            description=f"Started a live transcription preview for flow {id}",
            metadata=AuditMetadata.standard(
                actor=user,
                target=live.flow,
                extra={
                    "flow_id": str(id),
                    "step_id": str(step_id),
                    "flow_version": live.flow_version,
                    "model_id": str(live.model.id),
                },
            ),
            required=True,
        )
    return FlowLiveTranscriptionSessionPublic(
        ticket=live.ticket,
        websocket_path=f"{get_settings().api_prefix}{LIVE_TRANSCRIPTION_SOCKET_PATH}",
        expires_at=live.expires_at,
        max_seconds=live.max_seconds,
        model=FlowLiveTranscriptionModelPublic(
            id=live.model.id, name=live.model.nickname or live.model.name
        ),
    )

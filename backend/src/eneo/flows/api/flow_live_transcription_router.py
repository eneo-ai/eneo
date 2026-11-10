from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.access_denial_code import AccessDenialCode
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.database.database import AsyncSession
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import error_response
from eneo.flows.api.flow_live_transcription_models import (
    LIVE_TRANSCRIPTION_SOCKET_PATH,
    FlowLiveTranscriptionModelPublic,
    FlowLiveTranscriptionSessionPublic,
    FlowLiveTranscriptionSessionRequest,
    FlowLiveTranscriptionUnavailableError,
)
from eneo.flows.api.flow_runtime_paths import FLOW_LIVE_TRANSCRIPTION_SESSIONS_PATH
from eneo.flows.flow_access_policy import FlowApiAction, flow_action_access_reason
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.server.dependencies.container import get_container_for_explicit_transaction

router = APIRouter()
__all__ = ["router"]

_DESCRIPTION = """
Admit a live transcription session for one audio step of a published flow and
return a single-use ticket for the WebSocket at `websocket_path`.

Connect within 30 seconds, offering the subprotocols `eneo-live.v1` and
`ticket.<ticket>`. Send the recording as binary frames of mono 16-bit
little-endian PCM at 16 kHz and a text frame `{"type": "stop"}` when it ends.
The socket answers `ready`, `transcript.delta` (text to append),
`transcript.done` (the session's full text) and `error` (`code`, `message`,
`retryable`) events.

The source of the audio picks the model. Streamed audio is written by the
flow's live transcription model, or by its transcription model when the flow
chose none; uploaded and recorded files are written by the transcription model.

The optional body `recording_id` is an opaque client string matching
`^[A-Za-z0-9_-]{8,64}$`. With it, Eneo stores the text of a session that heard
the whole recording and sends its `transcript_id` in `transcript.done`; `ready`
says whether it will, as `keeps_transcript`. `ready.finish_within_seconds` is
how long, from sending `stop`, the session may take to store the transcript or
give up; wait that long for `transcript.done`, then create the run without the
id. Without a `recording_id` the text is shown only, and a client need not wait
for `transcript.done` before creating the run.
To store a clean session, also send `produced_samples` in the stop message: a
non-negative integer counting captured 16 kHz samples before client queueing or
discarding. Missing or invalid counts disable storage without changing the
text. Storage also requires a successfully sent final commit and upstream
`audio_seconds` whose rounded 16 kHz sample count matches Eneo's received count
exactly. The `transcript_id` is sent only after the row commits. Storage
failures or a five-second write timeout leave the text without an id. A
recording cut into parts while it streamed also sends `part_start_samples`:
the sample count at which each part after the first began, increasing and
below `produced_samples`; the run then submits every part, in order, with
`single_recording`.

Upload the recording as a runtime file and create the run with `streamed` set
on the step, and the `transcript_id` as its `live_transcript_id` when one came:
the run uses the stored text instead of transcribing the recording again, and
the flow's speaker service only times its words and labels the speakers. When
the text cannot be used (no id, a recording that does not match it, or a live
model the flow no longer has), the flow's transcription model transcribes the
recording and the step's `live_fallback_reason` says why. Live text is only available while both of the flow's
models are available in its space and the model it streams through supports
realtime; otherwise this route answers 409
`flow_live_transcription_unavailable` with a `reason`.
The run contract's `transcription.live` reports the same availability and
reason, so a client can decide before recording whether to offer streaming.
"""


@router.post(
    FLOW_LIVE_TRANSCRIPTION_SESSIONS_PATH,
    response_model=FlowLiveTranscriptionSessionPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow_live_transcription_session",
    summary="Start a live transcription session",
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
            code=AccessDenialCode.INSUFFICIENT_SCOPE,
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found.",
            message="Not found",
            eneo_error_code=ErrorCodes.NOT_FOUND,
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
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=flow_action_access_reason(FlowApiAction.RUN),
)
async def create_flow_live_transcription_session(
    id: Annotated[UUID, Path(description="Identifier of the published flow.")],
    step_id: Annotated[
        UUID, Path(description="Identifier of the published step that takes audio.")
    ],
    request: Request,
    body: FlowLiveTranscriptionSessionRequest | None = None,
    container: Container = Depends(
        get_container_for_explicit_transaction(
            with_user=True, with_module_user=True, with_upload_admission=True
        )
    ),
) -> FlowLiveTranscriptionSessionPublic:
    session = cast(AsyncSession, container.session())
    async with session.begin():
        access = await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.RUN,
            allow_service_key_principals=True,
            require_published_for_service_key=True,
        )
        live = await container.flow_live_transcription_session_service().open_session(
            flow_id=id,
            step_id=step_id,
            space=await container.space_service().get_space(access.flow.space_id),
            recording_id=body.recording_id if body else None,
        )
        user = container.user()
        await container.audit_service().log(
            tenant_id=user.tenant_id,
            user=user,
            action=ActionType.FLOW_LIVE_TRANSCRIPTION_STARTED,
            entity_type=EntityType.FLOW,
            entity_id=id,
            description=f"Started a live transcription session for flow {id}",
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

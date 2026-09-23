"""Public contract of the live transcription session route and socket."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.runtime.live_transcription.admission import (
    LiveTranscriptionUnavailableReason,
)
from eneo.main.exceptions import ErrorCodes

LIVE_TRANSCRIPTION_SUBPROTOCOL: Final = "eneo-live.v1"
LIVE_TRANSCRIPTION_TICKET_PREFIX: Final = "ticket."
# Its own first path segment: a WebSocket cannot carry the HTTP route guards of
# /flows, so the socket accepts only tickets that the guarded POST issued.
LIVE_TRANSCRIPTION_SOCKET_PATH: Final = "/live-transcription"


class FlowLiveTranscriptionModelPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str = Field(description="Display name of the transcription model.")


class FlowLiveTranscriptionSessionPublic(BaseModel):
    """An admitted live transcription session, ready to connect."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "ticket": "Pq0cX5WnU1kz0dY8Gm7wQ2vJ4hR9sT3bA6eL1fN8xC0",
                "websocket_path": "/api/v1/live-transcription",
                "subprotocol": "eneo-live.v1",
                "expires_at": "2026-09-23T10:15:30Z",
                "sample_rate": 16000,
                "max_seconds": 18000,
                "model": {
                    "id": "7d0c7a8e-8b4c-4c1e-9d3e-2f4b6a1c9e10",
                    "name": "Pianissimo",
                },
            }
        },
    )

    ticket: str = Field(
        description=(
            "Single-use ticket for the WebSocket. Offer it as the subprotocol "
            "`ticket.<ticket>` next to `eneo-live.v1`. It expires after 30 seconds."
        )
    )
    websocket_path: str = Field(
        description="Path of the live transcription WebSocket on this API host."
    )
    subprotocol: Literal["eneo-live.v1"] = LIVE_TRANSCRIPTION_SUBPROTOCOL
    expires_at: datetime
    sample_rate: Literal[16000] = Field(
        default=16000,
        description="Send mono 16-bit little-endian PCM at this rate, as binary frames.",
    )
    max_seconds: int = Field(
        description="Longest audio the session accepts, the flow audio duration limit."
    )
    model: FlowLiveTranscriptionModelPublic


class FlowLiveTranscriptionAvailabilityPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason: LiveTranscriptionUnavailableReason | None = Field(
        default=None,
        description=(
            "Why live preview is unavailable: `transcription_disabled`, "
            "`transcription_service_mode` (an external service transcribes with its "
            "own model), `model_unavailable`, or `model_not_realtime`."
        ),
    )


class FlowLiveTranscriptionUnavailableContext(BaseModel):
    reason: LiveTranscriptionUnavailableReason = Field(
        description=(
            "`transcription_disabled`: the flow does not transcribe audio. "
            "`transcription_service_mode`: an external service transcribes with its own "
            "model. `model_unavailable`: the flow's transcription model is not available "
            "in its space. `model_not_realtime`: the model does not support realtime."
        )
    )


class FlowLiveTranscriptionUnavailableError(BaseModel):
    """409 body when live preview cannot start for the flow."""

    message: str
    eneo_error_code: ErrorCodes
    code: Literal["flow_live_transcription_unavailable"]
    context: FlowLiveTranscriptionUnavailableContext
    request_id: str | None = None
    error_id: str | None = None
    details: dict[str, Any] | None = None

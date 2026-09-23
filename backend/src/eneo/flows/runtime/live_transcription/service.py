"""Admit a live transcription session for one audio step of a published flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.flows.enums import FlowRuntimeInputFormat
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.published_runtime import (
    FlowRuntimeFlowSource,
    FlowRuntimePublicationIntent,
    FlowRuntimeSettingsSource,
    FlowRuntimeVersionSource,
    load_published_runtime_inputs,
)
from eneo.flows.runtime.live_transcription.admission import resolve_live_transcription
from eneo.flows.runtime.live_transcription.tickets import (
    LiveTranscriptionGrant,
    LiveTranscriptionTicketStore,
)
from eneo.main.config import Settings
from eneo.main.exceptions import ConflictException

if TYPE_CHECKING:
    from eneo.flows.domain.flow import Flow
    from eneo.spaces.space import Space
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )
    from eneo.users.user import UserInDB


@dataclass(frozen=True)
class LiveTranscriptionSession:
    ticket: str
    expires_at: datetime
    max_seconds: int
    flow: Flow
    flow_version: int
    model: TranscriptionModel


@dataclass(frozen=True)
class LiveTranscriptionSessionService:
    user: UserInDB
    flow_service: FlowRuntimeFlowSource
    flow_version_repo: FlowRuntimeVersionSource
    settings_service: FlowRuntimeSettingsSource
    ticket_store: LiveTranscriptionTicketStore
    settings: Settings

    async def open_session(
        self, *, flow_id: UUID, step_id: UUID, space: Space
    ) -> LiveTranscriptionSession:
        """``space`` is the flow's space the caller was authorized in."""
        runtime_inputs = await load_published_runtime_inputs(
            flow_service=self.flow_service,
            flow_version_repo=self.flow_version_repo,
            settings_source=self.settings_service,
            flow_id=flow_id,
            intent=FlowRuntimePublicationIntent.LIVE_TRANSCRIPTION,
        )
        spec = runtime_inputs.input_specs.get(step_id)
        if (
            spec is None
            or spec.runtime_input.input_format is not FlowRuntimeInputFormat.AUDIO
        ):
            raise FlowBadRequestException(
                "Live transcription needs a published step that takes audio.",
                code=FlowApiErrorCode.RUN_UNKNOWN_STEP_INPUT,
                context={"step_id": str(step_id)},
            )

        published = runtime_inputs.published
        availability = resolve_live_transcription(
            wizard_metadata=runtime_inputs.definition.metadata().wizard,
            space=space,
            step=spec.step,
            settings=self.settings,
        )
        if availability.model is None:
            raise ConflictException(
                "Live transcription is not available for this flow.",
                code=FlowApiErrorCode.LIVE_TRANSCRIPTION_UNAVAILABLE.value,
                context={"reason": availability.reason},
            )

        max_seconds = self.settings.flow_audio_max_duration_seconds
        ticket, expires_at = await self.ticket_store.issue(
            LiveTranscriptionGrant(
                tenant_id=self.user.tenant_id,
                user_id=self.user.id,
                flow_id=published.flow_id,
                flow_version=published.published_version,
                step_id=step_id,
                model_id=availability.model.id,
                max_seconds=max_seconds,
            )
        )
        return LiveTranscriptionSession(
            ticket=ticket,
            expires_at=expires_at,
            max_seconds=max_seconds,
            flow=published.flow,
            flow_version=published.published_version,
            model=availability.model,
        )

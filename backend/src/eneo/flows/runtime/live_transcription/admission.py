"""Whether a published flow can show a live transcript preview, and with which model.

One owner for two readers: the run contract advertises availability and the
live-session route admits a session, so both ask this module and cannot
disagree. The preview uses exactly the flow's own transcription model; when
another engine would produce the final transcript (an external service in
``full`` mode ignores the flow's model), live preview is refused instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.runtime.transcription import resolve_transcription_model_for_step
from eneo.flows.transcription_config import (
    FlowTranscriptionConfigError,
    parse_transcription_config,
)
from eneo.main.exceptions import TypedIOValidationException
from eneo.transcription_models.domain.realtime import speaks_realtime_dialect

if TYPE_CHECKING:
    from eneo.flows.domain.runtime import RuntimeStep
    from eneo.main.config import Settings
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

LiveTranscriptionUnavailableReason = Literal[
    "transcription_disabled",
    "transcription_service_mode",
    "model_unavailable",
    "model_not_realtime",
]


@dataclass(frozen=True)
class LiveTranscriptionAvailability:
    model: TranscriptionModel | None
    reason: LiveTranscriptionUnavailableReason | None

    @property
    def available(self) -> bool:
        return self.model is not None


def _unavailable(
    reason: LiveTranscriptionUnavailableReason,
) -> LiveTranscriptionAvailability:
    return LiveTranscriptionAvailability(model=None, reason=reason)


async def resolve_live_transcription(
    *,
    wizard_metadata: FlowPersistedJsonObject | None,
    space_repo: SpaceRepository,
    step: RuntimeStep,
    settings: Settings,
) -> LiveTranscriptionAvailability:
    """Resolve the model a live session on ``step`` would stream to.

    The model is found exactly as the run's transcription finds it, through the
    step's assistant.
    """
    try:
        config = parse_transcription_config({"wizard": wizard_metadata})
    except FlowTranscriptionConfigError:
        return _unavailable("transcription_disabled")
    if not config.enabled:
        return _unavailable("transcription_disabled")
    if (
        settings.flow_transcription_service_configured
        and settings.flow_transcription_service_mode == "full"
    ):
        return _unavailable("transcription_service_mode")
    try:
        model = await resolve_transcription_model_for_step(
            space_repo=space_repo,
            assistant_id=step.assistant_id,
            config=config,
            step_order=step.step_order,
        )
    except TypedIOValidationException:
        return _unavailable("model_unavailable")
    if not (model.supports_realtime and speaks_realtime_dialect(model.provider_type)):
        return _unavailable("model_not_realtime")
    return LiveTranscriptionAvailability(model=model, reason=None)

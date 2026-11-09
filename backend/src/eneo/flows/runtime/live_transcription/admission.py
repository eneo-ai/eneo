"""Whether a published flow can show a live transcript preview, and with which model.

One owner for two readers: the run contract advertises availability and the
live-session route admits a session, so both ask this module and cannot
disagree. The flow's transcription model writes every run's transcript,
however the recording arrived. The preview streams through the flow's live
model, or through the transcription model when the flow chose none. Its text
can stand in for the run's transcription only when the transcription model
itself streamed it; a speaker service only adds labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.runtime.transcription import select_transcription_model
from eneo.flows.transcription_config import (
    FlowTranscriptionConfigError,
    parse_transcription_config,
    usable_transcription_model,
)
from eneo.main.exceptions import TypedIOValidationException
from eneo.transcription_models.domain.realtime import streams_live

if TYPE_CHECKING:
    from eneo.flows.domain.runtime import RuntimeStep
    from eneo.spaces.space import Space
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

LiveTranscriptionUnavailableReason = Literal[
    "transcription_disabled",
    "model_unavailable",
    "live_model_unavailable",
    "model_not_realtime",
]


@dataclass(frozen=True)
class LiveTranscriptionAvailability:
    # The model the preview streams through.
    model: TranscriptionModel | None
    reason: LiveTranscriptionUnavailableReason | None
    # Whether a session's text may become the run's transcript: only when the
    # preview streams through the flow's transcription model.
    keeps_transcript: bool = False

    @property
    def available(self) -> bool:
        return self.model is not None


def _unavailable(
    reason: LiveTranscriptionUnavailableReason,
) -> LiveTranscriptionAvailability:
    return LiveTranscriptionAvailability(model=None, reason=reason)


def resolve_live_transcription(
    *,
    wizard_metadata: FlowPersistedJsonObject | None,
    space: Space,
    step: RuntimeStep,
) -> LiveTranscriptionAvailability:
    """Resolve the model a live session on ``step`` would stream to.

    ``space`` is the flow's space the caller was authorized in, which is also
    the step's space; models are picked from it exactly as the run's
    transcription picks them, without loading the space's applications again.
    A preview is offered only while the run could transcribe the recording.
    """
    try:
        config = parse_transcription_config({"wizard": wizard_metadata})
    except FlowTranscriptionConfigError:
        return _unavailable("transcription_disabled")
    if not config.enabled:
        return _unavailable("transcription_disabled")
    try:
        transcription_model = select_transcription_model(
            space, config=config, step_order=step.step_order
        )
    except TypedIOValidationException:
        return _unavailable("model_unavailable")
    model = transcription_model
    if config.live_model_id is not None:
        live_model = usable_transcription_model(space, config.live_model_id)
        if live_model is None:
            return _unavailable("live_model_unavailable")
        model = live_model
    if not streams_live(model):
        return _unavailable("model_not_realtime")
    return LiveTranscriptionAvailability(
        model=model,
        reason=None,
        keeps_transcript=model.id == transcription_model.id,
    )

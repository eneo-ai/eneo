"""Whether a published flow can stream live text, and through which model.

One owner for two readers: the run contract advertises availability and the
live-session route admits a session, so both ask this module and cannot
disagree. The source of the audio picks the model: streamed audio is written
by the flow's live model, or by the transcription model when the flow chose
none, and the text of a session that heard the whole recording is the run's
transcript. Uploaded and recorded files are written by the transcription
model, which also transcribes a streamed recording whose live text cannot be
used. A speaker service only times the words and labels the speakers.
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
    # The model the live text streams through.
    model: TranscriptionModel | None
    reason: LiveTranscriptionUnavailableReason | None

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
    Live text is offered only while the run could also transcribe the
    recording, which it does when the live text cannot be used.
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
    return LiveTranscriptionAvailability(model=model, reason=None)

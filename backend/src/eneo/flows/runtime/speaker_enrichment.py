"""Speaker enrichment shared by batch and live flow transcripts."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.files.transcriber import TranscribedAudio
from eneo.flows.runtime.audio_spool import SpooledAudio
from eneo.flows.runtime.run_cancellation import FlowStepCancelledError
from eneo.main.exceptions import TypedIOValidationException
from eneo.main.logging import get_logger
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserverError,
)

if TYPE_CHECKING:
    from eneo.flows.runtime.remote_transcription import RemoteFlowTranscriber
    from eneo.model_providers.domain.provider_call_observer import ProviderCallObserver
    from eneo.transcription_models.domain.transcription_model import TranscriptionModel

logger = get_logger(__name__)
DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT = "skipped:empty_transcript"


class SpeakerServiceFailed(Exception):
    """The speaker identification service failed after the model wrote the
    text; the cause is chained. The step reports it as the speaker service's
    failure, not the transcription's."""


async def enrich_transcript(
    remote: RemoteFlowTranscriber,
    file: SpooledAudio,
    transcription_model: TranscriptionModel,
    *,
    transcribed: TranscribedAudio,
    file_id: UUID,
    language: str | None = None,
    observer: ProviderCallObserver | None = None,
    max_speakers: int | None = None,
) -> TranscribedAudio:
    if not transcribed.segments:
        # Every chunk decoded to nothing; there is no text to label.
        logger.warning(
            "flow_transcription.diarization_skipped model=%s reason=empty_transcript",
            transcription_model.model_name,
        )
        return replace(transcribed, diarization=DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT)

    started = time.monotonic()
    try:
        labelled = await remote.label_speakers(
            file,
            file_id=file_id,
            words=None,
            segments=transcribed.segments,
            model_name=transcription_model.model_name,
            language=language,
            observer=observer,
            max_speakers=max_speakers,
        )
    except (
        TypedIOValidationException,
        ProviderCallObserverError,
        FlowStepCancelledError,
    ):
        # Refusals, deadlines, cancellation and evidence gaps already say
        # what happened.
        raise
    except Exception as exc:
        raise SpeakerServiceFailed() from exc
    return TranscribedAudio(
        text=labelled.text,
        duration_seconds=transcribed.duration_seconds,
        segments=transcribed.segments,
        transcript_segments=labelled.segments,
        diarization="external",
        diarization_elapsed_ms=int((time.monotonic() - started) * 1000),
        alignment=labelled.alignment,
        speaker_review=labelled.speaker_review,
        empty_intervals=transcribed.empty_intervals,
    )

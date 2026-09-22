"""Flow-step transcriber that transcribes in Eneo and labels speakers externally.

The flow's own transcription model (registry, per-tenant provider credentials,
governance) produces the transcript; the external transcription service is
asked only to diarize the audio and attach speaker labels to it.

The service receives the transcript as one segment per audio chunk, spanning
the chunk's measured duration. Those windows are the only timestamps Eneo can
vouch for: they come from the audio it split and measured itself, not from the
provider, whose word timings have proven unreliable. The service force-aligns
the text inside each window and, if it cannot, falls back to labelling whole
segments, so the text order is never disturbed.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID

from eneo.files.transcriber import TranscribedAudio, Transcriber
from eneo.flows.runtime.audio_spool import SpooledAudio
from eneo.flows.runtime.remote_transcription import RemoteFlowTranscriber
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.model_providers.domain.provider_call_observer import (
        ProviderCallObserver,
    )
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

logger = get_logger(__name__)

DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT = "skipped:empty_transcript"


class RegistryFlowTranscriber:
    """Use the registry engine on an admitted flow spool without a shared cache."""

    def __init__(self, transcriber: Transcriber) -> None:
        self.transcriber = transcriber

    async def transcribe(
        self,
        file: SpooledAudio,
        transcription_model: TranscriptionModel,
        *,
        file_id: UUID,
        language: str | None = None,
        diarize: bool = True,
        persist_cache_to_file: bool = True,
        observer: ProviderCallObserver | None = None,
        max_speakers: int | None = None,
    ) -> TranscribedAudio:
        transcribed = await self.transcriber.transcribe_from_filepath(
            filepath=file.path,
            transcription_model=transcription_model,
            language=language,
            observer=observer,
        )
        if transcribed.duration_seconds is not None:
            file.cache_duration(transcribed.duration_seconds)
        return transcribed


class DiarizingFlowTranscriber(RegistryFlowTranscriber):
    """``FlowStepTranscriber`` composed of the registry engine and the service."""

    def __init__(self, transcriber: Transcriber, remote: RemoteFlowTranscriber) -> None:
        super().__init__(transcriber)
        self.remote = remote

    async def transcribe(
        self,
        file: SpooledAudio,
        transcription_model: TranscriptionModel,
        *,
        file_id: UUID,
        language: str | None = None,
        diarize: bool = True,
        persist_cache_to_file: bool = True,
        observer: ProviderCallObserver | None = None,
        max_speakers: int | None = None,
    ) -> TranscribedAudio:
        del persist_cache_to_file
        transcribed = await super().transcribe(
            file,
            transcription_model,
            file_id=file_id,
            language=language,
            # Flow transcripts never touch the File's shared transcription cache.
            persist_cache_to_file=False,
            observer=observer,
        )
        if not diarize:
            return transcribed
        if not transcribed.segments:
            # Every chunk decoded to nothing; there is no text to label.
            logger.warning(
                "flow_transcription.diarization_skipped model=%s reason=empty_transcript",
                transcription_model.model_name,
            )
            return replace(
                transcribed, diarization=DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT
            )

        started = time.monotonic()
        labelled = await self.remote.label_speakers(
            file,
            file_id=file_id,
            words=None,
            segments=transcribed.segments,
            model_name=transcription_model.model_name,
            language=language,
            observer=observer,
            max_speakers=max_speakers,
        )
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

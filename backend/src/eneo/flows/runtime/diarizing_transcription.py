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

from eneo.files.transcriber import TranscribedAudio, Transcriber
from eneo.flows.runtime.remote_transcription import RemoteFlowTranscriber
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.files.file_models import File
    from eneo.model_providers.domain.provider_call_observer import (
        ProviderCallObserver,
    )
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

logger = get_logger(__name__)

DIARIZATION_SKIPPED_EMPTY_TRANSCRIPT = "skipped:empty_transcript"


class DiarizingFlowTranscriber:
    """``FlowStepTranscriber`` composed of the registry engine and the service."""

    def __init__(self, transcriber: Transcriber, remote: RemoteFlowTranscriber) -> None:
        self.transcriber = transcriber
        self.remote = remote

    async def transcribe(
        self,
        file: File,
        transcription_model: TranscriptionModel,
        *,
        language: str | None = None,
        diarize: bool = True,
        persist_cache_to_file: bool = True,
        observer: ProviderCallObserver | None = None,
        max_speakers: int | None = None,
    ) -> TranscribedAudio:
        del persist_cache_to_file
        transcribed = await self.transcriber.transcribe(
            file,
            transcription_model,
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
        )

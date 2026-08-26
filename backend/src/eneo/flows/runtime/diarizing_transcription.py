"""Flow-step transcriber that transcribes in Eneo and labels speakers externally.

The flow's own transcription model (registry, per-tenant provider credentials,
governance) produces the transcript with word timestamps; the external
transcription service is asked only to diarize the audio and attach speaker
labels to those words. When the model cannot deliver word timestamps the
transcript is returned unlabelled and the step reports that it skipped speaker
identification rather than failing.
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

DIARIZATION_SKIPPED_NO_WORD_TIMESTAMPS = "skipped:no_word_timestamps"


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
            want_words=diarize,
        )
        if not diarize:
            return transcribed
        if not transcribed.words and not transcribed.segments:
            logger.warning(
                "flow_transcription.diarization_skipped model=%s reason=no_timestamps",
                transcription_model.model_name,
            )
            return replace(
                transcribed, diarization=DIARIZATION_SKIPPED_NO_WORD_TIMESTAMPS
            )
        if not transcribed.words:
            # Segment-level labelling: a speaker change inside one segment is
            # lost, but the transcript still gets speakers.
            logger.info(
                "flow_transcription.diarization_segments_only model=%s",
                transcription_model.model_name,
            )

        started = time.monotonic()
        labelled = await self.remote.label_speakers(
            file,
            words=transcribed.words,
            segments=transcribed.segments,
            model_name=transcription_model.model_name,
            language=language,
            observer=observer,
            max_speakers=max_speakers,
        )
        return TranscribedAudio(
            text=labelled.text,
            duration_seconds=transcribed.duration_seconds,
            words=transcribed.words,
            segments=transcribed.segments,
            diarization="external",
            diarization_elapsed_ms=int((time.monotonic() - started) * 1000),
            alignment=labelled.alignment,
        )

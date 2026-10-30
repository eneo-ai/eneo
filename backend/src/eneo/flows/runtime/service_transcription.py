"""Flow-step transcribers: the flow's model alone, or the model and the
transcription service the flow chose.

The flow's own transcription model (registry, per-tenant provider credentials,
governance) produces the transcript; the external transcription service never
writes text. It labels the speakers when the run asks for labels, and
otherwise places the words in time.

The service receives the transcript as one segment per audio chunk, spanning
the chunk's measured duration. Those windows are the only timestamps Eneo can
vouch for: they come from the audio it split and measured itself, not from the
provider, whose word timings have proven unreliable. The service force-aligns
the text inside each window. A diarize job that cannot falls back to labelling
whole segments, so the text order is never disturbed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from eneo.files.transcriber import TranscribedAudio, Transcriber
from eneo.flows.runtime.audio_spool import SpooledAudio
from eneo.flows.runtime.recording_parts import RecordingAudio, join_part_windows
from eneo.flows.runtime.remote_transcription import RemoteFlowTranscriber
from eneo.flows.runtime.service_enrichment import enrich_transcript

if TYPE_CHECKING:
    from eneo.model_providers.domain.provider_call_observer import (
        ProviderCallObserver,
    )
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )


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
            limits=file.limits,
        )
        if transcribed.duration_seconds is not None:
            file.cache_duration(transcribed.duration_seconds)
        return transcribed

    async def enrich(
        self,
        file: SpooledAudio,
        transcription_model: TranscriptionModel,
        *,
        transcribed: TranscribedAudio,
        file_id: UUID,
        diarize: bool,
        language: str | None = None,
        observer: ProviderCallObserver | None = None,
        max_speakers: int | None = None,
    ) -> TranscribedAudio:
        return transcribed


class ServiceFlowTranscriber(RegistryFlowTranscriber):
    """``FlowStepTranscriber`` composed of the registry engine and the flow's
    transcription service: the service labels the speakers of a run that asks
    for labels, and times the words of any other."""

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
        return await self.enrich(
            file,
            transcription_model,
            transcribed=transcribed,
            file_id=file_id,
            diarize=diarize,
            language=language,
            observer=observer,
            max_speakers=max_speakers,
        )

    async def enrich(
        self,
        file: SpooledAudio,
        transcription_model: TranscriptionModel,
        *,
        transcribed: TranscribedAudio,
        file_id: UUID,
        diarize: bool,
        language: str | None = None,
        observer: ProviderCallObserver | None = None,
        max_speakers: int | None = None,
    ) -> TranscribedAudio:
        return await enrich_transcript(
            self.remote,
            file,
            transcription_model,
            transcribed=transcribed,
            file_id=file_id,
            diarize=diarize,
            language=language,
            observer=observer,
            max_speakers=max_speakers,
        )

    async def transcribe_recording(
        self,
        recording: RecordingAudio,
        transcription_model: TranscriptionModel,
        *,
        language: str | None,
        observer: ProviderCallObserver | None,
        max_speakers: int | None,
    ) -> TranscribedAudio:
        """Each part transcribed on its own, the speakers labelled once on the
        joined audio so one voice keeps one label across the parts."""
        parts = [
            await RegistryFlowTranscriber.transcribe(
                self,
                part,
                transcription_model,
                file_id=file_id,
                language=language,
                persist_cache_to_file=False,
                observer=observer,
            )
            for part, file_id in zip(recording.parts, recording.file_ids, strict=True)
        ]
        return await self.enrich(
            recording.joined,
            transcription_model,
            transcribed=join_part_windows(parts, recording.bounds),
            file_id=recording.file_ids[0],
            diarize=True,
            language=language,
            observer=observer,
            max_speakers=max_speakers,
        )

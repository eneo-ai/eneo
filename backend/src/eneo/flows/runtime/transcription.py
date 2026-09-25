from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

from eneo.completion_models.infrastructure.context_builder import count_tokens
from eneo.files.audio import AudioDecodeLimitExceeded, AudioMimeTypes
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.domain.speaker_labels import (
    build_label_renumbering,
    build_speaker_inventory,
    render_segments,
    renumber_segment_speakers,
    renumber_speaker_labels,
)
from eneo.flows.domain.transcript_corrections import (
    SegmentsContentHash,
)
from eneo.flows.domain.transcript_source import (
    TranscriptSource,
    TranscriptSourceBounds,
    TranscriptSourceOmissionReason,
)
from eneo.flows.enums import FlowStepPhase
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import (
    TRANSCRIPTION_SERVICE_REASON_MAX_LENGTH,
    FlowRunErrorDetails,
    TranscriptionFailureKind,
)
from eneo.flows.runtime.audio_spool import OpenAudioDownload, SpooledAudio, spool_audio
from eneo.flows.runtime.run_cancellation import FlowStepCancelledError
from eneo.flows.runtime.step_deadline import current_step_deadline_scope
from eneo.flows.transcription_config import (
    FlowTranscriptionConfig,
    FlowTranscriptionConfigError,
    parse_transcription_config,
    to_provider_language,
)
from eneo.main.exceptions import (
    NotFoundException,
    OpenAIException,
    ProviderRejectedRequestException,
    TypedIOValidationException,
)
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserverError,
)
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    EmptyTranscriptionInterval,
    TranscriptSegment,
)


class TranscriptionProviderError(OpenAIException):
    def __init__(
        self,
        message: str,
        *,
        failure_kind: TranscriptionFailureKind = TranscriptionFailureKind.PROVIDER,
        service_reason: str | None = None,
        code: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message, code=code, details=details)
        self.failure_kind = failure_kind
        self.service_reason = (
            service_reason[:TRANSCRIPTION_SERVICE_REASON_MAX_LENGTH]
            if service_reason
            else None
        )


class TranscriptionProviderRejectedError(
    TranscriptionProviderError, ProviderRejectedRequestException
):
    pass


class TranscriptionFailure(TypedIOValidationException):
    def __init__(self, message: str, *, cause: Exception) -> None:
        super().__init__(
            message, code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED.value
        )
        service_reason = None
        if isinstance(cause, TranscriptionProviderError):
            kind = cause.failure_kind
            service_reason = cause.service_reason
        elif isinstance(cause, ProviderRejectedRequestException):
            kind = TranscriptionFailureKind.INPUT
        elif isinstance(cause, OpenAIException):
            kind = (
                TranscriptionFailureKind.CAPACITY
                if cause.code == "provider_rate_limited"
                else TranscriptionFailureKind.PROVIDER
            )
        else:
            kind = TranscriptionFailureKind.INTERNAL
        scope = current_step_deadline_scope()
        self.run_error_details = FlowRunErrorDetails(
            phase=FlowStepPhase.TRANSCRIPTION,
            transcription_failure_kind=kind,
            transcription_service_reason=service_reason,
            transcription_stage=scope.transcription_stage
            if scope is not None
            else None,
            transcription_queue_position=scope.transcription_queue_position
            if scope is not None
            else None,
        )


class FlowStepTranscriber(Protocol):
    """What a flow audio step needs from a transcription engine.

    Satisfied by ``RegistryFlowTranscriber`` (model-registry LiteLLM path) and
    ``RemoteFlowTranscriber`` (external transcription service).
    """

    async def transcribe(
        self,
        file: SpooledAudio,
        transcription_model: "TranscriptionModel",
        *,
        file_id: UUID,
        language: str | None = None,
        diarize: bool = True,
        persist_cache_to_file: bool = True,
        observer: "ProviderCallObserver | None" = None,
        max_speakers: int | None = None,
    ) -> "TranscribedAudio": ...

    async def enrich(
        self,
        file: SpooledAudio,
        transcription_model: "TranscriptionModel",
        *,
        transcribed: TranscribedAudio,
        file_id: UUID,
        language: str | None = None,
        observer: "ProviderCallObserver | None" = None,
        max_speakers: int | None = None,
    ) -> TranscribedAudio: ...


# Must stay aligned with
# frontend/apps/web/src/lib/features/audio/recordingSession.ts::buildSegmentFilenameBase.
# Other uploads fall back to the unlabeled transcript join.
_SEGMENT_FILENAME_RE = re.compile(
    r"^recording-(?P<session>[0-9a-fA-F-]+)-seg(?P<index>\d{2,4})-"
    r"(?P<iso>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d+)?Z)\.[A-Za-z0-9]+$"
)


def _parse_segment_iso(token: str) -> datetime | None:
    # The filename ISO is `YYYY-MM-DDTHH-MM-SS-mmmZ` because the recorder
    # replaces ':' and '.' with '-' to keep the value filesystem-safe.
    # Reconstruct the canonical ISO so datetime.fromisoformat can read it.
    if "T" not in token or not token.endswith("Z"):
        return None
    body = token[:-1]
    date_part, _, time_part = body.partition("T")
    if not date_part or not time_part:
        return None
    parts = time_part.split("-")
    if len(parts) < 3:
        return None
    hh, mm, ss, *rest = parts
    if len(rest) > 1 or any(not part.isdigit() for part in rest):
        return None
    canonical = f"{date_part}T{hh}:{mm}:{ss}"
    if rest:
        canonical += "." + "".join(rest)
    canonical += "+00:00"
    try:
        return datetime.fromisoformat(canonical)
    except ValueError:
        return None


def _parse_segment_filename(name: str) -> tuple[str, int, datetime] | None:
    match = _SEGMENT_FILENAME_RE.match(name or "")
    if not match:
        return None
    try:
        index = int(match.group("index"))
    except ValueError:
        return None
    parsed = _parse_segment_iso(match.group("iso"))
    if parsed is None:
        return None
    return match.group("session"), index, parsed


def _join_transcription_blocks(
    text_blocks: list[str],
    block_segments: list[tuple[str, int, datetime] | None],
) -> str:
    # Per-segment headers help the LLM (and human readers of the audit
    # trail) reason about a long recording that was paused — without them
    # the join produced one undifferentiated wall of text. We only label
    # when every block belongs to the same recording session and there is
    # more than one block, otherwise a single-shot upload would get an
    # unnecessary "## Del 1" header.
    if len(text_blocks) < 2:
        return "\n\n".join(text_blocks).strip()

    if any(meta is None for meta in block_segments):
        return "\n\n".join(text_blocks).strip()

    session_ids = {meta[0] for meta in block_segments if meta is not None}
    if len(session_ids) != 1:
        return "\n\n".join(text_blocks).strip()

    labelled: list[str] = []
    for block_text, meta in zip(text_blocks, block_segments):
        if meta is None:
            labelled.append(block_text)
            continue
        _, index, captured_at = meta
        time_str = captured_at.strftime("%H:%M:%S")
        labelled.append(f"## Del {index + 1} — kl {time_str}\n\n{block_text}")
    return "\n\n".join(labelled).strip()


if TYPE_CHECKING:
    from eneo.database.tables.flow_tables import FlowLiveTranscripts
    from eneo.files.file_models import FileInfo
    from eneo.model_providers.domain.provider_call_observer import (
        ProviderCallObserver,
    )
    from eneo.spaces.space import Space
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )


def _empty_speakers() -> list[dict[str, Any]]:
    return []


# A five-hour diarized transcript is about 0.5 MB before review detail.
MAX_SEGMENTS_BYTES = 2 * 1024 * 1024
MAX_DETAIL_BYTES = MAX_SEGMENTS_BYTES
# Word timings live in their own row (see ``FlowStepTranscriptWords``) and
# anchor to the stored segments by index, so they exist only when the
# segments do. An hour of speech is a few megabytes of words.
MAX_WORDS_BYTES = 8 * 1024 * 1024

LiveFallbackReason = Literal["duration_mismatch", "no_timing", "unavailable"]


def serialize_segments(
    segments: Sequence["TranscriptSegment"],
    *,
    file_index: int,
    file_id: str | None = None,
) -> list[dict[str, Any]]:
    """Structured transcript lines for one file, timestamps relative to that
    file's audio (a multi-file transcript restarts at zero per file)."""
    return [
        {
            "file_index": file_index,
            "start": segment.start,
            "end": segment.end,
            "speaker": segment.speaker,
            "text": segment.text,
            **(
                {
                    "speaker_attribution": segment.speaker_attribution,
                    "overlap_ids": [
                        f"{file_id}:{value}" if file_id else value
                        for value in segment.overlap_ids
                    ],
                }
                if segment.speaker_attribution is not None or segment.overlap_ids
                else {}
            ),
        }
        for segment in segments
    ]


def serialize_segment_words(
    segments: Sequence["TranscriptSegment"],
    *,
    first_segment_index: int,
    file_id: str | None = None,
) -> list[dict[str, Any]]:
    """Word timings for one file's segments, keyed by the index each segment
    gets in the stored array (``first_segment_index`` + position). Segments
    the service returned without words are skipped."""
    entries: list[dict[str, Any]] = []
    for position, segment in enumerate(segments):
        if not segment.words:
            continue
        entries.append(
            {
                "segment_index": first_segment_index + position,
                **(
                    {
                        "speaker_attribution": segment.speaker_attribution,
                        "overlap_ids": [
                            f"{file_id}:{value}" if file_id else value
                            for value in segment.overlap_ids
                        ],
                    }
                    if segment.speaker_attribution is not None or segment.overlap_ids
                    else {}
                ),
                "words": [
                    {
                        "word": word.word,
                        "start": word.start,
                        "end": word.end,
                        "probability": word.probability,
                    }
                    for word in segment.words
                ],
            }
        )
    return entries


class TranscriptSourcePreparation:
    """Bounded transcript evidence accumulated across one attempt."""

    def __init__(
        self,
        *,
        files_count: int = 0,
        segments: Sequence[dict[str, Any]] = (),
        speaker_review: dict[str, Any] | None = None,
        words: Sequence[dict[str, Any]] = (),
        words_omitted_reason: str | None = None,
    ) -> None:
        self.files_count = 0
        self.speakers_count = 0
        self.alignment: str | None = None
        self._segments: list[dict[str, Any]] | None = []
        self._words: list[dict[str, Any]] | None = []
        self._review_files: list[dict[str, Any]] | None = []
        self._segments_complete = True
        self._segments_count = 0
        self._segments_bytes = 0
        self._detail_count = 0
        self._detail_bytes = 0
        self._words_count = 0
        self._words_bytes = 0
        self._words_omitted_reason: TranscriptSourceOmissionReason | None = None
        self._hash = SegmentsContentHash()
        if files_count:
            self.append(
                files_count=files_count,
                segments=segments,
                speaker_review=speaker_review,
                words=words,
                words_omitted_reason=words_omitted_reason,
            )

    def append(
        self,
        *,
        files_count: int,
        segments: Sequence[dict[str, Any]],
        speaker_review: dict[str, Any] | None,
        words: Sequence[dict[str, Any]],
        words_omitted_reason: str | None,
        speakers_count: int = 0,
        alignment: str | None = None,
    ) -> None:
        self.alignment = _coarsest_alignment(
            [value for value in (self.alignment, alignment) if value is not None]
        )
        segment_offset = self._segments_count
        # Default JSON brackets/separators contribute two bytes per array item.
        for segment in segments:
            if self.files_count:
                segment = {
                    **segment,
                    "file_index": segment["file_index"] + self.files_count,
                }
            self._hash.append(segment)
            self._segments_count += 1
            self._segments_bytes += (
                len(json.dumps(segment, ensure_ascii=False).encode("utf-8")) + 2
            )
            if self._segments_bytes > MAX_SEGMENTS_BYTES:
                self._segments = None
            elif self._segments is not None:
                self._segments.append(segment)
        if not segments:
            self._segments_complete = False
            self._segments = None
        if speaker_review is not None:
            if not self._detail_bytes:
                self._detail_bytes = len(json.dumps({"files": []}).encode("utf-8"))
            if self._detail_bytes > MAX_DETAIL_BYTES:
                self._review_files = None
            for review in speaker_review.get("files", []):
                if self.files_count:
                    review = {
                        **review,
                        "file_index": review["file_index"] + self.files_count,
                    }
                self._detail_bytes += len(
                    json.dumps(review, ensure_ascii=False).encode("utf-8")
                )
                if self._detail_count:
                    self._detail_bytes += 2
                self._detail_count += 1
                if self._detail_bytes > MAX_DETAIL_BYTES:
                    self._review_files = None
                elif self._review_files is not None:
                    self._review_files.append(review)
        for entry in words:
            entry = {**entry, "segment_index": entry["segment_index"] + segment_offset}
            self._words_count += len(entry["words"])
            self._words_bytes += (
                len(json.dumps(entry, ensure_ascii=False).encode("utf-8")) + 2
            )
            if self._words_bytes > MAX_WORDS_BYTES:
                self._words = None
                self._words_omitted_reason = TranscriptSourceOmissionReason.TOO_LARGE
            elif self._words is not None:
                self._words.append(entry)
        self.files_count += files_count
        self.speakers_count += speakers_count
        if words_omitted_reason is not None:
            self._words = None
            self._words_omitted_reason = TranscriptSourceOmissionReason[
                words_omitted_reason.upper()
            ]

    @property
    def source_hash(self) -> str | None:
        return (
            self._hash.hexdigest()
            if self._segments_complete and self._segments_count
            else None
        )

    @property
    def bounds(self) -> TranscriptSourceBounds:
        return TranscriptSourceBounds(
            segments_bytes=self._segments_bytes,
            detail_bytes=self._detail_bytes,
            words_bytes=self._words_bytes,
            segments_count=self._segments_count,
            words_count=self._words_count,
            segments_omitted_reason=(
                TranscriptSourceOmissionReason.NO_SEGMENTS
                if not self._segments_complete or not self._segments_count
                else TranscriptSourceOmissionReason.TOO_LARGE
                if self._segments is None
                else None
            ),
            detail_omitted_reason=(
                TranscriptSourceOmissionReason.TOO_LARGE
                if self._review_files is None
                else None
            ),
            words_omitted_reason=(
                TranscriptSourceOmissionReason.SEGMENTS_UNAVAILABLE
                if self._words_count and not self._segments
                else self._words_omitted_reason
            ),
        )

    @property
    def words(self) -> list[dict[str, Any]] | None:
        if self.bounds.words_omitted_reason is not None:
            return None
        return self._words or None

    @property
    def source(self) -> TranscriptSource:
        return TranscriptSource(
            segments=self._segments or None,
            speaker_review={"files": self._review_files}
            if self._detail_bytes and self._review_files is not None
            else None,
            source_hash=self.source_hash,
            bounds=self.bounds,
        )


@dataclass(frozen=True)
class FlowTranscriptionResult:
    text: str
    file_ids: list[UUID]
    model_id: UUID | None
    model_name: str
    language: str
    transcript_bytes: int
    estimated_tokens: int
    audio_seconds: float | None
    elapsed_ms: int
    files_count: int
    near_inline_limit: bool
    source_preparation: TranscriptSourcePreparation
    # None: no speaker labels requested. "external": labelled by the external
    # service. "skipped:<reason>": requested but not produced.
    diarization: str | None = None
    # Time spent in the external speaker-labelling calls, when any were made.
    diarization_elapsed_ms: int | None = None
    # Labelled speakers across all files, after renumbering to unique labels.
    speakers: list[dict[str, Any]] = field(default_factory=_empty_speakers)
    # Upper bound given to diarization, from the participants form field.
    max_speakers: int | None = None
    # Coarsest word-timestamp source across files, as reported by the service.
    alignment: str | None = None
    empty_intervals: tuple[EmptyTranscriptionInterval, ...] = ()
    transcript_origin: Literal["live", "batch"] = "batch"
    live_fallback_reason: LiveFallbackReason | None = None

    @property
    def source(self) -> TranscriptSource:
        return self.source_preparation.source

    def to_metadata(self) -> dict[str, Any]:
        return {
            "transcript_bytes": self.transcript_bytes,
            "estimated_tokens": self.estimated_tokens,
            # Decoded source length for this step's successful transcription.
            # A transcription step consumes no tokens, so without this its
            # runtime evidence says nothing about what it actually read.
            "audio_seconds": self.audio_seconds,
            "elapsed_ms": self.elapsed_ms,
            "files_count": self.files_count,
            "model": self.model_name,
            "model_id": str(self.model_id) if self.model_id is not None else None,
            "language": self.language,
            "file_ids": [str(file_id) for file_id in self.file_ids],
            "diarization": self.diarization,
            "diarization_elapsed_ms": self.diarization_elapsed_ms,
            "speakers": self.speakers,
            "max_speakers": self.max_speakers,
            "alignment": self.alignment,
            "transcript_origin": self.transcript_origin,
            **(
                {"live_fallback_reason": self.live_fallback_reason}
                if self.live_fallback_reason is not None
                else {}
            ),
        }


def order_files_by_request(
    files: list["FileInfo"],
    requested_ids: list[UUID],
) -> list["FileInfo"]:
    by_id = {item.id: item for item in files}
    ordered: list["FileInfo"] = []
    seen: set[UUID] = set()
    for file_id in requested_ids:
        if file_id in seen:
            continue
        match = by_id.get(file_id)
        if match is None:
            continue
        ordered.append(match)
        seen.add(file_id)
    return ordered


async def resolve_transcription_model_for_step(
    *,
    space_repo: "SpaceRepository",
    assistant_id: UUID,
    config: FlowTranscriptionConfig,
    step_order: int,
) -> "TranscriptionModel":
    space = await space_repo.get_space_by_assistant(assistant_id=assistant_id)
    return select_transcription_model(space, config=config, step_order=step_order)


def select_transcription_model(
    space: "Space",
    *,
    config: FlowTranscriptionConfig,
    step_order: int,
) -> "TranscriptionModel":
    """The flow's transcription model, when the step's space may use it."""
    available_models = list(getattr(space, "transcription_models", []) or [])

    if config.model_id is None:
        raise TypedIOValidationException(
            (
                f"Step {step_order}: a transcription model must be configured "
                "for audio input."
            ),
            code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_MODEL_MISSING.value,
        )

    for model in available_models:
        if getattr(model, "id", None) == config.model_id and bool(
            getattr(model, "can_access", True)
        ):
            return model

    raise TypedIOValidationException(
        (
            f"Step {step_order}: selected transcription model is not available in this space. "
            "Choose another transcription model in the flow transcription settings."
        ),
        code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_MODEL_UNAVAILABLE.value,
    )


async def transcribe_audio_input(
    *,
    files: list["FileInfo"],
    transcriber: FlowStepTranscriber,
    transcription_model: "TranscriptionModel",
    language: str,
    step_order: int,
    max_files: int,
    max_inline_text_bytes: int,
    open_audio_download: "OpenAudioDownload",
    transcription_call_observer: "ProviderCallObserver | None" = None,
    near_limit_ratio: float = 0.85,
    diarize: bool = True,
    max_speakers: int | None = None,
    source_preparation: TranscriptSourcePreparation | None = None,
    live_transcript: FlowLiveTranscripts | None = None,
    live_transcript_requested: bool = False,
) -> FlowTranscriptionResult:
    """Transcribe files in request order, closing each spool on every exit."""
    if not files:
        raise TypedIOValidationException(
            f"Step {step_order}: audio input requires at least one audio file.",
            code=FlowApiErrorCode.TYPED_IO_AUDIO_MISSING_FILE.value,
        )
    if len(files) > max_files:
        raise TypedIOValidationException(
            f"Step {step_order}: too many audio files ({len(files)}, max {max_files}).",
            code=FlowApiErrorCode.TYPED_IO_AUDIO_TOO_MANY_FILES.value,
        )

    for file in files:
        mimetype = str(getattr(file, "mimetype", "") or "")
        if not AudioMimeTypes.has_value(mimetype):
            raise TypedIOValidationException(
                (
                    f"Step {step_order}: file '{getattr(file, 'name', 'unknown')}' "
                    f"is not an audio file (got {mimetype})."
                ),
                code=FlowApiErrorCode.TYPED_IO_AUDIO_INVALID_FILE_TYPE.value,
            )

    transcription_started = time.monotonic()
    provider_language = to_provider_language(language)
    text_blocks: list[str] = []
    text_file_indices: list[int] = []
    block_segments: list[tuple[str, int, datetime] | None] = []
    measured_seconds: list[float] = []
    every_file_measured = True
    diarization_outcomes: list[str | None] = []
    diarization_elapsed: list[int] = []
    speakers: list[dict[str, Any]] = []
    alignments: list[str] = []
    segments: list[dict[str, Any]] = []
    words: list[dict[str, Any]] = []
    every_file_segmented = True
    review_files: list[dict[str, Any]] = []
    # Labels are assigned per file by the diarization service; renumber so one
    # label means one speaker across the whole transcript.
    source_preparation = source_preparation or TranscriptSourcePreparation()
    label_offset = source_preparation.speakers_count

    empty_intervals: list[EmptyTranscriptionInterval] = []
    transcript_origin: Literal["live", "batch"] = "batch"
    live_fallback_reason: LiveFallbackReason | None = None
    for file_index, file in enumerate(files):
        try:
            try:
                audio_file = await spool_audio(
                    file.id, open_audio_download=open_audio_download
                )
            except NotFoundException as exc:
                # A file can disappear between being identified and being read.
                # Report it as the missing file it is, not a transcription fault.
                raise TypedIOValidationException(
                    f"File content is unavailable for: [{file.id}]",
                    code=FlowApiErrorCode.TYPED_IO_FILE_NOT_FOUND.value,
                ) from exc
            try:
                transcribed = None
                if live_transcript_requested:
                    if (
                        live_transcript is None
                        or len(files) != 1
                        or live_transcript.bound_file_id != file.id
                    ):
                        live_fallback_reason = "unavailable"
                    elif live_transcript.segments is None:
                        # Known before any decode: batch it is.
                        live_fallback_reason = "no_timing"
                    else:
                        duration = await audio_file.measure_duration()
                        if abs(duration - live_transcript.received_audio_seconds) > max(
                            1.0, duration * 0.005
                        ):
                            live_fallback_reason = "duration_mismatch"
                        else:
                            # Streamed deltas carry the space that joined them; the
                            # speaker service's aligner refuses leading whitespace.
                            live_segments = tuple(
                                TranscriptSegment(
                                    text=str(segment["text"]).strip(),
                                    start=float(segment["start"]),
                                    end=float(segment["end"]),
                                )
                                for segment in live_transcript.segments
                                if str(segment["text"]).strip()
                            )
                            transcribed = TranscribedAudio(
                                text=live_transcript.text,
                                duration_seconds=duration,
                                segments=live_segments,
                                transcript_segments=live_segments,
                            )
                            if diarize:
                                transcribed = await transcriber.enrich(
                                    audio_file,
                                    transcription_model,
                                    transcribed=transcribed,
                                    file_id=file.id,
                                    language=provider_language,
                                    observer=transcription_call_observer,
                                    max_speakers=max_speakers,
                                )
                            transcript_origin = "live"
                if transcribed is None:
                    transcribed = await transcriber.transcribe(
                        audio_file,
                        transcription_model,
                        file_id=file.id,
                        language=provider_language,
                        diarize=diarize,
                        persist_cache_to_file=False,
                        observer=transcription_call_observer,
                        max_speakers=max_speakers if diarize else None,
                    )
            finally:
                await audio_file.aclose()
        except (
            TypedIOValidationException,
            ProviderCallObserverError,
            FlowStepCancelledError,
        ):
            # A cancelled run is the executor's outcome, not a step failure.
            # A failure to record what a request did is not a transcription
            # fault, and the executor already reports it as the evidence gap it
            # is. Flattening it here would hide which request went unrecorded.
            raise
        except AudioDecodeLimitExceeded as exc:
            raise TypedIOValidationException(
                str(exc),
                code=FlowApiErrorCode.TYPED_IO_AUDIO_EXCEEDS_LIMIT.value,
                context=exc.context,
            ) from exc
        except Exception as exc:
            raise TranscriptionFailure(
                (
                    f"Step {step_order}: transcription failed for "
                    f"'{getattr(file, 'name', 'unknown')}'."
                ),
                cause=exc,
            ) from exc

        if transcribed.duration_seconds is None:
            every_file_measured = False
        else:
            measured_seconds.append(transcribed.duration_seconds)

        diarization_outcomes.append(transcribed.diarization)
        empty_intervals.extend(
            replace(interval, file_id=file.id)
            for interval in transcribed.empty_intervals
        )
        if transcribed.diarization_elapsed_ms is not None:
            diarization_elapsed.append(transcribed.diarization_elapsed_ms)
        if transcribed.alignment:
            alignments.append(transcribed.alignment)
        block_text = transcribed.text
        block_transcript_segments = sorted(
            transcribed.transcript_segments or (),
            key=lambda segment: (segment.start, segment.end),
        )
        if transcribed.speaker_review is not None:
            review_files.append(
                {
                    **transcribed.speaker_review,
                    "file_index": file_index,
                    "file_id": str(file.id),
                    "overlaps": [
                        {**overlap, "id": f"{file.id}:{overlap['id']}"}
                        for overlap in transcribed.speaker_review.get("overlaps", [])
                    ],
                }
            )
        if transcribed.diarization == "external":
            label_mapping = build_label_renumbering(
                block_text, label_offset, segments=block_transcript_segments
            )
            block_text, label_count = renumber_speaker_labels(block_text, label_offset)
            label_count = len(label_mapping)
            block_transcript_segments = renumber_segment_speakers(
                block_transcript_segments, label_mapping
            )
            if block_transcript_segments:
                block_text = render_segments(block_transcript_segments)
            speakers.extend(
                build_speaker_inventory(
                    block_text,
                    file_index=file_index,
                    file_id=str(file.id),
                    segments=block_transcript_segments,
                )
            )
            label_offset += label_count
        if block_transcript_segments:
            words.extend(
                serialize_segment_words(
                    block_transcript_segments,
                    first_segment_index=len(segments),
                    file_id=str(file.id),
                )
            )
            segments.extend(
                serialize_segments(
                    block_transcript_segments,
                    file_index=file_index,
                    file_id=str(file.id),
                )
            )
        elif block_text.strip():
            # A reader can only seek by segments when every file has them;
            # a partial list would silently mislabel the transcript's parts.
            every_file_segmented = False
        if block_text.strip():
            text_blocks.append(block_text.strip())
            text_file_indices.append(file_index)
            block_segments.append(
                _parse_segment_filename(str(getattr(file, "name", "") or ""))
            )

    combined = _join_transcription_blocks(text_blocks, block_segments)
    if len(files) > 1 and review_files:
        # Explicit file headers retain playback identity even when timestamps restart.
        combined = "\n\n".join(
            f"## Del {file_index + 1}\n\n{block}"
            for file_index, block in zip(text_file_indices, text_blocks)
        )
    if not combined:
        raise TypedIOValidationException(
            f"Step {step_order}: transcription produced empty text.",
            code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_EMPTY.value,
        )

    transcript_bytes = len(combined.encode("utf-8"))
    threshold = int(max_inline_text_bytes * near_limit_ratio)
    near_inline_limit = transcript_bytes >= threshold
    estimated_tokens = count_tokens(combined)
    elapsed_ms = int((time.monotonic() - transcription_started) * 1000)
    source_preparation.append(
        files_count=len(files),
        segments=segments if every_file_segmented else [],
        speaker_review={"files": review_files} if review_files else None,
        words=words,
        words_omitted_reason=None,
        speakers_count=label_offset - source_preparation.speakers_count,
        alignment=_coarsest_alignment(alignments),
    )

    return FlowTranscriptionResult(
        text=combined,
        file_ids=[file.id for file in files],
        model_id=getattr(transcription_model, "id", None),
        model_name=str(getattr(transcription_model, "name", "unknown")),
        language=language,
        transcript_bytes=transcript_bytes,
        estimated_tokens=estimated_tokens,
        audio_seconds=round(sum(measured_seconds), 3) if every_file_measured else None,
        elapsed_ms=elapsed_ms,
        files_count=len(files),
        near_inline_limit=near_inline_limit,
        source_preparation=source_preparation,
        diarization=_combine_diarization_outcomes(diarization_outcomes),
        diarization_elapsed_ms=sum(diarization_elapsed)
        if diarization_elapsed
        else None,
        speakers=speakers,
        max_speakers=max_speakers if diarize else None,
        alignment=_coarsest_alignment(alignments),
        empty_intervals=tuple(empty_intervals),
        transcript_origin=transcript_origin,
        live_fallback_reason=live_fallback_reason,
    )


def capture_transcript_source(
    *,
    segments: list[dict[str, Any]],
    speaker_review: dict[str, Any] | None,
    words: list[dict[str, Any]],
    words_omitted_reason: str | None,
) -> TranscriptSource:
    return TranscriptSourcePreparation(
        files_count=1,
        segments=segments,
        speaker_review=speaker_review,
        words=words,
        words_omitted_reason=words_omitted_reason,
    ).source


# Alignment values the service reports when it could not force-align the text
# inside its chunk windows and labelled whole segments instead.
REDUCED_PRECISION_ALIGNMENTS = frozenset({"segment_split", "segment_only"})


def _coarsest_alignment(alignments: list[str]) -> str | None:
    """One alignment for the step: ``forced`` only when every file was forced."""
    if not alignments:
        return None
    return next(
        (value for value in alignments if value != "forced"),
        alignments[0],
    )


def _combine_diarization_outcomes(outcomes: list[str | None]) -> str | None:
    """One outcome for the step: any skipped file makes the step's labels partial."""
    skipped = [
        outcome for outcome in outcomes if outcome and outcome.startswith("skipped")
    ]
    if skipped:
        return skipped[0]
    if outcomes and all(outcome == "external" for outcome in outcomes):
        return "external"
    return None


async def resolve_and_transcribe_audio_for_step(
    *,
    version_metadata: dict[str, Any] | None,
    space_repo: "SpaceRepository",
    assistant_id: UUID,
    step_order: int,
    files: list["FileInfo"],
    requested_ids: list[UUID],
    transcriber: FlowStepTranscriber,
    max_files: int,
    max_inline_text_bytes: int,
    open_audio_download: OpenAudioDownload,
    transcription_call_observer: "ProviderCallObserver | None" = None,
    max_speakers: int | None = None,
    speaker_labels: bool | None = None,
    source_preparation: TranscriptSourcePreparation | None = None,
    live_transcript: FlowLiveTranscripts | None = None,
    live_transcript_requested: bool = False,
) -> FlowTranscriptionResult:
    try:
        transcription_config = parse_transcription_config(version_metadata)
    except FlowTranscriptionConfigError as exc:
        raise TypedIOValidationException(
            f"Step {step_order}: invalid transcription configuration in published flow metadata.",
            code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_CONFIG_INVALID.value,
        ) from exc

    if not transcription_config.enabled:
        raise TypedIOValidationException(
            (
                f"Step {step_order}: transcription must be enabled when using "
                "audio input."
            ),
            code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_NOT_ENABLED.value,
        )

    if transcription_config.model_id is None:
        raise TypedIOValidationException(
            (
                f"Step {step_order}: a transcription model must be configured "
                "for audio input."
            ),
            code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_MODEL_MISSING.value,
        )

    transcription_model = await resolve_transcription_model_for_step(
        space_repo=space_repo,
        assistant_id=assistant_id,
        config=transcription_config,
        step_order=step_order,
    )
    ordered_files = order_files_by_request(files, requested_ids)

    return await transcribe_audio_input(
        files=ordered_files,
        transcriber=transcriber,
        transcription_model=transcription_model,
        language=transcription_config.language,
        step_order=step_order,
        max_files=max_files,
        max_inline_text_bytes=max_inline_text_bytes,
        open_audio_download=open_audio_download,
        transcription_call_observer=transcription_call_observer,
        diarize=transcription_config.diarize(speaker_labels),
        max_speakers=max_speakers,
        source_preparation=source_preparation,
        live_transcript=live_transcript,
        live_transcript_requested=live_transcript_requested,
    )

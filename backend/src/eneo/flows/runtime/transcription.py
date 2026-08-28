from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias
from uuid import UUID

from eneo.completion_models.infrastructure.context_builder import count_tokens
from eneo.files.audio import AudioMimeTypes
from eneo.flows.domain.speaker_labels import (
    build_label_renumbering,
    build_speaker_inventory,
    renumber_segment_speakers,
    renumber_speaker_labels,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.run_cancellation import FlowStepCancelledError
from eneo.flows.transcription_config import (
    FlowTranscriptionConfig,
    FlowTranscriptionConfigError,
    parse_transcription_config,
    to_provider_language,
)
from eneo.main.exceptions import NotFoundException, TypedIOValidationException
from eneo.model_providers.domain.provider_call_observer import (
    ProviderCallObserverError,
)

# Reads one authorized audio file's bytes, immediately before transcription.
LoadAudioPayload: TypeAlias = Callable[[UUID], Awaitable["File"]]


class FlowStepTranscriber(Protocol):
    """What a flow audio step needs from a transcription engine.

    Satisfied by ``Transcriber`` (model-registry LiteLLM path) and
    ``RemoteFlowTranscriber`` (external transcription service).
    """

    async def transcribe(
        self,
        file: "File",
        transcription_model: "TranscriptionModel",
        *,
        language: str | None = None,
        diarize: bool = True,
        persist_cache_to_file: bool = True,
        observer: "ProviderCallObserver | None" = None,
        max_speakers: int | None = None,
    ) -> "TranscribedAudio": ...


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
    from eneo.files.file_models import File, FileInfo
    from eneo.files.transcriber import TranscribedAudio
    from eneo.model_providers.domain.provider_call_observer import (
        ProviderCallObserver,
    )
    from eneo.spaces.space_repo import SpaceRepository
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )
    from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
        TranscriptSegment,
    )


def _empty_speakers() -> list[dict[str, Any]]:
    return []


# Segments are evidence for a reader, not input to any step, so a transcript
# whose structured view would bloat the step's stored payload keeps only its
# text; the reader falls back to parsing the timestamped lines.
MAX_SEGMENTS_BYTES = 256 * 1024
SEGMENTS_OMITTED_TOO_LARGE = "too_large"


def serialize_segments(
    segments: Sequence["TranscriptSegment"], *, file_index: int
) -> list[dict[str, Any]]:
    """Structured transcript lines for one file, timestamps relative to that
    file's audio (a multi-file transcript restarts at zero per file)."""
    return [
        {
            "file_index": file_index,
            "start": round(segment.start, 2),
            "end": round(segment.end, 2),
            "speaker": segment.speaker,
            "text": segment.text,
        }
        for segment in segments
    ]


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
    # Structured transcript lines across all files (see ``serialize_segments``),
    # or None when the engine produced none or they exceeded the size cap.
    segments: list[dict[str, Any]] | None = None
    segments_omitted_reason: str | None = None

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
            "segments": self.segments,
            "segments_omitted_reason": self.segments_omitted_reason,
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
    load_audio_payload: "LoadAudioPayload",
    transcription_call_observer: "ProviderCallObserver | None" = None,
    near_limit_ratio: float = 0.85,
    diarize: bool = True,
    max_speakers: int | None = None,
) -> FlowTranscriptionResult:
    """Transcribe each audio file in request order, one payload at a time.

    ``files`` carries descriptive fields only. ``load_audio_payload`` reads one
    file's bytes immediately before it is transcribed and the result is released
    afterwards, so a step's memory cost is its largest audio file rather than
    the sum of every file it was given.
    """
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
    block_segments: list[tuple[str, int, datetime] | None] = []
    measured_seconds: list[float] = []
    every_file_measured = True
    diarization_outcomes: list[str | None] = []
    diarization_elapsed: list[int] = []
    speakers: list[dict[str, Any]] = []
    alignments: list[str] = []
    segments: list[dict[str, Any]] = []
    every_file_segmented = True
    # Labels are assigned per file by the diarization service; renumber so one
    # label means one speaker across the whole transcript.
    label_offset = 0

    for file_index, file in enumerate(files):
        # Reading a payload is part of this step's typed failure surface: it
        # authorizes, hydrates and verifies bytes, and every way it can fail
        # must reach the caller as a flow error rather than an escaping
        # exception.
        try:
            try:
                audio_file = await load_audio_payload(file.id)
            except NotFoundException as exc:
                # A file can disappear between being identified and being read.
                # Report it as the missing file it is, not a transcription fault.
                raise TypedIOValidationException(
                    f"File content is unavailable for: [{file.id}]",
                    code=FlowApiErrorCode.TYPED_IO_FILE_NOT_FOUND.value,
                ) from exc
            try:
                transcribed = await transcriber.transcribe(
                    audio_file,
                    transcription_model,
                    language=provider_language,
                    diarize=diarize,
                    persist_cache_to_file=False,
                    observer=transcription_call_observer,
                    max_speakers=max_speakers if diarize else None,
                )
            finally:
                del audio_file
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
        except Exception as exc:
            raise TypedIOValidationException(
                (
                    f"Step {step_order}: transcription failed for "
                    f"'{getattr(file, 'name', 'unknown')}'."
                ),
                code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED.value,
            ) from exc

        if transcribed.duration_seconds is None:
            every_file_measured = False
        else:
            measured_seconds.append(transcribed.duration_seconds)

        diarization_outcomes.append(transcribed.diarization)
        if transcribed.diarization_elapsed_ms is not None:
            diarization_elapsed.append(transcribed.diarization_elapsed_ms)
        if transcribed.alignment:
            alignments.append(transcribed.alignment)
        block_text = transcribed.text
        block_transcript_segments = list(transcribed.transcript_segments or ())
        if transcribed.diarization == "external":
            label_mapping = build_label_renumbering(block_text, label_offset)
            block_text, label_count = renumber_speaker_labels(block_text, label_offset)
            block_transcript_segments = renumber_segment_speakers(
                block_transcript_segments, label_mapping
            )
            speakers.extend(
                build_speaker_inventory(
                    block_text, file_index=file_index, file_id=str(file.id)
                )
            )
            label_offset += label_count
        if block_transcript_segments:
            segments.extend(
                serialize_segments(block_transcript_segments, file_index=file_index)
            )
        elif block_text.strip():
            # A reader can only seek by segments when every file has them;
            # a partial list would silently mislabel the transcript's parts.
            every_file_segmented = False
        if block_text.strip():
            text_blocks.append(block_text.strip())
            block_segments.append(
                _parse_segment_filename(str(getattr(file, "name", "") or ""))
            )

    combined = _join_transcription_blocks(text_blocks, block_segments)
    if not combined:
        raise TypedIOValidationException(
            f"Step {step_order}: transcription produced empty text.",
            code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_EMPTY.value,
        )

    transcript_bytes = len(combined.encode("utf-8"))
    if transcript_bytes > max_inline_text_bytes:
        raise TypedIOValidationException(
            (
                f"Step {step_order}: transcript exceeded max inline text bytes "
                f"({transcript_bytes} > {max_inline_text_bytes})."
            ),
            code=FlowApiErrorCode.TYPED_IO_TRANSCRIPT_TOO_LARGE.value,
        )

    threshold = int(max_inline_text_bytes * near_limit_ratio)
    near_inline_limit = transcript_bytes >= threshold
    estimated_tokens = count_tokens(combined)
    elapsed_ms = int((time.monotonic() - transcription_started) * 1000)
    kept_segments, segments_omitted_reason = _cap_segments(
        segments if every_file_segmented else []
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
        diarization=_combine_diarization_outcomes(diarization_outcomes),
        diarization_elapsed_ms=sum(diarization_elapsed)
        if diarization_elapsed
        else None,
        speakers=speakers,
        max_speakers=max_speakers if diarize else None,
        alignment=_coarsest_alignment(alignments),
        segments=kept_segments,
        segments_omitted_reason=segments_omitted_reason,
    )


def _cap_segments(
    segments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not segments:
        return None, None
    size = len(json.dumps(segments, ensure_ascii=False).encode("utf-8"))
    if size > MAX_SEGMENTS_BYTES:
        return None, SEGMENTS_OMITTED_TOO_LARGE
    return segments, None


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
    load_audio_payload: LoadAudioPayload,
    transcription_call_observer: "ProviderCallObserver | None" = None,
    max_speakers: int | None = None,
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
        load_audio_payload=load_audio_payload,
        transcription_call_observer=transcription_call_observer,
        diarize=transcription_config.diarization,
        max_speakers=max_speakers,
    )

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.completion_models.infrastructure.context_builder import count_tokens
from intric.files.audio import AudioMimeTypes
from intric.flows.transcription_config import (
    FlowTranscriptionConfig,
    FlowTranscriptionConfigError,
    parse_transcription_config,
    to_provider_language,
)
from intric.main.exceptions import TypedIOValidationException

# Filename pattern owned by the browser's multi-segment recorder. Anything
# uploaded as a single file (Whisper-direct or another integration) won't
# match — the transcript join then falls back to the unlabeled form.
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
    from intric.files.file_models import File
    from intric.files.transcriber import Transcriber
    from intric.spaces.space_repo import SpaceRepository
    from intric.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )


@dataclass(frozen=True)
class FlowTranscriptionResult:
    text: str
    file_ids: list[UUID]
    model_name: str
    language: str
    transcript_bytes: int
    estimated_tokens: int
    elapsed_ms: int
    files_count: int
    used_cache: bool
    cached_files_count: int
    near_inline_limit: bool

    def to_metadata(self) -> dict[str, Any]:
        return {
            "transcript_bytes": self.transcript_bytes,
            "estimated_tokens": self.estimated_tokens,
            "elapsed_ms": self.elapsed_ms,
            "files_count": self.files_count,
            "model": self.model_name,
            "language": self.language,
            "used_cache": self.used_cache,
            "cached_files_count": self.cached_files_count,
            "file_ids": [str(file_id) for file_id in self.file_ids],
        }


def order_files_by_request(
    files: list["File"],
    requested_ids: list[UUID],
) -> list["File"]:
    by_id = {item.id: item for item in files}
    ordered: list["File"] = []
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
            code="typed_io_transcription_model_missing",
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
        code="typed_io_transcription_model_unavailable",
    )


async def transcribe_audio_input(
    *,
    files: list["File"],
    transcriber: "Transcriber",
    transcription_model: "TranscriptionModel",
    language: str,
    step_order: int,
    max_files: int,
    max_inline_text_bytes: int,
    near_limit_ratio: float = 0.85,
) -> FlowTranscriptionResult:
    if not files:
        raise TypedIOValidationException(
            f"Step {step_order}: audio input requires at least one audio file.",
            code="typed_io_audio_missing_file",
        )
    if len(files) > max_files:
        raise TypedIOValidationException(
            f"Step {step_order}: too many audio files ({len(files)}, max {max_files}).",
            code="typed_io_audio_too_many_files",
        )

    for file in files:
        mimetype = str(getattr(file, "mimetype", "") or "")
        if not AudioMimeTypes.has_value(mimetype):
            raise TypedIOValidationException(
                (
                    f"Step {step_order}: file '{getattr(file, 'name', 'unknown')}' "
                    f"is not an audio file (got {mimetype})."
                ),
                code="typed_io_audio_invalid_file_type",
            )

    transcription_started = time.monotonic()
    provider_language = to_provider_language(language)
    cache_eligible = provider_language is None
    text_blocks: list[str] = []
    block_segments: list[tuple[str, int, datetime] | None] = []
    cached_files_count = 0

    for file in files:
        has_cached_transcription = bool(
            cache_eligible
            and isinstance(getattr(file, "transcription", None), str)
            and str(getattr(file, "transcription", "")).strip()
        )
        if has_cached_transcription:
            cached_files_count += 1

        try:
            block_text = await transcriber.transcribe(
                file,
                transcription_model,
                language=provider_language,
            )
        except TypedIOValidationException:
            raise
        except Exception as exc:
            raise TypedIOValidationException(
                (
                    f"Step {step_order}: transcription failed for "
                    f"'{getattr(file, 'name', 'unknown')}'."
                ),
                code="typed_io_transcription_failed",
            ) from exc

        if block_text.strip():
            text_blocks.append(block_text.strip())
            block_segments.append(
                _parse_segment_filename(str(getattr(file, "name", "") or ""))
            )

    combined = _join_transcription_blocks(text_blocks, block_segments)
    if not combined:
        raise TypedIOValidationException(
            f"Step {step_order}: transcription produced empty text.",
            code="typed_io_transcription_empty",
        )

    transcript_bytes = len(combined.encode("utf-8"))
    if transcript_bytes > max_inline_text_bytes:
        raise TypedIOValidationException(
            (
                f"Step {step_order}: transcript exceeded max inline text bytes "
                f"({transcript_bytes} > {max_inline_text_bytes})."
            ),
            code="typed_io_transcript_too_large",
        )

    threshold = int(max_inline_text_bytes * near_limit_ratio)
    near_inline_limit = transcript_bytes >= threshold
    estimated_tokens = count_tokens(combined)
    elapsed_ms = int((time.monotonic() - transcription_started) * 1000)

    return FlowTranscriptionResult(
        text=combined,
        file_ids=[file.id for file in files],
        model_name=str(getattr(transcription_model, "name", "unknown")),
        language=language,
        transcript_bytes=transcript_bytes,
        estimated_tokens=estimated_tokens,
        elapsed_ms=elapsed_ms,
        files_count=len(files),
        used_cache=cached_files_count == len(files),
        cached_files_count=cached_files_count,
        near_inline_limit=near_inline_limit,
    )


async def resolve_and_transcribe_audio_for_step(
    *,
    version_metadata: dict[str, Any] | None,
    space_repo: "SpaceRepository",
    assistant_id: UUID,
    step_order: int,
    files: list["File"],
    requested_ids: list[UUID],
    transcriber: "Transcriber",
    max_files: int,
    max_inline_text_bytes: int,
) -> FlowTranscriptionResult:
    try:
        transcription_config = parse_transcription_config(version_metadata)
    except FlowTranscriptionConfigError as exc:
        raise TypedIOValidationException(
            f"Step {step_order}: invalid transcription configuration in published flow metadata.",
            code="typed_io_transcription_config_invalid",
        ) from exc

    if not transcription_config.enabled:
        raise TypedIOValidationException(
            (
                f"Step {step_order}: transcription must be enabled when using "
                "audio input."
            ),
            code="typed_io_transcription_not_enabled",
        )

    if transcription_config.model_id is None:
        raise TypedIOValidationException(
            (
                f"Step {step_order}: a transcription model must be configured "
                "for audio input."
            ),
            code="typed_io_transcription_model_missing",
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
    )

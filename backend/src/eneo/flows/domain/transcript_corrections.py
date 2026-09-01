"""Non-destructive transcript corrections for flow transcription steps.

A correction set stores char-range replacements anchored to the structured
transcript lines a transcription step persisted (``transcription.segments`` in
the step result's ``input_payload_json``). The raw transcript is never
rewritten: corrections are applied on read, so every corrected span keeps its
original text for auditing and revert.

Anchors are only valid for the exact segment array they were written against;
``segments_content_hash`` is the staleness token that detects re-transcription.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eneo.authentication.principal_types import PrincipalType

TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION = 1
MAX_CORRECTION_OCCURRENCES = 2000


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionOccurrence:
    """One corrected span: ``original`` at ``[char_start, char_end)`` of the
    segment's text becomes ``corrected`` (empty string deletes the span)."""

    segment_index: int
    char_start: int
    char_end: int
    original: str
    corrected: str

    def as_json(self) -> dict[str, Any]:
        return {
            "segment_index": self.segment_index,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "original": self.original,
            "corrected": self.corrected,
        }


@dataclass(eq=False)
class TranscriptCorrectionInvalidOccurrenceError(Exception):
    """A submitted occurrence does not fit the segment array it targets."""

    reason: str
    context: dict[str, Any]


@dataclass(eq=False)
class FlowTranscriptCorrectionsStaleRevisionError(Exception):
    """The compare-and-swap revision no longer matches the stored row.

    ``current_revision`` is None when no row exists for the step;
    ``expected_revision`` is None when the caller tried to create a row that
    already exists.
    """

    expected_revision: int | None
    current_revision: int | None


class FlowTranscriptCorrectionSet(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    step_id: UUID
    occurrences_json: list[dict[str, Any]]
    revision: int
    schema_version: int
    segments_hash: str
    edited_by_user_id: UUID | None = None
    edited_by_service_id: UUID | None = None
    edited_by_principal_type: PrincipalType
    created_at: datetime
    updated_at: datetime

    def occurrences(self) -> list[TranscriptCorrectionOccurrence]:
        return [
            TranscriptCorrectionOccurrence(
                segment_index=int(item["segment_index"]),
                char_start=int(item["char_start"]),
                char_end=int(item["char_end"]),
                original=str(item["original"]),
                corrected=str(item["corrected"]),
            )
            for item in self.occurrences_json
        ]


def segments_content_hash(raw_segments: list[dict[str, Any]]) -> str:
    """Staleness token for a stored segment array.

    Canonical JSON so key order and whitespace never change the hash; any
    re-transcription that changes a single character invalidates anchors.
    """
    canonical = json.dumps(
        raw_segments,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sort_occurrences(
    occurrences: list[TranscriptCorrectionOccurrence],
) -> list[TranscriptCorrectionOccurrence]:
    """Canonical order so saves, dirty checks, and diffs are stable."""
    return sorted(occurrences, key=lambda item: (item.segment_index, item.char_start))


def _segment_text(segment: dict[str, Any]) -> str:
    text = segment.get("text")
    return text if isinstance(text, str) else ""


def validate_occurrences(
    segments: list[dict[str, Any]],
    occurrences: list[TranscriptCorrectionOccurrence],
) -> None:
    """Reject occurrence lists that do not fit ``segments`` exactly.

    Raises TranscriptCorrectionInvalidOccurrenceError for the first violation:
    out-of-range segment index, invalid char range, a span whose ``original``
    no longer matches the anchored text, overlapping ranges within a segment,
    or an oversized list.
    """
    if len(occurrences) > MAX_CORRECTION_OCCURRENCES:
        raise TranscriptCorrectionInvalidOccurrenceError(
            reason="too_many_occurrences",
            context={
                "occurrence_count": len(occurrences),
                "max_occurrences": MAX_CORRECTION_OCCURRENCES,
            },
        )
    by_segment: dict[int, list[TranscriptCorrectionOccurrence]] = {}
    for occurrence in occurrences:
        if not 0 <= occurrence.segment_index < len(segments):
            raise TranscriptCorrectionInvalidOccurrenceError(
                reason="segment_index_out_of_range",
                context={
                    "segment_index": occurrence.segment_index,
                    "segment_count": len(segments),
                },
            )
        text = _segment_text(segments[occurrence.segment_index])
        if not 0 <= occurrence.char_start < occurrence.char_end <= len(text):
            raise TranscriptCorrectionInvalidOccurrenceError(
                reason="char_range_invalid",
                context={
                    "segment_index": occurrence.segment_index,
                    "char_start": occurrence.char_start,
                    "char_end": occurrence.char_end,
                    "text_length": len(text),
                },
            )
        anchored = text[occurrence.char_start : occurrence.char_end]
        if anchored != occurrence.original:
            raise TranscriptCorrectionInvalidOccurrenceError(
                reason="original_mismatch",
                context={
                    "segment_index": occurrence.segment_index,
                    "char_start": occurrence.char_start,
                    "char_end": occurrence.char_end,
                    "anchored_text": anchored,
                    "original": occurrence.original,
                },
            )
        by_segment.setdefault(occurrence.segment_index, []).append(occurrence)
    for segment_index, segment_occurrences in by_segment.items():
        ordered = sorted(segment_occurrences, key=lambda item: item.char_start)
        for previous, current in zip(ordered, ordered[1:]):
            if current.char_start < previous.char_end:
                raise TranscriptCorrectionInvalidOccurrenceError(
                    reason="overlapping_ranges",
                    context={
                        "segment_index": segment_index,
                        "first_range": [previous.char_start, previous.char_end],
                        "second_range": [current.char_start, current.char_end],
                    },
                )


def apply_corrections(
    segments: list[dict[str, Any]],
    occurrences: list[TranscriptCorrectionOccurrence],
) -> tuple[list[dict[str, Any]], list[TranscriptCorrectionOccurrence]]:
    """Return corrected copies of ``segments`` plus the skipped occurrences.

    Occurrences whose anchor no longer matches (or no longer exists) are
    skipped, never applied approximately. Within a segment, replacements run
    right-to-left so earlier char offsets stay valid.
    """
    by_segment: dict[int, list[TranscriptCorrectionOccurrence]] = {}
    skipped: list[TranscriptCorrectionOccurrence] = []
    for occurrence in occurrences:
        if not 0 <= occurrence.segment_index < len(segments):
            skipped.append(occurrence)
            continue
        by_segment.setdefault(occurrence.segment_index, []).append(occurrence)

    corrected_segments = [dict(segment) for segment in segments]
    for segment_index, segment_occurrences in by_segment.items():
        text = _segment_text(corrected_segments[segment_index])
        applicable: list[TranscriptCorrectionOccurrence] = []
        for occurrence in segment_occurrences:
            in_range = 0 <= occurrence.char_start < occurrence.char_end <= len(text)
            if (
                not in_range
                or text[occurrence.char_start : occurrence.char_end]
                != occurrence.original
            ):
                skipped.append(occurrence)
                continue
            applicable.append(occurrence)
        for occurrence in sorted(
            applicable, key=lambda item: item.char_start, reverse=True
        ):
            text = (
                text[: occurrence.char_start]
                + occurrence.corrected
                + text[occurrence.char_end :]
            )
        corrected_segments[segment_index]["text"] = text
    return corrected_segments, skipped

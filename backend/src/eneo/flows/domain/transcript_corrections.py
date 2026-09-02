"""Non-destructive transcript corrections for flow transcription steps.

A correction set stores char-range replacements anchored to the structured
transcript lines a transcription step persisted (``transcription.segments`` in
the step result's ``input_payload_json``). The raw transcript is never
rewritten: corrections are applied on read, so every corrected span keeps its
original text for auditing and revert.

Speaker edits live in the same set: a whole-segment edit reassigns a stored
line to another speaker label, a span edit reassigns part of a line. Both
anchor to the raw segment array exactly like text occurrences do.

Anchors are only valid for the exact segment array they were written against;
``segments_content_hash`` is the staleness token that detects re-transcription.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.domain.speaker_labels import SPEAKER_LABEL_RE, SPEAKER_LINE_RE

TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION = 2
SUPPORTED_TRANSCRIPT_CORRECTIONS_SCHEMA_VERSIONS = frozenset({1, 2})
MAX_CORRECTION_OCCURRENCES = 2000
MAX_SPEAKER_EDITS = 2000


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


@dataclass(frozen=True, slots=True)
class TranscriptSpeakerEdit:
    """Reassigns a segment, or a raw-text span of it, to another speaker.

    The null-span shape (``char_start``/``char_end``/``original`` all None)
    re-attributes the whole segment regardless of its text. A present span
    re-attributes exactly ``original`` at ``[char_start, char_end)`` of the
    raw text. ``original_speaker`` anchors both shapes to the segment's
    stored label, exactly as ``original`` anchors a text occurrence.
    """

    segment_index: int
    char_start: int | None
    char_end: int | None
    original: str | None
    original_speaker: str
    speaker: str

    @property
    def is_whole_segment(self) -> bool:
        return self.char_start is None

    def as_json(self) -> dict[str, Any]:
        return {
            "segment_index": self.segment_index,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "original": self.original,
            "original_speaker": self.original_speaker,
            "speaker": self.speaker,
        }


@dataclass(eq=False)
class TranscriptCorrectionInvalidOccurrenceError(Exception):
    """A submitted occurrence does not fit the segment array it targets."""

    reason: str
    context: dict[str, Any]


@dataclass(eq=False)
class TranscriptSpeakerEditInvalidError(Exception):
    """A submitted speaker edit does not fit the segment array it targets."""

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
    speaker_edits_json: list[dict[str, Any]] = Field(
        default_factory=list[dict[str, Any]]
    )
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

    def speaker_edits(self) -> list[TranscriptSpeakerEdit]:
        return [
            TranscriptSpeakerEdit(
                segment_index=int(item["segment_index"]),
                char_start=(
                    int(item["char_start"]) if item["char_start"] is not None else None
                ),
                char_end=(
                    int(item["char_end"]) if item["char_end"] is not None else None
                ),
                original=(
                    str(item["original"]) if item["original"] is not None else None
                ),
                original_speaker=str(item["original_speaker"]),
                speaker=str(item["speaker"]),
            )
            for item in self.speaker_edits_json
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


def sort_speaker_edits(
    speaker_edits: list[TranscriptSpeakerEdit],
) -> list[TranscriptSpeakerEdit]:
    """Canonical order: whole-segment edits first, then spans by offset."""
    return sorted(
        speaker_edits,
        key=lambda item: (
            item.segment_index,
            -1 if item.char_start is None else item.char_start,
        ),
    )


def _segment_text(segment: dict[str, Any]) -> str:
    text = segment.get("text")
    return text if isinstance(text, str) else ""


def _segment_speaker(segment: dict[str, Any]) -> str | None:
    speaker = segment.get("speaker")
    return speaker if isinstance(speaker, str) and speaker else None


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


def validate_speaker_edits(
    segments: list[dict[str, Any]],
    speaker_edits: list[TranscriptSpeakerEdit],
) -> None:
    """Reject speaker-edit lists that do not fit ``segments`` exactly.

    Raises TranscriptSpeakerEditInvalidError for the first violation. A
    whole-segment edit is exclusive with any other edit on the same segment;
    span edits must not overlap each other (adjacent spans are fine). An edit
    that keeps the stored speaker is rejected: revert is expressed by removing
    the edit, never by writing a no-op.
    """
    if len(speaker_edits) > MAX_SPEAKER_EDITS:
        raise TranscriptSpeakerEditInvalidError(
            reason="too_many_speaker_edits",
            context={
                "speaker_edit_count": len(speaker_edits),
                "max_speaker_edits": MAX_SPEAKER_EDITS,
            },
        )
    by_segment: dict[int, list[TranscriptSpeakerEdit]] = {}
    for edit in speaker_edits:
        if not 0 <= edit.segment_index < len(segments):
            raise TranscriptSpeakerEditInvalidError(
                reason="segment_index_out_of_range",
                context={
                    "segment_index": edit.segment_index,
                    "segment_count": len(segments),
                },
            )
        for label in (edit.original_speaker, edit.speaker):
            if not SPEAKER_LABEL_RE.match(label):
                raise TranscriptSpeakerEditInvalidError(
                    reason="invalid_speaker_label",
                    context={"segment_index": edit.segment_index, "label": label},
                )
        segment = segments[edit.segment_index]
        stored_speaker = _segment_speaker(segment)
        if stored_speaker is None:
            raise TranscriptSpeakerEditInvalidError(
                reason="segment_has_no_speaker",
                context={"segment_index": edit.segment_index},
            )
        if edit.original_speaker != stored_speaker:
            raise TranscriptSpeakerEditInvalidError(
                reason="original_speaker_mismatch",
                context={
                    "segment_index": edit.segment_index,
                    "original_speaker": edit.original_speaker,
                    "stored_speaker": stored_speaker,
                },
            )
        if edit.char_start is None or edit.char_end is None or edit.original is None:
            all_null = (
                edit.char_start is None
                and edit.char_end is None
                and edit.original is None
            )
            if not all_null:
                raise TranscriptSpeakerEditInvalidError(
                    reason="char_range_invalid",
                    context={
                        "segment_index": edit.segment_index,
                        "char_start": edit.char_start,
                        "char_end": edit.char_end,
                    },
                )
        else:
            text = _segment_text(segment)
            if not 0 <= edit.char_start < edit.char_end <= len(text):
                raise TranscriptSpeakerEditInvalidError(
                    reason="char_range_invalid",
                    context={
                        "segment_index": edit.segment_index,
                        "char_start": edit.char_start,
                        "char_end": edit.char_end,
                        "text_length": len(text),
                    },
                )
            anchored = text[edit.char_start : edit.char_end]
            if anchored != edit.original:
                raise TranscriptSpeakerEditInvalidError(
                    reason="original_mismatch",
                    context={
                        "segment_index": edit.segment_index,
                        "char_start": edit.char_start,
                        "char_end": edit.char_end,
                        "anchored_text": anchored,
                        "original": edit.original,
                    },
                )
        if edit.speaker == stored_speaker:
            raise TranscriptSpeakerEditInvalidError(
                reason="speaker_unchanged",
                context={
                    "segment_index": edit.segment_index,
                    "speaker": edit.speaker,
                },
            )
        by_segment.setdefault(edit.segment_index, []).append(edit)
    for segment_index, segment_edits in by_segment.items():
        wholes = [edit for edit in segment_edits if edit.is_whole_segment]
        spans = [edit for edit in segment_edits if not edit.is_whole_segment]
        if wholes and (spans or len(wholes) > 1):
            raise TranscriptSpeakerEditInvalidError(
                reason="whole_segment_conflicts_with_span",
                context={"segment_index": segment_index},
            )
        ordered = sorted((edit.char_start or 0, edit.char_end or 0) for edit in spans)
        for previous, current in zip(ordered, ordered[1:]):
            if current[0] < previous[1]:
                raise TranscriptSpeakerEditInvalidError(
                    reason="overlapping_speaker_spans",
                    context={
                        "segment_index": segment_index,
                        "first_range": [previous[0], previous[1]],
                        "second_range": [current[0], current[1]],
                    },
                )


def _applicable_text_occurrences(
    text: str,
    occurrences: list[TranscriptCorrectionOccurrence],
    skipped: list[TranscriptCorrectionOccurrence],
) -> list[TranscriptCorrectionOccurrence]:
    """Anchor-verified occurrences for one segment, sorted by offset."""
    applicable: list[TranscriptCorrectionOccurrence] = []
    for occurrence in occurrences:
        in_range = 0 <= occurrence.char_start < occurrence.char_end <= len(text)
        if (
            not in_range
            or text[occurrence.char_start : occurrence.char_end] != occurrence.original
        ):
            skipped.append(occurrence)
            continue
        applicable.append(occurrence)
    return sorted(applicable, key=lambda item: item.char_start)


def _map_raw_offset(
    boundary: int,
    applicable: list[TranscriptCorrectionOccurrence],
) -> int:
    """Map a raw-text offset into corrected-text space (monotone, total).

    ``applicable`` must be this segment's anchor-verified occurrences sorted
    ascending. A boundary strictly inside a replaced span clamps inside the
    replacement so runs stay contiguous whatever the replacement length.
    """
    delta = 0
    for occurrence in applicable:
        if occurrence.char_end <= boundary:
            delta += len(occurrence.corrected) - (
                occurrence.char_end - occurrence.char_start
            )
        elif occurrence.char_start < boundary:
            offset_in_span = min(
                boundary - occurrence.char_start, len(occurrence.corrected)
            )
            return occurrence.char_start + delta + offset_in_span
        else:
            break
    return boundary + delta


def _corrected_speaker_runs(
    raw_text: str,
    stored_speaker: str,
    spans: list[TranscriptSpeakerEdit],
    applicable: list[TranscriptCorrectionOccurrence],
    skipped: list[TranscriptSpeakerEdit],
) -> list[dict[str, Any]]:
    """Consecutive speaker runs over the corrected text, merged and non-empty.

    ``spans`` are this segment's anchor-verified span edits. A single run in
    the stored speaker means nothing changed and the result is empty.
    """
    raw_runs: list[tuple[int, int, str]] = []
    cursor = 0
    for edit in sorted(spans, key=lambda item: item.char_start or 0):
        start = edit.char_start or 0
        end = edit.char_end or 0
        if start < cursor:
            # Overlap can only mean corrupt storage; skip, never guess.
            skipped.append(edit)
            continue
        if cursor < start:
            raw_runs.append((cursor, start, stored_speaker))
        raw_runs.append((start, end, edit.speaker))
        cursor = end
    if cursor < len(raw_text):
        raw_runs.append((cursor, len(raw_text), stored_speaker))

    merged: list[dict[str, Any]] = []
    for raw_start, raw_end, speaker in raw_runs:
        start = _map_raw_offset(raw_start, applicable)
        end = _map_raw_offset(raw_end, applicable)
        if start >= end:
            continue
        if merged and merged[-1]["speaker"] == speaker:
            merged[-1]["char_end"] = end
            continue
        merged.append({"char_start": start, "char_end": end, "speaker": speaker})
    if len(merged) == 1 and merged[0]["speaker"] == stored_speaker:
        return []
    return merged


def apply_corrections_and_speaker_edits(
    segments: list[dict[str, Any]],
    occurrences: list[TranscriptCorrectionOccurrence],
    speaker_edits: list[TranscriptSpeakerEdit],
) -> tuple[
    list[dict[str, Any]],
    list[TranscriptCorrectionOccurrence],
    list[TranscriptSpeakerEdit],
]:
    """Corrected copies of ``segments`` plus whatever could not be applied.

    Text corrections replace within ``text`` right-to-left. Speaker edits
    then attribute content: a whole-segment edit replaces ``speaker``; span
    edits attach ``speaker_runs`` (consecutive ``{char_start, char_end,
    speaker}`` runs covering the corrected text, raw boundaries mapped through
    the applied corrections) unless they collapse to a single speaker, which
    replaces ``speaker`` instead. Mismatched anchors are skipped, never
    applied approximately.
    """
    skipped_occurrences: list[TranscriptCorrectionOccurrence] = []
    skipped_speaker_edits: list[TranscriptSpeakerEdit] = []
    occurrences_by_segment: dict[int, list[TranscriptCorrectionOccurrence]] = {}
    for occurrence in occurrences:
        if not 0 <= occurrence.segment_index < len(segments):
            skipped_occurrences.append(occurrence)
            continue
        occurrences_by_segment.setdefault(occurrence.segment_index, []).append(
            occurrence
        )
    edits_by_segment: dict[int, list[TranscriptSpeakerEdit]] = {}
    for edit in speaker_edits:
        if not 0 <= edit.segment_index < len(segments):
            skipped_speaker_edits.append(edit)
            continue
        edits_by_segment.setdefault(edit.segment_index, []).append(edit)

    corrected_segments = [dict(segment) for segment in segments]
    touched = sorted(set(occurrences_by_segment) | set(edits_by_segment))
    for segment_index in touched:
        raw_text = _segment_text(segments[segment_index])
        stored_speaker = _segment_speaker(segments[segment_index])
        applicable = _applicable_text_occurrences(
            raw_text,
            occurrences_by_segment.get(segment_index, []),
            skipped_occurrences,
        )
        text = raw_text
        for occurrence in reversed(applicable):
            text = (
                text[: occurrence.char_start]
                + occurrence.corrected
                + text[occurrence.char_end :]
            )
        if segment_index in occurrences_by_segment:
            corrected_segments[segment_index]["text"] = text

        applicable_edits: list[TranscriptSpeakerEdit] = []
        for edit in sort_speaker_edits(edits_by_segment.get(segment_index, [])):
            anchored = (
                stored_speaker is not None and edit.original_speaker == stored_speaker
            )
            if anchored and not edit.is_whole_segment:
                anchored = (
                    edit.char_start is not None
                    and edit.char_end is not None
                    and 0 <= edit.char_start < edit.char_end <= len(raw_text)
                    and raw_text[edit.char_start : edit.char_end] == edit.original
                )
            if not anchored:
                skipped_speaker_edits.append(edit)
                continue
            applicable_edits.append(edit)
        wholes = [edit for edit in applicable_edits if edit.is_whole_segment]
        spans = [edit for edit in applicable_edits if not edit.is_whole_segment]
        if wholes:
            # Canonical sets hold at most one whole-segment edit and no
            # coexisting spans; anything extra is corrupt storage — skip it.
            corrected_segments[segment_index]["speaker"] = wholes[0].speaker
            skipped_speaker_edits.extend(wholes[1:])
            skipped_speaker_edits.extend(spans)
        elif spans and stored_speaker is not None:
            runs = _corrected_speaker_runs(
                raw_text, stored_speaker, spans, applicable, skipped_speaker_edits
            )
            if len(runs) == 1:
                corrected_segments[segment_index]["speaker"] = runs[0]["speaker"]
            elif runs:
                corrected_segments[segment_index]["speaker_runs"] = runs
    return corrected_segments, skipped_occurrences, skipped_speaker_edits


def apply_corrections(
    segments: list[dict[str, Any]],
    occurrences: list[TranscriptCorrectionOccurrence],
) -> tuple[list[dict[str, Any]], list[TranscriptCorrectionOccurrence]]:
    """Return corrected copies of ``segments`` plus the skipped occurrences.

    Occurrences whose anchor no longer matches (or no longer exists) are
    skipped, never applied approximately. Within a segment, replacements run
    right-to-left so earlier char offsets stay valid.
    """
    corrected_segments, skipped, _ = apply_corrections_and_speaker_edits(
        segments, occurrences, []
    )
    return corrected_segments, skipped


def apply_to_rendered_transcript(
    rendered_text: str,
    segments: list[dict[str, Any]],
    occurrences: list[TranscriptCorrectionOccurrence],
    speaker_edits: list[TranscriptSpeakerEdit],
) -> str | None:
    """Patch the rendered transcript lines, or None when they do not align.

    The rendered text is patchable only while its speaker lines correspond
    1:1, in order, to the stored segments (same label, same text). Any
    mismatch — a hand-edited line, a drifted render — returns None; callers
    must skip propagation rather than partial-apply. Non-speaker lines (part
    headers, blanks) pass through untouched. A segment attributed to several
    speakers renders one line per run, reusing the segment's timestamp prefix.
    """
    lines = rendered_text.split("\n")
    matches: list[tuple[int, re.Match[str]]] = []
    for line_index, line in enumerate(lines):
        match = SPEAKER_LINE_RE.match(line)
        if match:
            matches.append((line_index, match))
    if len(matches) != len(segments):
        return None
    for (_, match), segment in zip(matches, segments):
        if match.group("label") != _segment_speaker(segment):
            return None
        if match.group("text") != _segment_text(segment):
            return None
    corrected_segments, _, _ = apply_corrections_and_speaker_edits(
        segments, occurrences, speaker_edits
    )
    for (line_index, match), corrected in zip(matches, corrected_segments):
        prefix = match.group("prefix")
        text = _segment_text(corrected)
        speaker = _segment_speaker(corrected)
        runs = corrected.get("speaker_runs")
        rendered_runs: list[str] = []
        if isinstance(runs, list):
            for run in cast("list[dict[str, Any]]", runs):
                run_text = text[run["char_start"] : run["char_end"]].strip()
                if run_text:
                    rendered_runs.append(f"{prefix}{run['speaker']}: {run_text}")
        if rendered_runs:
            lines[line_index] = "\n".join(rendered_runs)
        else:
            lines[line_index] = f"{prefix}{speaker}: {text}"
    return "\n".join(lines)

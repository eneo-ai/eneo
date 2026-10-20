"""Non-destructive corrections to a transcribe step's transcript.

A correction set stores char-range replacements anchored to the segments a
transcribe step kept with its result (``transcription.segments`` in the
step's ``input_payload_json``). The stored transcript is never rewritten:
corrections are applied on read, so every corrected span keeps its original
text. Speaker edits live in the same set (a whole segment, or a span of it,
reassigned to another label), and so do speaker names (a person's name per
label; None clears a name a mapping gave).

Anchors are only valid for the exact segment array they were written
against: ``segments_content_hash`` is the staleness token a client sends
back as ``segments_hash``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Optional, cast

from eneo.flows.speaker_labels import SPEAKER_LABEL_RE, render_segments

TRANSCRIPT_CORRECTIONS_SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3})
MAX_CORRECTION_OCCURRENCES = 2000
MAX_SPEAKER_EDITS = 2000
MAX_SPEAKER_NAMES = 100
NAME_MAX_CHARS = 120


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionOccurrence:
    """``original`` at ``[char_start, char_end)`` of the segment's text
    becomes ``corrected`` (an empty string deletes the span)."""

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

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> TranscriptCorrectionOccurrence:
        return cls(
            segment_index=int(raw["segment_index"]),
            char_start=int(raw["char_start"]),
            char_end=int(raw["char_end"]),
            original=str(raw["original"]),
            corrected=str(raw.get("corrected", "")),
        )


@dataclass(frozen=True, slots=True)
class TranscriptSpeakerEdit:
    """Reassigns a segment, or a raw-text span of it, to another speaker.

    All-null span fields re-attribute the whole segment; a present span
    re-attributes exactly ``original`` at ``[char_start, char_end)``.
    ``original_speaker`` anchors both shapes to the stored label.
    """

    segment_index: int
    char_start: Optional[int]
    char_end: Optional[int]
    original: Optional[str]
    original_speaker: Optional[str]
    speaker: Optional[str]
    decision: Literal["confirmed", "unresolved"] = "confirmed"

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
            "decision": self.decision,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> TranscriptSpeakerEdit:
        decision = raw.get("decision", "confirmed")
        return cls(
            segment_index=int(raw["segment_index"]),
            char_start=raw.get("char_start"),
            char_end=raw.get("char_end"),
            original=raw.get("original"),
            original_speaker=raw.get("original_speaker"),
            speaker=raw.get("speaker"),
            decision="unresolved" if decision == "unresolved" else "confirmed",
        )


@dataclass(eq=False)
class TranscriptCorrectionInvalidOccurrenceError(Exception):
    reason: str
    context: dict[str, Any]


@dataclass(eq=False)
class TranscriptSpeakerEditInvalidError(Exception):
    reason: str
    context: dict[str, Any]


def segments_content_hash(raw_segments: Sequence[Mapping[str, Any]]) -> str:
    """sha256 over the canonical JSON of the segment array (64 hex chars)."""
    digest = hashlib.sha256()
    digest.update(b"[")
    for index, segment in enumerate(raw_segments):
        if index:
            digest.update(b",")
        digest.update(
            json.dumps(
                dict(segment), sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        )
    digest.update(b"]")
    return digest.hexdigest()


def _segment_text(segment: Mapping[str, Any]) -> str:
    return str(segment.get("text") or "")


def _segment_speaker(segment: Mapping[str, Any]) -> Optional[str]:
    speaker = segment.get("speaker")
    return str(speaker) if speaker else None


def sort_occurrences(
    occurrences: Sequence[TranscriptCorrectionOccurrence],
) -> list[TranscriptCorrectionOccurrence]:
    return sorted(occurrences, key=lambda o: (o.segment_index, o.char_start))


def sort_speaker_edits(
    edits: Sequence[TranscriptSpeakerEdit],
) -> list[TranscriptSpeakerEdit]:
    return sorted(
        edits,
        key=lambda e: (
            e.segment_index,
            0 if e.is_whole_segment else 1,
            e.char_start or 0,
        ),
    )


def validate_occurrences(
    segments: Sequence[Mapping[str, Any]],
    occurrences: Sequence[TranscriptCorrectionOccurrence],
) -> None:
    """Reject occurrences that do not fit ``segments`` exactly (first violation)."""
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
    for segment_index, items in by_segment.items():
        ordered = sorted(items, key=lambda item: item.char_start)
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
    segments: Sequence[Mapping[str, Any]],
    speaker_edits: Sequence[TranscriptSpeakerEdit],
) -> None:
    """Reject speaker edits that do not fit ``segments`` exactly.

    A whole-segment edit is exclusive with any other edit on the same
    segment; span edits must not overlap. A confirmed decision names a
    speaker, an unresolved one names none.
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
            if label is not None and not SPEAKER_LABEL_RE.fullmatch(label):
                raise TranscriptSpeakerEditInvalidError(
                    reason="invalid_speaker_label",
                    context={"segment_index": edit.segment_index, "label": label},
                )
        segment = segments[edit.segment_index]
        stored_speaker = _segment_speaker(segment)
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
            if not (
                edit.char_start is None
                and edit.char_end is None
                and edit.original is None
            ):
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
        if (edit.decision == "confirmed") != (edit.speaker is not None):
            raise TranscriptSpeakerEditInvalidError(
                reason="invalid_decision", context={"segment_index": edit.segment_index}
            )
        by_segment.setdefault(edit.segment_index, []).append(edit)
    for segment_index, items in by_segment.items():
        wholes = [edit for edit in items if edit.is_whole_segment]
        spans = [edit for edit in items if not edit.is_whole_segment]
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


def validate_correction_partitions(
    occurrences: Sequence[TranscriptCorrectionOccurrence],
    edits: Sequence[TranscriptSpeakerEdit],
) -> None:
    """A replacement cannot consume text on both sides of a speaker boundary."""
    for occurrence in occurrences:
        for edit in edits:
            if edit.segment_index != occurrence.segment_index or edit.is_whole_segment:
                continue
            if any(
                boundary is not None
                and occurrence.char_start < boundary < occurrence.char_end
                for boundary in (edit.char_start, edit.char_end)
            ):
                raise TranscriptCorrectionInvalidOccurrenceError(
                    reason="crosses_speaker_boundary",
                    context={
                        "segment_index": occurrence.segment_index,
                        "char_start": occurrence.char_start,
                        "char_end": occurrence.char_end,
                    },
                )


def nameable_labels(
    segments: Sequence[Mapping[str, Any]],
    speaker_edits: Sequence[TranscriptSpeakerEdit],
) -> set[str]:
    """Every stored segment label, and every label the edits assign."""
    labels = {label for segment in segments if (label := _segment_speaker(segment))}
    labels.update(edit.speaker for edit in speaker_edits if edit.speaker)
    return labels


def normalize_speaker_names(
    names: Mapping[str, Optional[str]],
    *,
    segments: Sequence[Mapping[str, Any]],
    speaker_edits: Sequence[TranscriptSpeakerEdit],
) -> dict[str, Optional[str]]:
    """Trimmed names for labels the transcript has; an empty name is None."""
    if len(names) > MAX_SPEAKER_NAMES:
        raise TranscriptSpeakerEditInvalidError(
            reason="too_many_speaker_names",
            context={
                "speaker_name_count": len(names),
                "max_speaker_names": MAX_SPEAKER_NAMES,
            },
        )
    labels = nameable_labels(segments, speaker_edits)
    normalized: dict[str, Optional[str]] = {}
    for label, raw_name in names.items():
        if not SPEAKER_LABEL_RE.fullmatch(label) or label not in labels:
            raise TranscriptSpeakerEditInvalidError(
                reason="unknown_speaker_label", context={"label": label}
            )
        name = (raw_name or "").strip() or None
        if name is not None and (len(name) > NAME_MAX_CHARS or "\n" in name):
            raise TranscriptSpeakerEditInvalidError(
                reason="invalid_speaker_name",
                context={"label": label, "max_chars": NAME_MAX_CHARS},
            )
        normalized[label] = name
    return normalized


def _applicable(
    text: str,
    occurrences: Sequence[TranscriptCorrectionOccurrence],
    skipped: list[TranscriptCorrectionOccurrence],
) -> list[TranscriptCorrectionOccurrence]:
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
    boundary: int, applicable: Sequence[TranscriptCorrectionOccurrence]
) -> int:
    """A raw-text offset in corrected-text space (monotone, total)."""
    delta = 0
    for occurrence in applicable:
        if occurrence.char_end <= boundary:
            delta += len(occurrence.corrected) - (
                occurrence.char_end - occurrence.char_start
            )
        elif occurrence.char_start < boundary:
            inside = min(boundary - occurrence.char_start, len(occurrence.corrected))
            return occurrence.char_start + delta + inside
        else:
            break
    return boundary + delta


def _speaker_runs(
    raw_text: str,
    stored_speaker: Optional[str],
    spans: Sequence[TranscriptSpeakerEdit],
    applicable: Sequence[TranscriptCorrectionOccurrence],
    skipped: list[TranscriptSpeakerEdit],
) -> list[dict[str, Any]]:
    raw_runs: list[tuple[int, int, Optional[str], Optional[str]]] = []
    cursor = 0
    for edit in sorted(spans, key=lambda item: item.char_start or 0):
        start, end = edit.char_start or 0, edit.char_end or 0
        if start < cursor:
            skipped.append(edit)
            continue
        if cursor < start:
            raw_runs.append((cursor, start, stored_speaker, None))
        raw_runs.append((start, end, edit.speaker, edit.decision))
        cursor = end
    if cursor < len(raw_text):
        raw_runs.append((cursor, len(raw_text), stored_speaker, None))
    merged: list[dict[str, Any]] = []
    for raw_start, raw_end, speaker, decision in raw_runs:
        start = _map_raw_offset(raw_start, applicable)
        end = _map_raw_offset(raw_end, applicable)
        if start >= end:
            continue
        if (
            merged
            and merged[-1]["speaker"] == speaker
            and merged[-1].get("decision") == decision
        ):
            merged[-1]["char_end"] = end
            continue
        merged.append(
            {
                "char_start": start,
                "char_end": end,
                "speaker": speaker,
                "decision": decision,
            }
        )
    return merged


def apply_corrections_and_speaker_edits(
    segments: Sequence[Mapping[str, Any]],
    occurrences: Sequence[TranscriptCorrectionOccurrence],
    speaker_edits: Sequence[TranscriptSpeakerEdit],
) -> tuple[
    list[dict[str, Any]],
    list[TranscriptCorrectionOccurrence],
    list[TranscriptSpeakerEdit],
]:
    """Corrected copies of ``segments`` plus whatever could not be applied.

    Text corrections replace right to left within a segment. A whole-segment
    edit replaces ``speaker``; span edits attach ``speaker_runs`` over the
    corrected text unless they collapse to one speaker. Mismatched anchors
    are skipped, never applied approximately.
    """
    skipped_occurrences: list[TranscriptCorrectionOccurrence] = []
    skipped_edits: list[TranscriptSpeakerEdit] = []
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
            skipped_edits.append(edit)
            continue
        edits_by_segment.setdefault(edit.segment_index, []).append(edit)

    corrected = [dict(segment) for segment in segments]
    for segment_index in sorted(set(occurrences_by_segment) | set(edits_by_segment)):
        raw_text = _segment_text(segments[segment_index])
        stored_speaker = _segment_speaker(segments[segment_index])
        applicable = _applicable(
            raw_text, occurrences_by_segment.get(segment_index, []), skipped_occurrences
        )
        text = raw_text
        for occurrence in reversed(applicable):
            text = (
                text[: occurrence.char_start]
                + occurrence.corrected
                + text[occurrence.char_end :]
            )
        if segment_index in occurrences_by_segment:
            corrected[segment_index]["text"] = text

        anchored_edits: list[TranscriptSpeakerEdit] = []
        for edit in sort_speaker_edits(edits_by_segment.get(segment_index, [])):
            anchored = edit.original_speaker == stored_speaker
            if anchored and not edit.is_whole_segment:
                anchored = (
                    edit.char_start is not None
                    and edit.char_end is not None
                    and 0 <= edit.char_start < edit.char_end <= len(raw_text)
                    and raw_text[edit.char_start : edit.char_end] == edit.original
                )
            (anchored_edits if anchored else skipped_edits).append(edit)
        wholes = [edit for edit in anchored_edits if edit.is_whole_segment]
        spans = [edit for edit in anchored_edits if not edit.is_whole_segment]
        if wholes:
            corrected[segment_index]["speaker"] = wholes[0].speaker
            corrected[segment_index]["speaker_decision"] = wholes[0].as_json()
            skipped_edits.extend(wholes[1:])
            skipped_edits.extend(spans)
        elif spans:
            runs = _speaker_runs(
                raw_text, stored_speaker, spans, applicable, skipped_edits
            )
            if len(runs) == 1:
                corrected[segment_index]["speaker"] = runs[0]["speaker"]
                corrected[segment_index]["speaker_decision"] = runs[0]
            elif runs:
                corrected[segment_index]["speaker_runs"] = runs
    return corrected, skipped_occurrences, skipped_edits


def render_corrected_transcript(
    segments: Sequence[Mapping[str, Any]],
    occurrences: Sequence[TranscriptCorrectionOccurrence],
    speaker_edits: Sequence[TranscriptSpeakerEdit],
    names: Mapping[str, Optional[str]] | None,
) -> str:
    """The transcript as a reader wants it: corrections and speaker edits
    applied, names in place of labels. A segment split between speakers
    renders one line per run."""
    corrected, _, _ = apply_corrections_and_speaker_edits(
        segments, occurrences, speaker_edits
    )
    lines: list[dict[str, Any]] = []
    for segment in corrected:
        runs = cast(list[dict[str, Any]] | None, segment.get("speaker_runs"))
        if not runs:
            lines.append(segment)
            continue
        text = _segment_text(segment)
        for run in runs:
            lines.append(
                {
                    **segment,
                    "speaker": run.get("speaker"),
                    "text": text[int(run["char_start"]) : int(run["char_end"])].strip(),
                }
            )
    return render_segments(lines, names)

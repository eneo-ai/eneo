"""One recording in several files: speaker labels on the recording's timeline.

A recorder that cuts a meeting into parts marks them as one recording. Their
speakers are labelled once on the joined audio, so one voice keeps one label,
and the result is split back into per-part transcripts whose times are
relative to each part, which is what the stored transcript contract and the
player expect.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from itertools import accumulate
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from uuid import UUID

from eneo.files.transcriber import TranscribedAudio
from eneo.flows.domain.speaker_labels import render_segments
from eneo.flows.runtime.audio_spool import SpooledAudio
from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
    EmptyTranscriptionInterval,
    TranscriptSegment,
    TranscriptWord,
)

if TYPE_CHECKING:
    from eneo.model_providers.domain.provider_call_observer import (
        ProviderCallObserver,
    )
    from eneo.transcription_models.domain.transcription_model import (
        TranscriptionModel,
    )

# Chunk windows are sums of measured cuts of the same decoded audio (no drift
# on a 21 min recording), so only float noise separates them from the part.
WINDOW_TOLERANCE_SECONDS = 0.05


class RecordingSplitError(ValueError):
    """The labelled recording cannot be returned to its parts faithfully."""


@dataclass(frozen=True, slots=True)
class PartBounds:
    """A part's decoded span on the recording's timeline, in seconds."""

    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass(frozen=True, slots=True)
class RecordingAudio:
    """The parts of one recording, each spooled, and their joined decode."""

    parts: tuple[SpooledAudio, ...]
    file_ids: tuple[UUID, ...]
    joined: SpooledAudio
    bounds: tuple[PartBounds, ...]


@runtime_checkable
class RecordingTranscriber(Protocol):
    """An engine that labels speakers can label a whole recording at once."""

    async def transcribe_recording(
        self,
        recording: RecordingAudio,
        transcription_model: "TranscriptionModel",
        *,
        language: str | None,
        observer: "ProviderCallObserver | None",
        max_speakers: int | None,
    ) -> TranscribedAudio:
        """The recording's labelled transcript on its own timeline."""
        ...


def part_bounds(durations: Sequence[float]) -> tuple[PartBounds, ...]:
    """Consecutive spans from the parts' decoded lengths."""
    return tuple(
        PartBounds(start=start, duration=duration)
        for start, duration in zip(accumulate(durations, initial=0.0), durations)
    )


def join_part_windows(
    parts: Sequence[TranscribedAudio], bounds: Sequence[PartBounds]
) -> TranscribedAudio:
    """The parts' own transcripts as one, their chunk windows placed on the
    recording's timeline, ready for one speaker-labelling call."""
    windows: list[TranscriptSegment] = []
    empty: list[EmptyTranscriptionInterval] = []
    for part, bound in zip(parts, bounds, strict=True):
        for window in part.segments or ():
            if window.start < -WINDOW_TOLERANCE_SECONDS or (
                window.end > bound.duration + WINDOW_TOLERANCE_SECONDS
            ):
                raise RecordingSplitError(
                    "A transcribed window lies outside its part's decoded audio."
                )
            windows.append(
                replace(
                    window,
                    start=bound.start + max(0.0, window.start),
                    end=bound.start + min(bound.duration, window.end),
                )
            )
        empty.extend(
            replace(
                interval,
                start=bound.start + interval.start,
                end=bound.start + min(bound.duration, interval.end),
            )
            for interval in part.empty_intervals
        )
    return TranscribedAudio(
        text="\n\n".join(part.text.strip() for part in parts if part.text.strip()),
        duration_seconds=bounds[-1].end,
        segments=tuple(windows),
        empty_intervals=tuple(empty),
    )


def split_recording(
    labelled: TranscribedAudio, bounds: Sequence[PartBounds]
) -> list[TranscribedAudio]:
    """Per-part transcripts, times relative to each part, labels unchanged.

    A segment inside one part moves there whole. One across a boundary is
    split by its words, which must spell all of its text; a word belongs to the
    part its start falls in, so a word spoken across a seam stays whole.
    """
    if labelled.transcript_segments is None and labelled.text.strip():
        raise RecordingSplitError(
            "The labelled recording came back without segments to place in its parts."
        )
    _check_times(labelled, bounds[-1].end)
    starts = [bound.start for bound in bounds]

    def part_of(time: float) -> int:
        return max(0, bisect_right(starts, time) - 1)

    def local(time: float, index: int) -> float:
        return min(max(time - bounds[index].start, 0.0), bounds[index].duration)

    segments: list[list[TranscriptSegment]] = [[] for _ in bounds]
    for segment in labelled.transcript_segments or ():
        for index, piece in _pieces(segment, part_of):
            segments[index].append(
                replace(
                    piece,
                    start=local(piece.start, index),
                    end=local(piece.end, index),
                    words=tuple(
                        replace(
                            word,
                            start=local(word.start, index),
                            end=local(word.end, index),
                        )
                        for word in piece.words
                    )
                    if piece.words
                    else piece.words,
                )
            )

    return [
        TranscribedAudio(
            text=render_segments(segments[index]),
            duration_seconds=bound.duration,
            transcript_segments=tuple(segments[index]),
            diarization=labelled.diarization,
            # One labelling call: its time is counted once, on the first part.
            diarization_elapsed_ms=labelled.diarization_elapsed_ms
            if index == 0
            else None,
            alignment=labelled.alignment,
            speaker_review=_review_in(labelled.speaker_review, bound),
            empty_intervals=tuple(
                replace(interval, start=span[0], end=span[1])
                for interval in labelled.empty_intervals
                if (span := _clip(interval.start, interval.end, bound)) is not None
            ),
        )
        for index, bound in enumerate(bounds)
    ]


def _pieces(
    segment: TranscriptSegment, part_of: Callable[[float], int]
) -> list[tuple[int, TranscriptSegment]]:
    first = part_of(segment.start)
    if part_of(max(segment.start, segment.end - WINDOW_TOLERANCE_SECONDS)) == first:
        return [(first, segment)]
    # Only words that spell the whole segment can say where each part of it was said.
    words = segment.words or ()
    if " ".join(segment.text.split()) != " ".join(word.word.strip() for word in words):
        raise RecordingSplitError(
            "A segment across a part boundary lacks word timings for all its text."
        )
    groups: list[tuple[int, list[TranscriptWord]]] = []
    for word in words:
        index = part_of(word.start)
        if groups and groups[-1][0] == index:
            groups[-1][1].append(word)
        else:
            groups.append((index, [word]))
    if len(groups) == 1:
        return [(groups[0][0], segment)]
    return [
        (
            index,
            replace(
                segment,
                text=" ".join(word.word.strip() for word in part_words),
                start=part_words[0].start,
                end=part_words[-1].end,
                words=tuple(part_words),
            ),
        )
        for index, part_words in groups
    ]


def _check_times(labelled: TranscribedAudio, duration: float) -> None:
    """Every time must be a real moment of the recording, and every word must
    lie in its segment in spoken order, before anything is routed by it."""
    overlaps = (labelled.speaker_review or {}).get("overlaps", [])
    spans = [(float(overlap["start"]), float(overlap["end"])) for overlap in overlaps]
    for segment in labelled.transcript_segments or ():
        spans.append((segment.start, segment.end))
        previous_start = segment.start - WINDOW_TOLERANCE_SECONDS
        for word in segment.words or ():
            if not (
                _within(word.start, word.end, segment.start, segment.end)
                and word.start >= previous_start
            ):
                raise RecordingSplitError(
                    "A word lies outside its segment or out of spoken order."
                )
            previous_start = word.start
            spans.append((word.start, word.end))
    if not all(_within(start, end, 0.0, duration) for start, end in spans):
        raise RecordingSplitError(
            "The labelled recording has times outside the recording."
        )


def _within(start: float, end: float, low: float, high: float) -> bool:
    return (
        math.isfinite(start)
        and math.isfinite(end)
        and low - WINDOW_TOLERANCE_SECONDS <= start <= end
        and end <= high + WINDOW_TOLERANCE_SECONDS
    )


def _clip(start: float, end: float, bound: PartBounds) -> tuple[float, float] | None:
    clipped_start, clipped_end = max(start, bound.start), min(end, bound.end)
    if clipped_end <= clipped_start:
        return None
    return clipped_start - bound.start, clipped_end - bound.start


def _review_in(
    review: dict[str, Any] | None, bound: PartBounds
) -> dict[str, Any] | None:
    if review is None:
        return None
    overlaps = [
        {**overlap, "start": span[0], "end": span[1]}
        for overlap in review.get("overlaps", [])
        if (span := _clip(float(overlap["start"]), float(overlap["end"]), bound))
        is not None
    ]
    return {**review, "overlaps": overlaps}

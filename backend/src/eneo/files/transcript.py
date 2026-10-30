"""Transcript text placed in time, as transcription engines return it."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    """One recognized word with absolute timestamps (seconds from audio start).

    ``probability`` is the service's confidence in the word's placement when
    it reports one. Its meaning follows the result's ``alignment``: a decoder
    posterior for ``provider_words``, the forced-alignment score for
    ``forced``, where exactly ``0.0`` marks a word the aligner could not fit
    to the audio and spread evenly over its window instead.
    """

    word: str
    start: float
    end: float
    probability: float | None = None


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """A stretch of transcript with absolute timestamps (seconds from audio start).

    ``speaker`` is the diarization label (``SPEAKER_NN``) when a service
    assigned one; providers that only transcribe leave it ``None``.
    """

    text: str
    start: float
    end: float
    speaker: str | None = None
    # Word timings inside the segment, when the service produced them.
    words: tuple[TranscriptWord, ...] | None = None
    speaker_attribution: str | None = None
    overlap_ids: tuple[str, ...] = ()

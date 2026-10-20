"""Transcript text placed in time, as transcription engines return it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    """One recognized word with absolute timestamps (seconds from audio start)."""

    word: str
    start: float
    end: float
    probability: float | None = None


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """A stretch of transcript with absolute timestamps (seconds from audio start).

    ``speaker`` is the diarization label (``SPEAKER_NN``) when a service
    assigned one; a provider that only transcribes leaves it ``None``.
    """

    text: str
    start: float
    end: float
    speaker: str | None = None
    words: tuple[TranscriptWord, ...] | None = None

    def as_json(self, *, file_index: int = 0) -> dict[str, Any]:
        """The stored shape (``transcription.segments`` of a step result)."""
        return {
            "file_index": file_index,
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
            "text": self.text,
        }

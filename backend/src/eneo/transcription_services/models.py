"""Domain vocabulary for native transcription services."""

from __future__ import annotations

from enum import StrEnum


class TranscriptionOperation(StrEnum):
    """Work Eneo asks a native transcription service to do.

    A service may advertise more tasks (Vemsa also realigns corrected
    transcripts); Eneo neither sends those nor offers them as supported.
    """

    TRANSCRIBE = "transcribe"
    DIARIZE = "diarize"

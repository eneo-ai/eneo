"""Content-free evidence retained after a run's source file is reclaimed."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FlowRunInputReleaseReason(StrEnum):
    TRANSCRIPTION_AUDIO_AFTER_USE = "transcription_audio_after_use"


class FlowRunReleasedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    step_id: UUID
    file_id: UUID
    released_at: datetime
    reason: FlowRunInputReleaseReason

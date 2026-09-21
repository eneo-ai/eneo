"""Immutable transcription evidence and its independently bounded components."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TranscriptSourceOmissionReason(IntEnum):
    TOO_LARGE = 1
    NO_SEGMENTS = 2
    SEGMENTS_UNAVAILABLE = 3


class TranscriptSourceBounds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    segments_bytes: int = Field(ge=0)
    detail_bytes: int = Field(ge=0)
    words_bytes: int = Field(ge=0)
    segments_count: int = Field(ge=0)
    words_count: int = Field(ge=0)
    segments_omitted_reason: TranscriptSourceOmissionReason | None = None
    detail_omitted_reason: TranscriptSourceOmissionReason | None = None
    words_omitted_reason: TranscriptSourceOmissionReason | None = None


class TranscriptSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    segments: list[dict[str, Any]] | None
    speaker_review: dict[str, Any] | None
    source_hash: str | None = Field(min_length=64, max_length=64)
    bounds: TranscriptSourceBounds

    @model_validator(mode="after")
    def _segments_match_omission(self) -> TranscriptSource:
        if bool(self.segments) != (self.bounds.segments_omitted_reason is None):
            raise ValueError(
                "Usable transcript segments must match their omission state."
            )
        return self


class TranscriptSourceReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    run_id: UUID
    step_id: UUID
    attempt_no: int = Field(ge=1)
    source_hash: str | None = Field(min_length=64, max_length=64)
    bounds: TranscriptSourceBounds


class TranscriptSourceExportRow(TranscriptSource):
    id: UUID
    tenant_id: UUID
    flow_id: UUID
    run_id: UUID
    step_id: UUID
    attempt_no: int
    created_at: datetime


class TranscriptComponentOmissions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    detail: TranscriptSourceOmissionReason | None
    words: TranscriptSourceOmissionReason | None


class PresentTranscriptSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["present"] = "present"
    source: TranscriptSource
    component_omissions: TranscriptComponentOmissions


class OmittedTranscriptSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["omitted"] = "omitted"
    reason: TranscriptSourceOmissionReason
    bounds: TranscriptSourceBounds


class UnavailablePreRowTranscriptSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["unavailable_pre_row"] = "unavailable_pre_row"


TranscriptSourceState = Annotated[
    PresentTranscriptSource
    | OmittedTranscriptSource
    | UnavailablePreRowTranscriptSource,
    Field(discriminator="status"),
]


class MissingTranscriptSourceError(RuntimeError):
    def __init__(self, reference: TranscriptSourceReference):
        self.reference = reference
        super().__init__(
            "Referenced transcript source is missing "
            f"(run_id={reference.run_id}, step_id={reference.step_id}, "
            f"attempt_no={reference.attempt_no})."
        )


def transcript_source_reference(
    payload: dict[str, Any] | None,
) -> TranscriptSourceReference | None:
    if payload is None:
        return None
    if payload.get("schema_version") == "flow-step-attempt-input.v1":
        payload = payload.get("resolved_input")
    if not isinstance(payload, dict):
        return None
    transcription = payload.get("transcription")
    if not isinstance(transcription, dict) or "source" not in transcription:
        return None
    return TranscriptSourceReference.model_validate(transcription["source"])


def with_transcript_source_reference(
    payload: dict[str, Any] | None, reference: TranscriptSourceReference
) -> dict[str, Any]:
    result = dict(payload or {})
    result["transcription"] = {
        **result.get("transcription", {}),
        "source": reference.model_dump(mode="json"),
    }
    return result

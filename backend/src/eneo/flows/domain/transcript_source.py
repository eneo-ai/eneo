"""Immutable transcription evidence and its independently bounded components."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue


class TranscriptSourceOmissionReason(IntEnum):
    """Why a transcript source component was not stored, sent as its number:
    `1` TOO_LARGE (over its byte bound), `2` NO_SEGMENTS (the transcription
    produced no structured lines), `3` SEGMENTS_UNAVAILABLE (word timings
    without the lines they anchor to)."""

    TOO_LARGE = 1
    NO_SEGMENTS = 2
    SEGMENTS_UNAVAILABLE = 3

    @classmethod
    def __get_pydantic_json_schema__(
        cls, core_schema: Any, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler.resolve_ref_schema(handler(core_schema))
        # Names for the wire numbers, for generators that build named enums.
        json_schema["x-enum-varnames"] = [reason.name for reason in cls]
        return json_schema


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


def _require_segments_match_omission(
    *, has_segments: bool, bounds: TranscriptSourceBounds
) -> None:
    if has_segments != (bounds.segments_omitted_reason is None):
        raise ValueError("Usable transcript segments must match their omission state.")


class TranscriptSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    segments: list[dict[str, Any]] | None
    speaker_review: dict[str, Any] | None
    source_hash: str | None = Field(min_length=64, max_length=64)
    bounds: TranscriptSourceBounds

    @model_validator(mode="after")
    def _segments_match_omission(self) -> TranscriptSource:
        _require_segments_match_omission(
            has_segments=bool(self.segments), bounds=self.bounds
        )
        return self


class TranscriptSourceSlice(BaseModel):
    """One page of a stored source: ``segments`` are its lines from absolute
    index ``start`` on, ``total`` counts every line, and ``speaker_review`` is
    read only for the page at ``start`` 0 (None on every other page)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: int = Field(ge=0)
    total: int = Field(ge=0)
    segments: list[dict[str, Any]] | None
    speaker_review: dict[str, Any] | None
    source_hash: str | None = Field(min_length=64, max_length=64)
    bounds: TranscriptSourceBounds

    @model_validator(mode="after")
    def _segments_match_omission(self) -> TranscriptSourceSlice:
        # The whole source decides, not the page: a page past the end is
        # empty, and lines marked omitted are refused on every page.
        _require_segments_match_omission(
            has_segments=self.total > 0, bounds=self.bounds
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


class PresentTranscriptSourceSlice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["present"] = "present"
    page: TranscriptSourceSlice
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

TranscriptSourcePageState = Annotated[
    PresentTranscriptSourceSlice
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

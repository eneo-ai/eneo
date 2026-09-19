from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeAlias, cast
from uuid import UUID

from eneo.main.exceptions import TypedIOValidationException

OUTPUT_TEXT_OVERFLOW_KEY: Final = "text_overflow"
REJECTED_OUTPUT_KEY: Final = "rejected_output"
REJECTED_OUTPUT_TRUNCATED_KEY: Final = "rejected_output_truncated"
_OVERFLOW_FIELDS = frozenset(
    {"generated_file_ids", "inline_text_bytes", "full_text_bytes"}
)


class StepOutputMetadataError(ValueError):
    """Persisted step text metadata is incomplete or internally inconsistent."""


@dataclass(frozen=True)
class RejectedOutput:
    text: str
    truncated_by_runtime: bool


@dataclass(frozen=True, slots=True)
class RejectedCompletion:
    """A received completion whose output failed validation, not an I/O failure."""

    finish_reason: str | None
    provider_response_id: str | None


class StepOutputValidationException(TypedIOValidationException):
    def __init__(
        self,
        cause: TypedIOValidationException,
        *,
        rejected_completion: RejectedCompletion,
    ):
        super().__init__(str(cause), code=cause.code, context=cause.context)
        self.rejected_completion = rejected_completion
        self.input_payload_json = cause.input_payload_json
        self.effective_prompt = cause.effective_prompt
        self.contract_validation = cause.contract_validation


def utf8_prefix(text: str, *, max_bytes: int) -> str:
    return text.encode("utf-8")[: max(0, max_bytes)].decode("utf-8", errors="ignore")


def build_rejected_output_payload(
    text: str, *, max_inline_bytes: int
) -> dict[str, object]:
    return {
        REJECTED_OUTPUT_KEY: utf8_prefix(text, max_bytes=max_inline_bytes),
        REJECTED_OUTPUT_TRUNCATED_KEY: len(text.encode("utf-8")) > max_inline_bytes,
    }


def interpret_rejected_output(
    payload: Mapping[str, object] | None,
) -> RejectedOutput | None:
    if payload is None or REJECTED_OUTPUT_KEY not in payload:
        return None
    text = payload[REJECTED_OUTPUT_KEY]
    truncated = payload.get(REJECTED_OUTPUT_TRUNCATED_KEY)
    if not isinstance(text, str) or not isinstance(truncated, bool):
        return None
    return RejectedOutput(text=text, truncated_by_runtime=truncated)


@dataclass(frozen=True)
class InlineStepText:
    text: str


@dataclass(frozen=True)
class FileBackedStepText:
    preview: str
    file_id: UUID
    inline_text_bytes: int
    full_text_bytes: int


StepText: TypeAlias = InlineStepText | FileBackedStepText


def interpret_step_text(payload: Mapping[str, object] | None) -> StepText:
    if payload is None:
        raise StepOutputMetadataError("Persisted step output payload is missing.")
    text = payload.get("text")
    if not isinstance(text, str):
        raise StepOutputMetadataError("Persisted step output text must be a string.")
    if OUTPUT_TEXT_OVERFLOW_KEY not in payload:
        return InlineStepText(text=text)

    overflow = payload[OUTPUT_TEXT_OVERFLOW_KEY]
    if not isinstance(overflow, dict):
        raise StepOutputMetadataError(
            "Persisted text overflow metadata has an invalid shape."
        )
    overflow_fields = cast(dict[object, object], overflow)
    if len(overflow_fields) != len(_OVERFLOW_FIELDS) or any(
        field not in overflow_fields for field in _OVERFLOW_FIELDS
    ):
        raise StepOutputMetadataError(
            "Persisted text overflow metadata has an invalid shape."
        )
    raw_file_ids = overflow_fields["generated_file_ids"]
    if not isinstance(raw_file_ids, list):
        raise StepOutputMetadataError(
            "Persisted text overflow must reference exactly one file UUID."
        )
    file_ids = cast(list[object], raw_file_ids)
    if len(file_ids) != 1 or not isinstance(file_ids[0], str):
        raise StepOutputMetadataError(
            "Persisted text overflow must reference exactly one file UUID."
        )
    try:
        file_id = UUID(file_ids[0])
    except ValueError as exc:
        raise StepOutputMetadataError(
            "Persisted text overflow file id must be a UUID."
        ) from exc

    inline_text_bytes = overflow_fields["inline_text_bytes"]
    full_text_bytes = overflow_fields["full_text_bytes"]
    if type(inline_text_bytes) is not int or type(full_text_bytes) is not int:
        raise StepOutputMetadataError(
            "Persisted text overflow byte counts must be integers."
        )
    if inline_text_bytes != len(text.encode("utf-8")):
        raise StepOutputMetadataError(
            "Persisted text overflow preview byte count does not match the text."
        )
    if full_text_bytes <= inline_text_bytes:
        raise StepOutputMetadataError(
            "Persisted text overflow full byte count must exceed the preview."
        )
    return FileBackedStepText(
        preview=text,
        file_id=file_id,
        inline_text_bytes=inline_text_bytes,
        full_text_bytes=full_text_bytes,
    )


def build_text_overflow_metadata(
    *,
    file_ids: Sequence[UUID],
    preview: str,
    full_text: str,
) -> dict[str, object]:
    if len(file_ids) != 1:
        raise ValueError("Text overflow output must reference exactly one file.")
    inline_text_bytes = len(preview.encode("utf-8"))
    full_text_bytes = len(full_text.encode("utf-8"))
    if full_text_bytes <= inline_text_bytes:
        raise ValueError("Text overflow output must be larger than its preview.")
    return {
        "generated_file_ids": [str(file_ids[0])],
        "inline_text_bytes": inline_text_bytes,
        "full_text_bytes": full_text_bytes,
    }

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, TypeAlias, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.flows.flow_api_error_code import FlowApiErrorCode
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


class FileBackedStepText(BaseModel):
    """A bounded preview and the identity of its complete text artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["file_backed_step_text"] = "file_backed_step_text"
    preview: str
    file_id: UUID
    inline_text_bytes: int = Field(strict=True, ge=0)
    full_text_bytes: int = Field(strict=True, ge=1)
    checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_step_id: UUID | None = None
    source_attempt_no: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def _coherent_reference(self) -> FileBackedStepText:
        if self.inline_text_bytes != len(self.preview.encode("utf-8")):
            raise ValueError("Step text preview size does not match its bytes.")
        if self.inline_text_bytes >= self.full_text_bytes:
            raise ValueError("A file-backed preview must be smaller than the material.")
        if (self.source_step_id is None) != (self.source_attempt_no is None):
            raise ValueError(
                "Step text source identity requires both step and attempt."
            )
        return self


@dataclass(frozen=True)
class ResolvedStepMaterial:
    source_step_id: UUID
    source_attempt_no: int
    file_id: UUID
    checksum: str
    byte_size: int
    text: str


def build_step_material_aliases(
    *,
    materials: Sequence[ResolvedStepMaterial],
    max_inline_bytes: int,
) -> tuple[FileBackedStepText, ...]:
    if not materials:
        return ()
    aliases = tuple(
        FileBackedStepText(
            preview=(
                preview := utf8_prefix(
                    material.text, max_bytes=min(256, material.byte_size - 1)
                )
            ),
            inline_text_bytes=len(preview.encode("utf-8")),
            file_id=material.file_id,
            checksum=material.checksum,
            full_text_bytes=material.byte_size,
            source_step_id=material.source_step_id,
            source_attempt_no=material.source_attempt_no,
        )
        for material in materials
    )
    if (
        len(
            json.dumps(
                [alias.model_dump(mode="json") for alias in aliases],
                ensure_ascii=False,
            ).encode("utf-8")
        )
        > max_inline_bytes
    ):
        raise _alias_too_large()
    return aliases


def parse_step_text_aliases(value: object) -> tuple[FileBackedStepText, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        FileBackedStepText.model_validate(item) for item in cast(list[object], value)
    )


def _alias_too_large() -> TypedIOValidationException:
    return TypedIOValidationException(
        "The bounded material reference exceeds the inline storage ceiling.",
        code=FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value,
    )


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

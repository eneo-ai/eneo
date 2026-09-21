from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Final, Literal, TypeAlias, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_redaction import redact_string_with_reason
from eneo.main.exceptions import TypedIOValidationException

OUTPUT_TEXT_OVERFLOW_KEY: Final = "text_overflow"
REJECTED_OUTPUT_KEY: Final = "rejected_output"
REJECTED_OUTPUT_TRUNCATED_KEY: Final = "rejected_output_truncated"
_OVERFLOW_FIELDS = frozenset(
    {"generated_file_ids", "inline_text_bytes", "full_text_bytes"}
)


class StepOutputMetadataError(ValueError):
    """Persisted step text metadata is incomplete or internally inconsistent."""


class RejectedOutputEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tail: str
    observed_bytes: int | None = Field(ge=0)
    sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    sampling_status: Literal["complete", "sampled", "unavailable"]
    redaction_applied: bool = False


@dataclass(frozen=True)
class RejectedOutput:
    text: str
    truncated_by_runtime: bool
    evidence: RejectedOutputEvidence | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            REJECTED_OUTPUT_KEY: self.text,
            REJECTED_OUTPUT_TRUNCATED_KEY: self.truncated_by_runtime,
        }
        if self.evidence is not None:
            payload["rejection_evidence"] = self.evidence.model_dump(mode="json")
        return payload


@dataclass(frozen=True, slots=True)
class RejectedCompletion:
    """A received completion whose output failed validation, not an I/O failure."""

    finish_reason: str | None
    provider_response_id: str | None
    output: RejectedOutput | None = None


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
    return RejectedOutput(
        text=utf8_prefix(text, max_bytes=max_inline_bytes),
        truncated_by_runtime=len(text.encode("utf-8")) > max_inline_bytes,
    ).to_payload()


def sample_rejected_output(
    text: str | None,
    *,
    max_inline_bytes: int,
    observed_bytes: int | None = None,
    sha256: str | None = None,
) -> RejectedOutput | None:
    encoded = text.encode("utf-8") if text is not None else b""
    if observed_bytes is None and text is not None:
        observed_bytes = len(encoded)
    if sha256 is None and text is not None:
        sha256 = hashlib.sha256(encoded).hexdigest()
    redacted = redact_string_with_reason(text, key=None) if text is not None else None
    redaction_applied = redacted is not None and redacted.reason is not None
    if redacted is not None:
        encoded = redacted.value.encode("utf-8")
    # JSON escaping can triple a sample, so the budget is found by bisection on
    # the serialized envelope: at most log2(ceiling) serializations of a
    # payload no larger than one model output.
    lower, upper = 0, min(len(encoded), max_inline_bytes)
    retained = None
    while lower <= upper:
        budget = (lower + upper) // 2
        complete = len(encoded) <= budget
        sampled = not complete or (
            observed_bytes is not None and observed_bytes > max_inline_bytes
        )
        head = encoded if complete else encoded[: budget // 2]
        tail = b"" if complete or budget == 0 else encoded[-(budget - budget // 2) :]
        output = RejectedOutput(
            text=head.decode("utf-8", errors="ignore"),
            truncated_by_runtime=sampled,
            evidence=RejectedOutputEvidence(
                tail=tail.decode("utf-8", errors="ignore"),
                observed_bytes=observed_bytes,
                sha256=sha256,
                redaction_applied=redaction_applied,
                sampling_status=(
                    "unavailable"
                    if text is None
                    else "complete"
                    if not sampled
                    else "sampled"
                ),
            ),
        )
        # The existing inline ceiling also covers metadata and JSON escaping.
        excess = (
            len(json.dumps(output.to_payload(), ensure_ascii=False).encode("utf-8"))
            - max_inline_bytes
        )
        if excess <= 0:
            retained = output
            lower = budget + 1
        else:
            upper = budget - 1
    return retained


def interpret_rejected_output(
    payload: Mapping[str, object] | None,
) -> RejectedOutput | None:
    if payload is None or REJECTED_OUTPUT_KEY not in payload:
        return None
    text = payload[REJECTED_OUTPUT_KEY]
    truncated = payload.get(REJECTED_OUTPUT_TRUNCATED_KEY)
    if not isinstance(text, str) or not isinstance(truncated, bool):
        return None
    evidence = None
    if "rejection_evidence" in payload:
        try:
            evidence = RejectedOutputEvidence.model_validate(
                payload["rejection_evidence"]
            )
        except ValidationError:
            return None
    return RejectedOutput(text=text, truncated_by_runtime=truncated, evidence=evidence)


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


FlowResolvedInputJsonPathSegment: TypeAlias = (
    Annotated[str, Field(strict=True, min_length=1)]
    | Annotated[int, Field(strict=True, ge=0)]
)


class FlowResolvedInputJsonPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["json_path"]
    path: tuple[FlowResolvedInputJsonPathSegment, ...]


class FlowResolvedInputHashedSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    encoding: Literal["utf8", "canonical_json"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(strict=True, ge=0)


class InlineStepTextReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["inline_step_text"] = "inline_step_text"
    source_step_id: UUID
    source_attempt_no: int = Field(strict=True, ge=1)
    selector: FlowResolvedInputJsonPath
    selection: FlowResolvedInputHashedSelection

    @model_validator(mode="after")
    def _text_encoding(self) -> InlineStepTextReference:
        if self.selection.encoding != "utf8":
            raise ValueError("Inline material must select UTF-8 text.")
        return self


StepMaterialReference: TypeAlias = Annotated[
    FileBackedStepText | InlineStepTextReference, Field(discriminator="kind")
]
StepMaterialIdentity: TypeAlias = (
    UUID | tuple[UUID, int, tuple[FlowResolvedInputJsonPathSegment, ...]]
)
_MATERIAL_REFERENCE = TypeAdapter[StepMaterialReference](StepMaterialReference)


def material_reference_identity(
    reference: StepMaterialReference,
) -> StepMaterialIdentity:
    if isinstance(reference, FileBackedStepText):
        return reference.file_id
    return (
        reference.source_step_id,
        reference.source_attempt_no,
        reference.selector.path,
    )


def inline_text_reference(
    *,
    source_step_id: UUID,
    source_attempt_no: int,
    text: str,
    selector_path: tuple[FlowResolvedInputJsonPathSegment, ...] = ("output", "text"),
) -> InlineStepTextReference:
    encoded = text.encode("utf-8")
    return InlineStepTextReference(
        source_step_id=source_step_id,
        source_attempt_no=source_attempt_no,
        selector=FlowResolvedInputJsonPath(kind="json_path", path=selector_path),
        selection=FlowResolvedInputHashedSelection(
            encoding="utf8",
            sha256=hashlib.sha256(encoded).hexdigest(),
            byte_size=len(encoded),
        ),
    )


class InlineTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["inline_transcript"] = "inline_transcript"
    text: str
    reference: InlineStepTextReference

    @model_validator(mode="after")
    def _verified_text(self) -> InlineTranscript:
        verify_inline_text(self.reference, self.text)
        return self


def verify_inline_text(reference: InlineStepTextReference, text: str) -> None:
    encoded = text.encode("utf-8")
    if (
        len(encoded) != reference.selection.byte_size
        or hashlib.sha256(encoded).hexdigest() != reference.selection.sha256
    ):
        raise StepOutputMetadataError("Inline text does not match its selected bytes.")


def inline_transcript(
    *,
    text: str,
    source_step_id: UUID,
    source_attempt_no: int,
    selector_path: tuple[FlowResolvedInputJsonPathSegment, ...] = ("input", "text"),
) -> InlineTranscript:
    return InlineTranscript(
        text=text,
        reference=inline_text_reference(
            source_step_id=source_step_id,
            source_attempt_no=source_attempt_no,
            text=text,
            selector_path=selector_path,
        ),
    )


def inline_output_reference(
    payload: Mapping[str, object],
    *,
    source_step_id: UUID,
    source_attempt_no: int,
) -> InlineStepTextReference:
    text = payload.get("text")
    if not isinstance(text, str):
        raise StepOutputMetadataError("Inline output must contain text.")
    identity = inline_output_identity(
        payload, source_step_id=source_step_id, source_attempt_no=source_attempt_no
    )
    return inline_text_reference(
        source_step_id=source_step_id,
        source_attempt_no=source_attempt_no,
        text=text,
        selector_path=identity[2],
    )


def inline_output_identity(
    payload: Mapping[str, object],
    *,
    source_step_id: UUID,
    source_attempt_no: int,
) -> tuple[UUID, int, tuple[FlowResolvedInputJsonPathSegment, ...]]:
    selector = (
        FlowResolvedInputJsonPath.model_validate(payload["text_source_selector"])
        if "text_source_selector" in payload
        else FlowResolvedInputJsonPath(kind="json_path", path=("output", "text"))
    )
    return source_step_id, source_attempt_no, selector.path


@dataclass(frozen=True)
class ResolvedStepMaterial:
    source_step_id: UUID
    source_attempt_no: int
    file_id: UUID | None
    checksum: str
    byte_size: int
    text: str
    selector_path: tuple[FlowResolvedInputJsonPathSegment, ...] = ("output", "text")

    @classmethod
    def from_inline(
        cls, *, reference: InlineStepTextReference, text: str
    ) -> ResolvedStepMaterial:
        verify_inline_text(reference, text)
        return cls(
            source_step_id=reference.source_step_id,
            source_attempt_no=reference.source_attempt_no,
            file_id=None,
            checksum=reference.selection.sha256,
            byte_size=reference.selection.byte_size,
            text=text,
            selector_path=reference.selector.path,
        )

    @property
    def reference(self) -> StepMaterialReference:
        if self.file_id is None:
            return InlineStepTextReference(
                source_step_id=self.source_step_id,
                source_attempt_no=self.source_attempt_no,
                selector=FlowResolvedInputJsonPath(
                    kind="json_path", path=self.selector_path
                ),
                selection=FlowResolvedInputHashedSelection(
                    encoding="utf8", sha256=self.checksum, byte_size=self.byte_size
                ),
            )
        preview = utf8_prefix(self.text, max_bytes=min(256, self.byte_size - 1))
        return FileBackedStepText(
            preview=preview,
            inline_text_bytes=len(preview.encode("utf-8")),
            file_id=self.file_id,
            checksum=self.checksum,
            full_text_bytes=self.byte_size,
            source_step_id=self.source_step_id,
            source_attempt_no=self.source_attempt_no,
        )

    @property
    def identity(self) -> StepMaterialIdentity:
        if self.file_id is not None:
            return self.file_id
        return self.source_step_id, self.source_attempt_no, self.selector_path


def build_step_material_aliases(
    *,
    materials: Sequence[ResolvedStepMaterial],
    max_inline_bytes: int,
) -> tuple[StepMaterialReference, ...]:
    if not materials:
        return ()
    aliases = tuple(material.reference for material in materials)
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


def parse_step_text_aliases(value: object) -> tuple[StepMaterialReference, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        _MATERIAL_REFERENCE.validate_python(item) for item in cast(list[object], value)
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

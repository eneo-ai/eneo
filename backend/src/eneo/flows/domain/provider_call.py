from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, get_args
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from eneo.flows.flow_run_provenance import (
    MappedProviderCallProvenance,
    TokenCountSource,
)

PROVIDER_REQUEST_HASH_PATTERN = r"^[0-9a-f]{64}$"
PROVIDER_REQUEST_HASH_DESCRIPTION = (
    "SHA-256 of Eneo's canonical non-streaming request intent at the provider "
    "adapter boundary: requested model, provider, ordered messages, and "
    "allowlisted controls. Provider-side parameter dropping or transport "
    "enrichment is not reflected."
)

PROVIDER_CALL_EVIDENCE_PAGE_EXAMPLE: dict[str, JsonValue] = {
    "items": [
        {
            "event_id": "00000000-0000-0000-0000-000000000801",
            "attempt_id": "00000000-0000-0000-0000-000000000701",
            "step_id": "00000000-0000-0000-0000-000000000601",
            "step_order": 1,
            "attempt_no": 1,
            "ordinal": 1,
            "status": "completed",
            "request_schema_version": 2,
            "provider_request_hash": "a" * 64,
            "requested_model": "gpt-5-mini",
            "provider": "openai",
            "response_format": "json_schema",
            "requested_capabilities": ["structured_output"],
            "call_reason": "initial",
            "mapped_execution_mode": "per_item",
            "mapped_item_index": 1,
            "mapped_source_id": "source-file-1",
            "response_model": "gpt-5-mini-2025-08-07",
            "provider_response_id": "resp_01HZXAMPLE",
            "num_tokens_input": 824,
            "num_tokens_output": 167,
            "input_source": "provider",
            "output_source": "provider",
            "requested_at": "2026-07-26T12:00:00Z",
            "finished_at": "2026-07-26T12:00:01Z",
        }
    ],
    "count": 1,
    "total_count": 2,
    "has_more": True,
    "next_after_event_id": "00000000-0000-0000-0000-000000000801",
}


class ProviderCallStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    REJECTED = "rejected"
    OUTCOME_UNKNOWN = "outcome_unknown"


class ProviderCallResponseFormat(str, Enum):
    NONE = "none"
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"
    OTHER = "other"


class ProviderCallRequestedCapability(str, Enum):
    IMAGE_INPUT = "image_input"
    REASONING = "reasoning"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"


def _require_canonical_requested_capabilities(
    capabilities: tuple[ProviderCallRequestedCapability, ...],
) -> tuple[ProviderCallRequestedCapability, ...]:
    canonical = tuple(sorted(set(capabilities)))
    if capabilities != canonical:
        raise ValueError("Requested provider capabilities must be sorted and unique.")
    return capabilities


ProviderCallRequestedCapabilities = Annotated[
    tuple[ProviderCallRequestedCapability, ...],
    AfterValidator(_require_canonical_requested_capabilities),
]


class ProviderCallReason(str, Enum):
    INITIAL = "initial"
    RESPONSE_FORMAT_FALLBACK = "response_format_fallback"
    TOOL_ROUND = "tool_round"


class ProviderCallRejectionReason(str, Enum):
    RESPONSE_FORMAT_REJECTED = "response_format_rejected"
    PROVIDER_REJECTED = "provider_rejected"


class ProviderCallUnknownReason(str, Enum):
    REQUEST_TIMEOUT = "request_timeout"
    RUN_CANCELLED = "run_cancelled"
    WORKER_INTERRUPTED = "worker_interrupted"
    PROVIDER_ERROR = "provider_error"
    REQUEST_CANCELLED = "request_cancelled"
    STALE_STARTED = "stale_started"


class ProviderCallRequest(BaseModel):
    """Credential-free identity facts for one outbound provider request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_schema_version: Literal[2] = 2
    provider_request_hash: str = Field(
        pattern=PROVIDER_REQUEST_HASH_PATTERN,
        description=PROVIDER_REQUEST_HASH_DESCRIPTION,
    )
    requested_model: str = Field(min_length=1, max_length=255)
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    response_format: ProviderCallResponseFormat = ProviderCallResponseFormat.NONE
    requested_capabilities: ProviderCallRequestedCapabilities
    call_reason: ProviderCallReason = ProviderCallReason.INITIAL
    mapped_call: MappedProviderCallProvenance | None = None

    @model_validator(mode="after")
    def validate_capabilities_match_response_format(self) -> "ProviderCallRequest":
        structured_output_requested = (
            ProviderCallRequestedCapability.STRUCTURED_OUTPUT
            in self.requested_capabilities
        )
        structured_response_format = self.response_format in {
            ProviderCallResponseFormat.JSON_OBJECT,
            ProviderCallResponseFormat.JSON_SCHEMA,
        }
        if structured_output_requested != structured_response_format:
            raise ValueError(
                "Structured-output capability and response format must agree."
            )
        return self


class ProviderCallCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    response_model: str | None = Field(default=None, max_length=255)
    provider_response_id: str | None = Field(default=None, max_length=512)
    num_tokens_input: int | None = Field(default=None, ge=0)
    num_tokens_output: int | None = Field(default=None, ge=0)
    input_source: TokenCountSource
    output_source: TokenCountSource

    @model_validator(mode="after")
    def validate_token_sources(self) -> "ProviderCallCompletion":
        for count, source, dimension in (
            (self.num_tokens_input, self.input_source, "input"),
            (self.num_tokens_output, self.output_source, "output"),
        ):
            if (count is None) != (source == "not_reported"):
                raise ValueError(
                    f"Provider call {dimension} count must be absent exactly "
                    "when its source is not_reported."
                )
        return self


class ProviderCall(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    flow_step_attempt_id: UUID
    ordinal: int = Field(ge=1)
    status: ProviderCallStatus
    request_schema_version: Literal[2]
    provider_request_hash: str = Field(
        pattern=PROVIDER_REQUEST_HASH_PATTERN,
        description=PROVIDER_REQUEST_HASH_DESCRIPTION,
    )
    requested_model: str = Field(min_length=1)
    provider: str | None = Field(min_length=1)
    response_format: ProviderCallResponseFormat
    requested_capabilities: ProviderCallRequestedCapabilities
    call_reason: ProviderCallReason
    mapped_execution_mode: Literal["per_item", "per_source"] | None
    mapped_item_index: int | None = Field(default=None, ge=1)
    mapped_source_index: int | None = Field(default=None, ge=1)
    mapped_source_id: str | None
    response_model: str | None
    provider_response_id: str | None
    num_tokens_input: int | None = Field(default=None, ge=0)
    num_tokens_output: int | None = Field(default=None, ge=0)
    input_source: TokenCountSource | None
    output_source: TokenCountSource | None
    outcome_reason: ProviderCallRejectionReason | ProviderCallUnknownReason | None
    requested_at: datetime
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_mapped_context(self) -> "ProviderCall":
        if self.mapped_execution_mode == "per_item":
            if self.mapped_item_index is None or self.mapped_source_index is not None:
                raise ValueError(
                    "per_item provider calls require only mapped_item_index"
                )
        elif self.mapped_execution_mode == "per_source":
            if self.mapped_source_index is None or self.mapped_item_index is not None:
                raise ValueError(
                    "per_source provider calls require only mapped_source_index"
                )
        elif (
            self.mapped_item_index is not None
            or self.mapped_source_index is not None
            or self.mapped_source_id is not None
        ):
            raise ValueError("unmapped provider calls cannot carry mapped context")
        return self


class ProviderCallEvidence(BaseModel):
    """Run-scoped ordered read model for one provider-call lifecycle row."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    attempt_id: UUID
    step_id: UUID
    step_order: int = Field(ge=1)
    attempt_no: int = Field(ge=1)
    ordinal: int = Field(ge=1)
    status: ProviderCallStatus
    request_schema_version: Literal[2]
    provider_request_hash: str = Field(
        pattern=PROVIDER_REQUEST_HASH_PATTERN,
        description=PROVIDER_REQUEST_HASH_DESCRIPTION,
    )
    requested_model: str = Field(min_length=1)
    provider: str | None = Field(min_length=1)
    response_format: ProviderCallResponseFormat
    requested_capabilities: ProviderCallRequestedCapabilities = Field(
        description=(
            "Sorted request intent for capabilities Eneo attempted in this provider "
            "request. [] means none were requested. This is not proof of provider "
            "support, acceptance, or completion."
        )
    )
    call_reason: ProviderCallReason
    mapped_execution_mode: Literal["per_item", "per_source"] | None
    mapped_item_index: int | None = Field(default=None, ge=1)
    mapped_source_index: int | None = Field(default=None, ge=1)
    mapped_source_id: str | None
    response_model: str | None
    provider_response_id: str | None
    num_tokens_input: int | None = Field(default=None, ge=0)
    num_tokens_output: int | None = Field(default=None, ge=0)
    input_source: TokenCountSource | None
    output_source: TokenCountSource | None
    outcome_reason: ProviderCallRejectionReason | ProviderCallUnknownReason | None = (
        None
    )
    requested_at: datetime
    finished_at: datetime | None


class ProviderCallEvidencePage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={"example": PROVIDER_CALL_EVIDENCE_PAGE_EXAMPLE},
    )

    items: tuple[ProviderCallEvidence, ...]
    count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    has_more: bool
    next_after_event_id: UUID | None

    @model_validator(mode="after")
    def validate_page_shape(self) -> "ProviderCallEvidencePage":
        if self.count != len(self.items):
            raise ValueError("Provider-call page count must match items.")
        if self.has_more != (self.next_after_event_id is not None):
            raise ValueError(
                "Provider-call page cursor must be present exactly when more rows exist."
            )
        return self


PROVIDER_CALL_STATUS_VALUES = tuple(item.value for item in ProviderCallStatus)
PROVIDER_CALL_RESPONSE_FORMAT_VALUES = tuple(
    item.value for item in ProviderCallResponseFormat
)
PROVIDER_CALL_REQUESTED_CAPABILITY_VALUES = tuple(
    item.value for item in ProviderCallRequestedCapability
)
PROVIDER_CALL_REASON_VALUES = tuple(item.value for item in ProviderCallReason)
PROVIDER_CALL_REJECTION_REASON_VALUES = tuple(
    item.value for item in ProviderCallRejectionReason
)
PROVIDER_CALL_UNKNOWN_REASON_VALUES = tuple(
    item.value for item in ProviderCallUnknownReason
)
PROVIDER_CALL_TOKEN_SOURCE_VALUES = get_args(TokenCountSource)

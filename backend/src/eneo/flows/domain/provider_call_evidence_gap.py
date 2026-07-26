from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ProviderCallPersistenceOutcome = Literal[
    "started",
    "completed",
    "response_format_rejected",
    "provider_rejected",
    "request_timeout",
    "run_cancelled",
    "worker_interrupted",
    "provider_error",
    "request_cancelled",
    "stale_started",
]


class ProviderCallEvidenceGap(BaseModel):
    """Secret-free facts retained when an evidence transaction cannot commit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: UUID | None = None
    ordinal: int | None = Field(default=None, ge=1)
    provider_request_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    provider_response_id: str | None = Field(default=None, max_length=512)
    outcome: ProviderCallPersistenceOutcome
    num_tokens_input: int | None = Field(default=None, ge=0)
    num_tokens_output: int | None = Field(default=None, ge=0)

from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.model_providers.domain.connection_check import (
    ConnectionCheckError,
    ConnectionCheckStatus,
)

_KEY_EXPIRES_ON_DESCRIPTION = (
    "Date the API key stops working, entered by an admin so the key can be "
    "renewed in time. Few providers report key expiry through their API, so "
    "Eneo stores this date as given and does not verify it."
)

HeaderEncoding = Literal["percent", "none"]
HeaderOnMissing = Literal["omit", "fallback", "fail"]


class OutboundHeaderInput(BaseModel):
    """One outbound header in a create or update.

    Write convention (the list replaces the stored one):
    an entry with an `id` and no `value` keeps the stored value; with a `value`,
    replaces it; an entry without an `id` is new and must supply `value`; a
    stored header whose `id` is absent is deleted. `fallback` follows the same
    rule, and `null` clears it.
    """

    id: Optional[str] = Field(
        default=None, description="Server-assigned id; omit for a new header"
    )
    name: str = Field(..., description="HTTP header name (RFC 9110 token)")
    value: Optional[str] = Field(
        default=None,
        description="Literal text and {{token}} dynamic values. Omit to keep the stored value.",
    )
    encoding: HeaderEncoding = Field(
        default="percent",
        description="percent: percent-encode the resolved value (receiver unquotes); none: send byte-exact (printable ASCII only)",
    )
    secret: bool = Field(
        False, description="Encrypt at rest and never return the value"
    )
    on_missing: HeaderOnMissing = Field(
        default="omit",
        description="What to do when a dynamic value has no value for the user",
    )
    fallback: Optional[str] = Field(
        default=None,
        description="Literal sent when on_missing is 'fallback'. Omit to keep the stored one.",
    )


class OutboundHeaderPublic(BaseModel):
    """A configured header. A secret header's value and fallback are masked."""

    id: str
    name: str
    value: str
    encoding: HeaderEncoding
    secret: bool
    on_missing: HeaderOnMissing
    fallback: Optional[str] = None
    classification: Optional[Literal["identifying", "organisational"]] = Field(
        default=None,
        description=(
            "The most sensitive kind of dynamic value the header sends; "
            "known for a secret header although its value is masked"
        ),
    )


class DynamicValuePublic(BaseModel):
    token: str = Field(..., description="Used in a header value as {{token}}")
    source: Literal["scim_enterprise", "external_id"]
    attribute: str = Field(..., description="The provisioned attribute the token reads")
    classification: Literal["identifying", "organisational"]


class OutboundHeaderOptions(BaseModel):
    """Server-owned metadata for the outbound header editor."""

    dynamic_values: list[DynamicValuePublic]
    supported_provider_types: list[str]
    max_headers: int


class OutboundHeaderPreviewRequest(BaseModel):
    user_id: UUID = Field(..., description="The tenant user to resolve the headers for")


class OutboundHeaderPreviewItem(BaseModel):
    name: str
    secret: bool
    state: Literal["resolved", "missing", "invalid"]
    value: Optional[str] = Field(
        default=None,
        description="The value as it would be sent. Never returned for a secret header.",
    )
    policy: Optional[HeaderOnMissing] = Field(
        default=None,
        description="The missing-value policy applied, when state is 'missing'",
    )
    reason: Optional[str] = Field(default=None, description="Why the value is invalid")
    missing_dynamic_values: list[str] = []


class OutboundHeaderPreview(BaseModel):
    user_id: UUID
    headers: list[OutboundHeaderPreviewItem]
    destination_problem: Optional[str] = Field(
        default=None,
        description="Why requests to this provider's endpoint would be blocked",
    )
    blocked: bool = Field(
        ..., description="Whether this user's requests would be blocked"
    )
    blocked_reason: Optional[str] = Field(
        default=None,
        description=(
            "Why the headers block this user's requests, e.g. "
            "'missing_required_value', 'total_size_exceeded' or "
            "'decryption_failed' (a stored secret cannot be read)"
        ),
    )


class ModelProviderCreate(BaseModel):
    """Request model for creating a model provider."""

    name: str = Field(..., description="User-defined name for this provider instance")
    provider_type: str = Field(
        ..., description="Provider type: openai, azure, or anthropic"
    )
    credentials: dict[str, Any] = Field(
        ..., description="Provider credentials (will be encrypted)"
    )
    config: dict[str, Any] = Field(
        default_factory=dict, description="Additional configuration"
    )
    is_active: bool = Field(default=True, description="Whether the provider is active")
    key_expires_on: date | None = Field(
        default=None, description=_KEY_EXPIRES_ON_DESCRIPTION
    )
    outbound_headers: list[OutboundHeaderInput] = Field(
        default_factory=lambda: list[OutboundHeaderInput](),
        description="Outbound HTTP headers to configure",
    )


class ModelProviderUpdate(BaseModel):
    """Request model for updating a model provider."""

    name: Optional[str] = Field(
        None, description="User-defined name for this provider instance"
    )
    credentials: Optional[dict[str, Any]] = Field(
        None, description="Provider credentials (will be encrypted)"
    )
    config: Optional[dict[str, Any]] = Field(
        None, description="Additional configuration"
    )
    is_active: Optional[bool] = Field(
        None, description="Whether the provider is active"
    )
    key_expires_on: date | None = Field(
        default=None,
        description=(
            f"{_KEY_EXPIRES_ON_DESCRIPTION} Send null to remove the date; "
            "leave the field out to keep it."
        ),
    )
    outbound_headers: Optional[list[OutboundHeaderInput]] = Field(
        None,
        description="Replaces the configured outbound headers; omit to leave them unchanged",
    )


class ValidateModelRequest(BaseModel):
    """Request model for validating a model against a provider."""

    model_name: str = Field(..., description="Model name to validate")
    model_type: str = Field(
        default="completion",
        description="Model type: completion, embedding, transcription, image, or rerank",
    )


class FavoriteProvidersUpdate(BaseModel):
    """Request model for updating tenant's favorite provider types."""

    providers: list[str] = Field(
        ..., description="Ordered list of provider type strings to pin as favorites"
    )


class ConnectionCheckPublic(BaseModel):
    """The latest connection check: an authenticated call to the provider."""

    status: ConnectionCheckStatus
    checked_at: datetime
    error: ConnectionCheckError | None = Field(
        default=None,
        description=(
            "Why the check failed; set only when status is failed. A fixed "
            "category, never text from the provider's response."
        ),
    )


class ModelProviderPublic(BaseModel):
    """Public response model for a model provider (without credentials)."""

    id: UUID
    tenant_id: UUID
    name: str
    provider_type: str
    config: dict[str, Any]
    is_active: bool
    masked_api_key: str | None = None
    key_expires_on: date | None = Field(
        default=None, description=_KEY_EXPIRES_ON_DESCRIPTION
    )
    connection_check: ConnectionCheckPublic | None = Field(
        default=None,
        description=(
            "Result of the latest connection check; null until one runs and "
            "again after the credentials or endpoint change."
        ),
    )
    connection_check_supported: bool = Field(
        default=False,
        description=(
            "Whether POST /{provider_id}/connection-check/ can check this "
            "provider: Eneo knows a cheap authenticated call for its type, or "
            "it has an OpenAI-compatible endpoint."
        ),
    )
    outbound_headers: list[OutboundHeaderPublic] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

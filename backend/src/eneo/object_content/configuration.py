import os
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self, cast
from urllib.parse import urlparse
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_MEBIBYTE = 1024 * 1024
_MINIMUM_MULTIPART_PART_BYTES = 5 * _MEBIBYTE
_MAXIMUM_MULTIPART_PART_BYTES = 5 * 1024 * _MEBIBYTE
_MAXIMUM_MULTIPART_PARTS = 10_000
_MAXIMUM_S3_OBJECT_BYTES = 5 * 1024 * 1024 * _MEBIBYTE
_MAXIMUM_S3_PAGE_SIZE = 1_000


class ObjectContentCoreSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OBJECT_CONTENT_",
        env_file=None,
        extra="forbid",
        hide_input_in_errors=True,
    )

    inline_maximum_bytes: int = Field(default=10 * _MEBIBYTE, ge=1)
    inline_io_chunk_bytes: int = Field(default=256 * 1024, ge=1)
    reconciliation_batch_size: int = Field(
        default=100,
        ge=1,
        le=_MAXIMUM_S3_PAGE_SIZE,
    )
    reconciliation_concurrency: int = Field(default=4, ge=1, le=32)
    reconciliation_lease_seconds: int = Field(default=300, ge=1)
    reconciliation_retry_base_seconds: int = Field(default=30, ge=1)
    reconciliation_retry_max_seconds: int = Field(default=3600, ge=1)
    pending_stale_seconds: int = Field(default=300, ge=1)

    @model_validator(mode="after")
    def validate_core_bounds(self) -> Self:
        if self.inline_io_chunk_bytes > self.inline_maximum_bytes:
            raise ValueError(
                "inline_io_chunk_bytes must not exceed inline_maximum_bytes"
            )
        if (
            self.reconciliation_retry_max_seconds
            < self.reconciliation_retry_base_seconds
        ):
            raise ValueError(
                "reconciliation_retry_max_seconds must be at least the base delay"
            )
        return self


class ObjectContentSettings(ObjectContentCoreSettings):
    endpoint_url: str
    region: str = Field(min_length=1, max_length=128)
    bucket: str = Field(min_length=3, max_length=63)
    access_key_id: SecretStr
    secret_access_key: SecretStr
    deployment_id: UUID
    addressing_style: Literal["path", "virtual"] = "path"
    allow_insecure_http: bool = False
    ca_bundle: Path | None = None

    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    read_timeout_seconds: float = Field(default=60.0, gt=0)
    sdk_max_attempts: int = Field(default=3, ge=1)
    readiness_timeout_seconds: float = Field(default=2.0, gt=0)
    readiness_max_attempts: int = Field(default=1, ge=1)
    binding_claim_seconds: int = Field(default=30, ge=1)
    io_chunk_bytes: int = Field(default=256 * 1024, ge=1)
    spool_memory_bytes: int = Field(default=8 * _MEBIBYTE, ge=1)
    multipart_part_bytes: int = Field(
        default=8 * _MEBIBYTE,
        ge=_MINIMUM_MULTIPART_PART_BYTES,
        le=_MAXIMUM_MULTIPART_PART_BYTES,
    )
    multipart_threshold_bytes: int = Field(
        default=16 * _MEBIBYTE,
        ge=1,
        le=_MAXIMUM_MULTIPART_PART_BYTES,
    )
    delete_visibility_timeout_seconds: int = Field(default=30, ge=1)
    delete_poll_interval_seconds: float = Field(default=0.25, gt=0)
    orphan_grace_seconds: int = Field(default=3600, ge=1)

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("endpoint_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password:
            raise ValueError("endpoint_url must not contain credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("endpoint_url must not contain a path, query, or fragment")
        return value.removesuffix("/")

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        if not value[0].isalnum() or not value[-1].isalnum():
            raise ValueError("bucket must start and end with a letter or digit")
        if any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789.-"
            for character in value
        ):
            raise ValueError("bucket must use the portable S3 bucket-name subset")
        if ".." in value:
            raise ValueError("bucket must not contain adjacent periods")
        return value

    @field_validator("access_key_id", "secret_access_key")
    @classmethod
    def validate_credentials(cls, value: SecretStr) -> SecretStr:
        credential = value.get_secret_value()
        if not credential or len(credential) > 1024:
            raise ValueError("object-content credentials must be non-empty and bounded")
        return value

    @model_validator(mode="after")
    def validate_transport(self) -> Self:
        if (
            urlparse(self.endpoint_url).scheme == "http"
            and not self.allow_insecure_http
        ):
            raise ValueError(
                "plain HTTP requires allow_insecure_http=true on a private trusted network"
            )
        if self.ca_bundle is not None and not self.ca_bundle.is_file():
            raise ValueError("ca_bundle must name a readable regular file")
        if self.multipart_threshold_bytes < self.multipart_part_bytes:
            raise ValueError(
                "multipart_threshold_bytes must be at least multipart_part_bytes"
            )
        if self.io_chunk_bytes > self.spool_memory_bytes:
            raise ValueError("io_chunk_bytes must not exceed spool_memory_bytes")
        if self.delete_poll_interval_seconds > self.delete_visibility_timeout_seconds:
            raise ValueError(
                "delete_poll_interval_seconds must not exceed the visibility timeout"
            )
        if self.reconciliation_lease_seconds < self.sdk_request_budget_seconds:
            raise ValueError(
                "reconciliation_lease_seconds must cover the configured SDK retry window"
            )
        if self.binding_claim_seconds < self.readiness_request_budget_seconds:
            raise ValueError(
                "binding_claim_seconds must cover the configured readiness request window"
            )
        return self

    @property
    def sdk_request_budget_seconds(self) -> float:
        """Bound one SDK request, including retries and a scheduling margin."""
        return (
            self.sdk_max_attempts
            * (self.connect_timeout_seconds + self.read_timeout_seconds)
            + 5
        )

    @property
    def readiness_request_budget_seconds(self) -> float:
        """Bound one binding probe or mutation, including scheduling margin."""
        return self.readiness_max_attempts * (2 * self.readiness_timeout_seconds) + 5

    @property
    def maximum_multipart_bytes(self) -> int:
        """Return the portable S3 multipart protocol envelope."""
        return min(
            self.multipart_part_bytes * _MAXIMUM_MULTIPART_PARTS,
            _MAXIMUM_S3_OBJECT_BYTES,
        )

    @property
    def signing_region(self) -> str:
        """Return the endpoint's signing scope, not a data-residency choice."""
        return self.region

    @property
    def object_key_prefix(self) -> str:
        return f"v1/{self.deployment_id.hex}/"


def load_object_content_settings() -> ObjectContentSettings | None:
    core_fields = ObjectContentCoreSettings.model_fields
    remote_environment_names = {
        f"OBJECT_CONTENT_{name.upper()}"
        for name in ObjectContentSettings.model_fields
        if name not in core_fields
    }
    if not any(name.upper() in remote_environment_names for name in os.environ):
        return None
    settings_factory = cast(Callable[[], ObjectContentSettings], ObjectContentSettings)
    return settings_factory()


def load_object_content_core_settings() -> ObjectContentCoreSettings:
    settings_factory = cast(
        Callable[[], ObjectContentCoreSettings],
        ObjectContentCoreSettings,
    )
    return settings_factory()

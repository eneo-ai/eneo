"""Native transcription services an organisation connects Eneo to."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, LiteralString
from urllib.parse import urlsplit
from uuid import UUID

from eneo.model_providers.domain.endpoints import normalize_endpoint_base

if TYPE_CHECKING:
    from eneo.security_classifications.domain.entities.security_classification import (
        SecurityClassification,
    )

SERVICE_ENDPOINT_MAX_LENGTH = 2048


class TranscriptionOperation(StrEnum):
    """Work Eneo asks a native transcription service to do.

    A service may advertise more tasks (Vemsa also realigns corrected
    transcripts); Eneo neither sends those nor offers them as supported.
    """

    TRANSCRIBE = "transcribe"
    DIARIZE = "diarize"


@dataclass(frozen=True, slots=True)
class TranscriptionServiceConnection:
    """An organisation's connection to one native transcription service.

    Eneo uses it to identify speakers; a connection check reports whether the
    service says it can. The credential is write-only and never part of this
    view.
    """

    id: UUID
    tenant_id: UUID
    name: str
    endpoint_url: str
    is_enabled: bool
    security_classification: SecurityClassification | None
    created_at: datetime
    updated_at: datetime

    @property
    def can_access(self) -> bool:
        """New work may use the connection only while it is enabled."""
        return self.is_enabled


ServiceEndpointProblem = Literal[
    "service_endpoint_too_long",
    "service_endpoint_not_http",
    "service_endpoint_credentials",
    "service_endpoint_query",
    "service_endpoint_port",
]

SERVICE_ENDPOINT_MESSAGES: dict[ServiceEndpointProblem, LiteralString] = {
    "service_endpoint_too_long": "The endpoint is too long.",
    "service_endpoint_not_http": (
        "The endpoint must be an http or https URL with a host."
    ),
    "service_endpoint_credentials": (
        "The endpoint must not contain credentials; enter the API key separately."
    ),
    "service_endpoint_query": "The endpoint must not contain a query or a fragment.",
    "service_endpoint_port": "The endpoint has an invalid port.",
}


class ServiceEndpointError(ValueError):
    """Why an endpoint cannot be used, as a code with a fixed message that
    never repeats the input."""

    def __init__(self, code: ServiceEndpointProblem) -> None:
        self.code: ServiceEndpointProblem = code
        self.message: LiteralString = SERVICE_ENDPOINT_MESSAGES[code]
        super().__init__(self.message)


def parse_service_endpoint(raw: str) -> str:
    """The base URL the native ``/v1`` paths are built on.

    An http(s) URL with a host. Credentials, a query or a fragment are refused
    rather than dropped: each would change what is sent, or to whom, without
    the administrator seeing it. A trailing slash or ``/v1`` is removed, so
    either form of the same address is stored the same way.
    """
    value = raw.strip()
    if len(value) > SERVICE_ENDPOINT_MAX_LENGTH:
        raise ServiceEndpointError("service_endpoint_too_long")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ServiceEndpointError("service_endpoint_not_http")
    if parts.username is not None or parts.password is not None:
        raise ServiceEndpointError("service_endpoint_credentials")
    if parts.query or parts.fragment or value.endswith(("?", "#")):
        raise ServiceEndpointError("service_endpoint_query")
    try:
        parts.port
    except ValueError:
        raise ServiceEndpointError("service_endpoint_port") from None
    return normalize_endpoint_base(value)

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
# An organisation connects a handful of services; the cap keeps every list of
# them to one page (the routes' largest page size).
MAX_CONNECTIONS_PER_ORGANISATION = 200


class ConnectionCheckOutcome(StrEnum):
    READY = "ready"
    NOT_ACCEPTING_JOBS = "not_accepting_jobs"
    UNAVAILABLE = "unavailable"
    CREDENTIALS_REJECTED = "credentials_rejected"


class ConnectionCheckReason(StrEnum):
    """Why a check got no usable answer; a closed set that never quotes the
    endpoint, the key or the transport's own text."""

    # No connection was made, or no response came back.
    UNREACHABLE = "unreachable"
    # The answer did not arrive in time.
    TIMEOUT = "timeout"
    # The service answered with a status other than 200; the status is kept.
    HTTP_STATUS = "http_status"
    # The service answered 200 with something that is no readiness answer.
    MALFORMED = "malformed"
    # The service rejected the key.
    CREDENTIALS = "credentials"


@dataclass(frozen=True, slots=True)
class LastConnectionCheck:
    """The latest check of a connection's current endpoint and key.

    ``reason`` is None when the service answered usably; ``status_code`` is
    the status of an ``http_status`` answer.
    """

    outcome: ConnectionCheckOutcome
    identifies_speakers: bool | None
    service_version: str | None
    checked_at: datetime
    times_words: bool | None = None
    reason: ConnectionCheckReason | None = None
    status_code: int | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionServiceConnection:
    """An organisation's connection to one native transcription service.

    Eneo uses it to time the words of a flow's transcripts and to identify
    their speakers; a connection check reports whether the service says it
    can do each. The credential is write-only and never part of this view.
    """

    id: UUID
    tenant_id: UUID
    name: str
    endpoint_url: str
    is_enabled: bool
    # The organisation's default, marked by an administrator and never
    # inferred: a flow draft that transcribes and has made no choice of
    # service gets it stored as its own choice.
    is_default: bool
    security_classification: SecurityClassification | None
    created_at: datetime
    updated_at: datetime
    # Spaces granted the connection; flows there lose word timings and speaker
    # labels without it.
    space_count: int
    last_check: LastConnectionCheck | None

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

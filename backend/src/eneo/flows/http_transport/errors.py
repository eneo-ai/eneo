from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HttpTransportError(str, Enum):
    MISSING_URL = "HTTP_MISSING_URL"
    INVALID_URL = "HTTP_INVALID_URL"
    VARIABLE_RESOLUTION_FAILED = "HTTP_VARIABLE_RESOLUTION_FAILED"
    UNRESOLVED_STORED_SECRET = "HTTP_UNRESOLVED_STORED_SECRET"
    MISSING_AUTH_CREDENTIALS = "HTTP_MISSING_AUTH"
    INVALID_BODY_JSON = "HTTP_INVALID_BODY_JSON"
    BODY_NOT_ALLOWED_FOR_GET = "HTTP_BODY_NOT_ALLOWED_FOR_GET"
    TIMEOUT_OUT_OF_RANGE = "HTTP_TIMEOUT_OUT_OF_RANGE"
    TIMEOUT = "HTTP_TIMEOUT"
    CONNECTION_REFUSED = "HTTP_CONNECTION_REFUSED"
    STATUS_ERROR = "HTTP_STATUS_ERROR"


class HttpTemplateInterpolationError(Exception):
    """Raised when authored HTTP template interpolation cannot resolve a value."""


@dataclass(frozen=True, slots=True)
class AuthoredSecretEncryptionUnavailableError(Exception):
    """Raised when a plaintext authored secret cannot be encrypted before storage.

    ``secret_fields`` names the offending fields (never their values) so callers
    can tell the operator which credentials blocked the write.
    """

    secret_fields: tuple[str, ...]

    def __str__(self) -> str:
        return (
            "Authored HTTP secrets cannot be stored while encryption is inactive: "
            f"{', '.join(self.secret_fields)}."
        )

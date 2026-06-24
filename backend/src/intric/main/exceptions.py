from enum import Enum, unique
from typing import Any

from intric.files.text import (
    CorruptFileError,
    EncryptedFileError,
    ExtractionError,
    UnsupportedFormatError,
)


@unique
class ErrorCodes(int, Enum):
    NOT_FOUND = 9000
    UNAUTHORIZED = 9001
    UNSUPPORTED_MODEL = 9002
    QUERY_ERROR = 9003
    UNIQUE_USER_ERROR = 9004
    AUTHENTICATION_ERROR = 9005
    USER_NOT_CREATED = 9006
    BAD_REQUEST = 9007
    QUOTA_EXCEEDED = 9008
    UNIQUE_ERROR = 9009
    OPENAI_ERROR = 9010
    CLAUDE_ERROR = 9011
    VALIDATION_ERROR = 9012
    PYDANTIC_PARSE_ERROR = 9013
    FILE_NOT_SUPPORTED = 9014
    FILE_TOO_LARGE = 9015
    CHUNK_EMBEDDING_MISMATCH = 9016
    NAME_COLLISION = 9017
    PROVISIONING_NOT_ENABLED = 9018
    USER_INACTIVE = 9019
    NO_MODEL_SELECTED = 9020
    CRAWL_ALREADY_RUNNING = 9021
    IAM_EXCEPTION = 9022
    INTERNAL_HTTP_ERROR = 9023
    INTERNAL_SERVER_ERROR = 9024
    TENANT_SUSPENDED = 9025
    API_KEY_NOT_CONFIGURED = 9026
    # File extraction errors
    FILE_EXTRACTION_ERROR = 9027
    FILE_ENCRYPTED = 9028
    FILE_CORRUPT = 9029
    FILE_FORMAT_UNSUPPORTED = 9030
    # Provider errors
    PROVIDER_INACTIVE = 9031
    PROVIDER_NOT_FOUND = 9032
    # Resource configuration errors
    MODEL_NOT_AVAILABLE = 9033
    KNOWLEDGE_MODEL_UNAVAILABLE = 9034
    SECURITY_CLASSIFICATION_MISMATCH = 9035
    # MCP upstream errors
    MCP_UPSTREAM_ERROR = 9036
    MCP_UPSTREAM_AUTH_ERROR = 9037
    # Resource readiness
    RESOURCE_NOT_READY = 9038
    # Model lifecycle — soft-delete blocked because the model is still
    # referenced by an active resource (assistants, apps, services,
    # assistant/app templates). Space membership alone does not block.
    MODEL_IN_USE = 9039
    # System user protection
    SYSTEM_USER_PROTECTED = 9040
    # AI provider deterministically rejected the request (4xx upstream)
    PROVIDER_REJECTED_REQUEST = 9041


class NotFoundException(Exception):
    pass


class UnauthorizedException(Exception):
    def __init__(
        self,
        message: str = "",
        *,
        code: str = "forbidden",
        context: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.context = context


class UnsupportedModelException(Exception):
    pass


class QueryException(Exception):
    def __init__(
        self,
        message: str | None = None,
        *,
        tokens_used: int | None = None,
        token_limit: int | None = None,
    ):
        self.tokens_used = tokens_used
        self.token_limit = token_limit

        if message is None:
            message = self._build_default_message()

        super().__init__(message)

    def _build_default_message(self) -> str:
        if self.tokens_used is not None and self.token_limit is not None:
            return (
                f"Input is too long for the selected model: "
                f"{self.tokens_used:,} tokens used, limit is {self.token_limit:,} tokens. "
                f"Try a shorter input, fewer attachments, or a model with a larger context window."
            )
        return "Query too long"

    @property
    def details(self) -> dict[str, Any]:
        details: dict[str, Any] = {}

        if self.tokens_used is not None:
            details["tokens_used"] = self.tokens_used

        if self.token_limit is not None:
            details["token_limit"] = self.token_limit

        return details


class UniqueUserException(Exception):
    pass


class AuthenticationException(Exception):
    pass


class BadRequestException(Exception):
    pass


class ModelInUseException(Exception):
    """Raised when trying to soft-delete a model that is still referenced.

    Surfaced as 400 with a dedicated error code so the frontend can show a
    localized "Model is in use" message and offer the migration flow as a
    follow-up action — the generic BAD_REQUEST code can't carry that
    context.
    """

    pass


class QuotaExceededException(Exception):
    pass


class UniqueException(Exception):
    pass


class OpenAIException(Exception):
    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        context: dict[str, object] | None = None,
        details: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.context = context
        self.details = details


class ProviderRejectedRequestException(OpenAIException):
    """The AI provider deterministically rejected the request (upstream 4xx).

    Subclasses OpenAIException so existing provider-error handling keeps
    catching it, but maps to 400 instead of 503: the request/configuration is
    at fault, not provider availability, and retrying cannot succeed.
    """

    pass


class ClaudeException(Exception):
    pass


class ValidationException(Exception):
    pass


class PydanticParseError(Exception):
    pass


class NotReadyException(Exception):
    pass


class FileNotSupportedException(Exception):
    pass


class FileTooLargeException(Exception):
    DEFAULT_DOCS_HINT = (
        "See backend/README.md (Environment variables) and backend/.env.template "
        "to update upload limits."
    )

    def __init__(
        self,
        message: str | None = None,
        *,
        file_size: int | None = None,
        max_size: int | None = None,
        setting_name: str | None = None,
        docs_hint: str | None = None,
    ):
        self.file_size = file_size
        self.max_size = max_size
        self.setting_name = setting_name
        self.docs_hint = docs_hint or self.DEFAULT_DOCS_HINT

        if message is None:
            message = self._build_default_message()

        super().__init__(message)

    @staticmethod
    def _format_bytes(value: int) -> str:
        if value < 1024:
            return f"{value} bytes"

        size = float(value)
        units = ("KB", "MB", "GB", "TB")

        for unit in units:
            size /= 1024
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"

        return f"{value} bytes"

    def _build_default_message(self) -> str:
        if self.file_size is not None and self.max_size is not None:
            message = (
                "File size limit exceeded: "
                f"got {self.file_size} bytes ({self._format_bytes(self.file_size)}), "
                f"maximum allowed is {self.max_size} bytes ({self._format_bytes(self.max_size)})."
            )
        elif self.max_size is not None:
            message = (
                "File size limit exceeded: "
                f"maximum allowed is {self.max_size} bytes ({self._format_bytes(self.max_size)})."
            )
        else:
            message = "File size limit exceeded."

        if self.setting_name:
            message += (
                f" Adjust {self.setting_name} in your backend environment "
                "if you need a higher limit."
            )

        if self.docs_hint:
            message += f" {self.docs_hint}"

        return message

    @property
    def details(self) -> dict[str, Any]:
        details: dict[str, Any] = {}

        if self.file_size is not None:
            details["file_size_bytes"] = self.file_size
            details["file_size_human"] = self._format_bytes(self.file_size)

        if self.max_size is not None:
            details["max_size_bytes"] = self.max_size
            details["max_size_human"] = self._format_bytes(self.max_size)

        return details


class ChunkEmbeddingMisMatchException(Exception):
    pass


class CrawlerException(Exception):
    pass


class CrawlTimeoutError(CrawlerException):
    """Raised when a crawl times out but may have partial results.

    This is a controlled termination, not a failure. The crawler ran for
    the configured max_length but didn't complete naturally. Partial results
    in the JSONL spool file should be preserved and persisted.

    Attributes:
        url: The URL that was being crawled
        timeout_seconds: The timeout value that was exceeded
        pages_collected: Number of pages in the spool file (if known)
    """

    def __init__(
        self,
        url: str,
        timeout_seconds: int,
        pages_collected: int = 0,
        message: str | None = None,
    ):
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.pages_collected = pages_collected
        msg = message or f"Crawl timeout: exceeded {timeout_seconds}s for {url}"
        if pages_collected > 0:
            msg += f" ({pages_collected} pages collected)"
        super().__init__(msg)


class NameCollisionException(Exception):
    pass


class UserNotCreatedInIntricError(Exception):
    pass


class ProvisioningNotAllowed(Exception):
    pass


class UserInactiveException(Exception):
    pass


class NoModelSelectedException(Exception):
    pass


class CrawlAlreadyRunningException(Exception):
    pass


class IAMException(Exception):
    pass


class InternalHTTPException(Exception):
    pass


class InternalServerException(Exception):
    pass


class TenantSuspendedException(Exception):
    pass


class APIKeyNotConfiguredException(Exception):
    pass


class SystemUserProtected(Exception):
    """Raised when an admin path tries to delete or mutate a system user.

    Per-tenant system users (``users.is_system_user = true``) own seeded
    Help Assistant rows; deleting them would cascade-destroy the org-space's
    Prompt Guide and audit history. The marker is authoritative — no admin
    path is allowed to remove it.
    """

    pass


class ProviderInactiveException(Exception):
    """Raised when attempting to use a model whose provider is inactive/disabled."""

    pass


class ProviderNotFoundException(Exception):
    """Raised when the model's provider cannot be found in the database."""

    pass


class ModelNotAvailableException(Exception):
    """Raised when a model is assigned to a resource but not available in the space."""

    pass


class KnowledgeModelUnavailableException(Exception):
    """Raised when a knowledge source uses an embedding model that is not available."""

    pass


class SecurityClassificationMismatchException(Exception):
    """Raised when a resource does not meet the space's security classification."""

    pass


class MCPClientError(Exception):
    """Raised when an upstream MCP service fails."""

    pass


class MCPAuthenticationError(MCPClientError):
    """Raised when upstream MCP authentication fails."""

    pass


# Map exceptions to response codes
# Set message to None to use the internal message
# Set error codes in the range 9000 - 9999
EXCEPTION_MAP = {
    NotFoundException: (404, "Not found", ErrorCodes.NOT_FOUND),
    UnauthorizedException: (403, None, ErrorCodes.UNAUTHORIZED),
    UnsupportedModelException: (400, None, ErrorCodes.UNSUPPORTED_MODEL),
    QueryException: (400, None, ErrorCodes.QUERY_ERROR),
    UniqueUserException: (400, None, ErrorCodes.UNIQUE_USER_ERROR),
    AuthenticationException: (401, "Unauthenticated", ErrorCodes.AUTHENTICATION_ERROR),
    UserNotCreatedInIntricError: (
        401,
        "User is not created",
        ErrorCodes.USER_NOT_CREATED,
    ),
    BadRequestException: (400, None, ErrorCodes.BAD_REQUEST),
    ModelInUseException: (
        400,
        "Model is currently in use and cannot be deleted.",
        ErrorCodes.MODEL_IN_USE,
    ),
    QuotaExceededException: (403, None, ErrorCodes.QUOTA_EXCEEDED),
    UniqueException: (400, None, ErrorCodes.UNIQUE_ERROR),
    OpenAIException: (503, None, ErrorCodes.OPENAI_ERROR),
    # Starlette resolves handlers via MRO, so this subclass entry wins over
    # the OpenAIException one for deterministic upstream rejections.
    ProviderRejectedRequestException: (
        400,
        None,
        ErrorCodes.PROVIDER_REJECTED_REQUEST,
    ),
    ClaudeException: (503, None, ErrorCodes.CLAUDE_ERROR),
    ValidationException: (422, None, ErrorCodes.VALIDATION_ERROR),
    PydanticParseError: (500, None, ErrorCodes.PYDANTIC_PARSE_ERROR),
    FileNotSupportedException: (415, None, ErrorCodes.FILE_NOT_SUPPORTED),
    FileTooLargeException: (413, None, ErrorCodes.FILE_TOO_LARGE),
    ChunkEmbeddingMisMatchException: (
        500,
        "Something went wrong.",
        ErrorCodes.CHUNK_EMBEDDING_MISMATCH,
    ),
    NameCollisionException: (409, None, ErrorCodes.NAME_COLLISION),
    ProvisioningNotAllowed: (403, None, ErrorCodes.PROVISIONING_NOT_ENABLED),
    UserInactiveException: (403, None, ErrorCodes.USER_INACTIVE),
    NoModelSelectedException: (400, None, ErrorCodes.NO_MODEL_SELECTED),
    CrawlAlreadyRunningException: (429, None, ErrorCodes.CRAWL_ALREADY_RUNNING),
    IAMException: (500, None, ErrorCodes.IAM_EXCEPTION),
    InternalHTTPException: (
        500,
        "Something went wrong.",
        ErrorCodes.INTERNAL_HTTP_ERROR,
    ),
    InternalServerException: (
        500,
        "Something went wrong.",
        ErrorCodes.INTERNAL_SERVER_ERROR,
    ),
    TenantSuspendedException: (403, "Tenant is suspended", ErrorCodes.TENANT_SUSPENDED),
    APIKeyNotConfiguredException: (503, None, ErrorCodes.API_KEY_NOT_CONFIGURED),
    # File extraction errors - use None to pass through the exception's own message
    ExtractionError: (400, None, ErrorCodes.FILE_EXTRACTION_ERROR),
    EncryptedFileError: (400, None, ErrorCodes.FILE_ENCRYPTED),
    CorruptFileError: (400, None, ErrorCodes.FILE_CORRUPT),
    UnsupportedFormatError: (415, None, ErrorCodes.FILE_FORMAT_UNSUPPORTED),
    # Provider errors - use None to pass through the exception's own message
    ProviderInactiveException: (503, None, ErrorCodes.PROVIDER_INACTIVE),
    ProviderNotFoundException: (404, None, ErrorCodes.PROVIDER_NOT_FOUND),
    # Resource configuration errors - use None to pass through the exception's own message
    ModelNotAvailableException: (400, None, ErrorCodes.MODEL_NOT_AVAILABLE),
    KnowledgeModelUnavailableException: (
        400,
        None,
        ErrorCodes.KNOWLEDGE_MODEL_UNAVAILABLE,
    ),
    SecurityClassificationMismatchException: (
        400,
        None,
        ErrorCodes.SECURITY_CLASSIFICATION_MISMATCH,
    ),
    # MCP upstream errors
    MCPClientError: (
        502,
        "MCP upstream service unavailable.",
        ErrorCodes.MCP_UPSTREAM_ERROR,
    ),
    MCPAuthenticationError: (
        502,
        "MCP upstream authentication failed.",
        ErrorCodes.MCP_UPSTREAM_AUTH_ERROR,
    ),
    NotReadyException: (
        503,
        "Resource is not ready yet.",
        ErrorCodes.RESOURCE_NOT_READY,
    ),
    SystemUserProtected: (403, None, ErrorCodes.SYSTEM_USER_PROTECTED),
}

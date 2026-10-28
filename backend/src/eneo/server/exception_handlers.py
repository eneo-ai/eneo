import logging
import traceback
import uuid
from typing import Any, Protocol, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from eneo.files.file_models import (
    FileInUseError,
    FileOriginalNotFoundError,
)
from eneo.icons.icon import IconInUseError, IconNotAttachableError
from eneo.info_blobs.info_blob import InfoBlobOriginalUnavailableError
from eneo.integration.domain.repositories.integration_knowledge_repo import (
    IntegrationKnowledgeSyncingError,
)
from eneo.integration.infrastructure.auth_service.base_auth_service import (
    OAuthClientRejectedError,
    OAuthCodeRejectedError,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    SharePointCredentialsInvalidError,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import (
    EXCEPTION_MAP,
    ErrorCodes,
    UnauthorizedException,
)
from eneo.main.models import GeneralError
from eneo.main.request_context import get_request_context
from eneo.object_content.content import (
    ContentTooLargeError,
    InvalidContentRangeError,
    ObjectContentBusyError,
    ObjectContentIdempotencyConflictError,
    ObjectContentIntegrityError,
    ObjectContentStateError,
    ObjectContentUnavailableError,
)
from eneo.object_content.deployment_policy import (
    DeploymentPolicyConflict,
    ObjectStoreTargetNotSelectable,
)
from eneo.object_content.object_store_connection import (
    ObjectStoreConnectionAlreadyConfigured,
    ObjectStoreConnectionConflict,
    ObjectStoreConnectionDatabaseUnavailable,
    ObjectStoreConnectionInvalid,
    ObjectStoreConnectionMutationOutcomeUnknown,
    ObjectStoreConnectionNotConfigured,
    ObjectStoreCredentialDataInvalid,
    ObjectStoreCredentialEncryptionUnavailable,
    ObjectStoreDestinationAlreadyBound,
    ObjectStoreDestinationCopyIncomplete,
    ObjectStoreDestinationSwitchBlocked,
    ObjectStoreMovesNotPaused,
    ObjectStoreNewWritesNotRedirected,
    ObjectStorePendingDestinationMissing,
    ObjectStorePlainHttpNotPermitted,
    ObjectStorePreviousDestinationMissing,
    ObjectStorePreviousDestinationPresent,
    ObjectStoreProbeAuthenticationFailed,
    ObjectStoreProbeBindingMismatch,
    ObjectStoreProbeCleanupFailed,
    ObjectStoreProbeConnectionFailed,
    ObjectStoreProbeIntegrityFailed,
    ObjectStoreProbeTlsFailed,
    ObjectStoreProbeUnavailable,
)
from eneo.server.middleware.cors import add_cors_headers
from eneo.server.middleware.trace_id import current_trace_id
from eneo.skills.domain.skill import (
    PublishedSkillDeletionError,
    SkillBlockedForBindingError,
    SkillExecutionBlockConflictError,
    SkillHasActiveAppRunsError,
    SkillHasBindingsError,
    SkillNotPublishedForBindingError,
    SkillRemovalBusyError,
    SkillRuntimePolicyChangedError,
    SkillSlugConflictError,
)
from eneo.users.password import (
    CurrentPasswordIncorrectError,
    LocalPasswordChangeUnavailableError,
    PasswordPolicyViolationError,
    PasswordReuseError,
)
from eneo.users.password_lifecycle import PasswordChangeRequiredError
from eneo.websites.domain.crawl_run_repo import (
    WebsiteCrawlActiveError,
    WebsiteCrawlCleanupPendingError,
)

# Partial unique indexes that guard active model display names, per
# 20260602_unique_model_display_names. Their names all end in this suffix.
_ACTIVE_NICKNAME_INDEX_SUFFIX = "_active_nickname"


def is_active_display_name_violation(exc: IntegrityError) -> bool:
    """True when an IntegrityError is a collision on a `uq_*_active_nickname`
    index — the validate-then-insert race the display-name pre-check can't close.

    Matches on the driver's reported constraint name when available, falling back
    to the rendered error text (Postgres includes the constraint name there), so
    it works regardless of which DBAPI surfaced the error.
    """
    orig = getattr(exc, "orig", None)
    constraint_name = getattr(orig, "constraint_name", None) or ""
    if constraint_name.endswith(_ACTIVE_NICKNAME_INDEX_SUFFIX):
        return True
    return _ACTIVE_NICKNAME_INDEX_SUFFIX in str(orig if orig is not None else exc)


class ExceptionContext(Protocol):
    context: dict[str, object] | None
    details: dict[str, object] | None
    code: str | None


def _default_message_for_status(status_code: int) -> str:
    if status_code == 400:
        return "Bad request."
    if status_code == 401:
        return "Unauthenticated."
    if status_code == 403:
        return "Forbidden: you do not have permission to perform this action."
    if status_code == 404:
        return "Not found"
    if status_code == 409:
        return "Conflict."
    if status_code >= 500:
        return "Something went wrong."
    return "Request failed."


def default_error_code_for_status(status_code: int) -> ErrorCodes:
    """The coarse numeric category for a status raised without one.

    An `HTTPException` raised with a `{"code", "message"}` detail carries only
    the string code, while clients branch on the numeric field. This
    keeps one category per status for those, so a client that branches on the
    numeric field is not left guessing at which layer refused the request.
    Precision lives in the string `code`, which the raiser owns.

    Only statuses whose meaning the category restates are mapped. A status that
    covers several domain failures, such as 409, falls through to the coarse
    one: the web client turns a category into a sentence for the reader, so
    inferring `NAME_COLLISION` from any conflict would tell someone resolving
    an approval conflict that a display name is taken.
    """
    if status_code == 401:
        return ErrorCodes.AUTHENTICATION_ERROR
    if status_code == 403:
        return ErrorCodes.UNAUTHORIZED
    if status_code == 404:
        return ErrorCodes.NOT_FOUND
    if status_code == 429:
        return ErrorCodes.QUOTA_EXCEEDED
    if status_code >= 500:
        return ErrorCodes.INTERNAL_SERVER_ERROR
    return ErrorCodes.BAD_REQUEST


def extract_request_id(request: Request | None = None) -> str | None:
    """The ``request_id`` an error body carries.

    Documented contract: a caller-sent correlation/request header is echoed;
    otherwise the request context's correlation id, which the logs carry.
    """
    if request is not None:
        request_id = request.headers.get("x-correlation-id") or request.headers.get(
            "x-request-id"
        )
        if request_id:
            return request_id
    return get_request_context().get("correlation_id")


def correlation_headers() -> dict[str, str] | None:
    """``X-Correlation-ID`` for an error response, or ``None``.

    Carries the request context's id: the trace id when a span is active,
    otherwise the caller's legacy header. That is the value every log line
    of the request carries, so support can go from the header to the logs.
    The trace middleware sets the same header when a span exists; this covers
    deployments without tracing.
    """
    correlation_id = get_request_context().get("correlation_id")
    if not correlation_id:
        return None
    return {"X-Correlation-ID": str(correlation_id)}


def has_registered_handler(app: FastAPI, exc: BaseException) -> bool:
    """Whether ``exc`` gets a canonical response from a handler on ``app``.

    Resolved the way Starlette resolves handlers, by ``isinstance``. The
    ``Exception`` and status-code catch-alls do not count: they are what an
    unexpected failure falls into.
    """
    return any(
        isinstance(key, type) and key is not Exception and isinstance(exc, key)
        for key in app.exception_handlers
    )


def _exception_context(
    *,
    status_code: int,
    exc: Exception,
) -> dict[str, object] | None:
    typed_exc = cast(ExceptionContext, exc)
    raw_context = getattr(typed_exc, "context", None)
    if isinstance(raw_context, dict):
        context_dict = cast(dict[object, object], raw_context)
        result: dict[str, object] = {
            str(key): value for key, value in context_dict.items()
        }
    else:
        result = {}

    if isinstance(exc, UnauthorizedException):
        result.setdefault("auth_layer", "domain_policy")

    if status_code not in {401, 403}:
        result.pop("auth_layer", None)

    return result or None


logger = logging.getLogger(__name__)


# Domain exceptions that carry their own HTTP status, reason code and English
# fallback. They live here rather than in eneo.main.exceptions because the
# server adapter may depend on a domain package without reversing that
# dependency. One map, so "where do I register this?" has one answer.
DOMAIN_EXCEPTION_MAP: dict[type[Exception], tuple[int, str | None, ErrorCodes]] = {
    # --- Local user credentials ---
    CurrentPasswordIncorrectError: (
        400,
        None,
        ErrorCodes.CURRENT_PASSWORD_INCORRECT,
    ),
    PasswordReuseError: (400, None, ErrorCodes.PASSWORD_REUSE),
    PasswordPolicyViolationError: (
        400,
        None,
        ErrorCodes.PASSWORD_POLICY_VIOLATION,
    ),
    LocalPasswordChangeUnavailableError: (
        409,
        None,
        ErrorCodes.LOCAL_PASSWORD_CHANGE_UNAVAILABLE,
    ),
    PasswordChangeRequiredError: (403, None, ErrorCodes.PASSWORD_CHANGE_REQUIRED),
    # --- Integrations: the string ``code`` tells the cases apart ---
    SharePointCredentialsInvalidError: (400, None, ErrorCodes.BAD_REQUEST),
    OAuthCodeRejectedError: (400, None, ErrorCodes.BAD_REQUEST),
    OAuthClientRejectedError: (400, None, ErrorCodes.BAD_REQUEST),
    IntegrationKnowledgeSyncingError: (409, None, ErrorCodes.BAD_REQUEST),
    # --- Website crawl lifecycle ---
    WebsiteCrawlActiveError: (
        409,
        "Stop the active crawl before deleting this website.",
        ErrorCodes.WEBSITE_CRAWL_ACTIVE,
    ),
    WebsiteCrawlCleanupPendingError: (
        409,
        "Crawler cleanup is still in progress; retry deletion shortly.",
        ErrorCodes.WEBSITE_CRAWL_CLEANUP_PENDING,
    ),
    # --- Object content and files ---
    ObjectContentUnavailableError: (503, None, ErrorCodes.RESOURCE_NOT_READY),
    ObjectContentIntegrityError: (503, None, ErrorCodes.RESOURCE_NOT_READY),
    ObjectContentIdempotencyConflictError: (409, None, ErrorCodes.UNIQUE_ERROR),
    ObjectContentStateError: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectContentBusyError: (409, None, ErrorCodes.RESOURCE_NOT_READY),
    FileInUseError: (409, None, ErrorCodes.FILE_IN_USE),
    FileOriginalNotFoundError: (404, None, ErrorCodes.FILE_ORIGINAL_NOT_FOUND),
    IconInUseError: (409, None, ErrorCodes.ICON_IN_USE),
    IconNotAttachableError: (400, None, ErrorCodes.ICON_NOT_ATTACHABLE),
    InfoBlobOriginalUnavailableError: (
        404,
        None,
        ErrorCodes.INFO_BLOB_ORIGINAL_UNAVAILABLE,
    ),
    ContentTooLargeError: (413, None, ErrorCodes.FILE_TOO_LARGE),
    InvalidContentRangeError: (416, None, ErrorCodes.BAD_REQUEST),
    DeploymentPolicyConflict: (409, None, ErrorCodes.DEPLOYMENT_POLICY_CONFLICT),
    ObjectStoreTargetNotSelectable: (
        409,
        None,
        ErrorCodes.OBJECT_STORE_NOT_SELECTABLE,
    ),
    ObjectStoreConnectionAlreadyConfigured: (
        409,
        None,
        ErrorCodes.UNIQUE_ERROR,
    ),
    ObjectStoreConnectionNotConfigured: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreConnectionDatabaseUnavailable: (
        503,
        None,
        ErrorCodes.RESOURCE_NOT_READY,
    ),
    ObjectStoreConnectionMutationOutcomeUnknown: (
        503,
        None,
        ErrorCodes.RESOURCE_NOT_READY,
    ),
    ObjectStoreDestinationAlreadyBound: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreDestinationSwitchBlocked: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreDestinationCopyIncomplete: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreMovesNotPaused: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreNewWritesNotRedirected: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectStorePendingDestinationMissing: (404, None, ErrorCodes.NOT_FOUND),
    ObjectStorePreviousDestinationMissing: (404, None, ErrorCodes.NOT_FOUND),
    ObjectStorePreviousDestinationPresent: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreConnectionConflict: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreConnectionInvalid: (400, None, ErrorCodes.BAD_REQUEST),
    ObjectStorePlainHttpNotPermitted: (400, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreCredentialEncryptionUnavailable: (
        503,
        None,
        ErrorCodes.RESOURCE_NOT_READY,
    ),
    ObjectStoreCredentialDataInvalid: (
        503,
        None,
        ErrorCodes.RESOURCE_NOT_READY,
    ),
    ObjectStoreProbeAuthenticationFailed: (400, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreProbeTlsFailed: (400, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreProbeBindingMismatch: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreProbeIntegrityFailed: (400, None, ErrorCodes.BAD_REQUEST),
    ObjectStoreProbeCleanupFailed: (503, None, ErrorCodes.RESOURCE_NOT_READY),
    ObjectStoreProbeConnectionFailed: (
        503,
        None,
        ErrorCodes.RESOURCE_NOT_READY,
    ),
    ObjectStoreProbeUnavailable: (503, None, ErrorCodes.RESOURCE_NOT_READY),
    # --- Skill lifecycle conflicts ---
    SkillSlugConflictError: (
        409,
        "A Skill with this identifier already exists in this scope. "
        "Choose a different identifier.",
        ErrorCodes.SKILL_SLUG_TAKEN,
    ),
    PublishedSkillDeletionError: (
        409,
        "Previously published Skills are retained for audit history "
        "and cannot be deleted.",
        ErrorCodes.SKILL_PUBLISHED_NOT_DELETABLE,
    ),
    SkillHasActiveAppRunsError: (
        409,
        "This Skill is required by a queued or running App run. "
        "Wait for it to finish before deleting the Skill.",
        ErrorCodes.SKILL_IN_USE_BY_APP_RUN,
    ),
    SkillHasBindingsError: (
        409,
        "This Skill is still attached. Remove every binding before deleting it.",
        ErrorCodes.SKILL_STILL_ATTACHED,
    ),
    SkillRemovalBusyError: (
        409,
        "One or more selected Skills are being changed. Nothing was removed. "
        "Reload and try again when the change has finished.",
        ErrorCodes.SKILL_REMOVAL_BUSY,
    ),
    SkillNotPublishedForBindingError: (
        400,
        "Bindings can only move to published organisation Skill versions",
        ErrorCodes.SKILL_NOT_PUBLISHED_FOR_BINDING,
    ),
    SkillBlockedForBindingError: (
        400,
        "Blocked organisation Skills cannot receive new or changed bindings",
        ErrorCodes.SKILL_BLOCKED_FOR_BINDING,
    ),
    SkillExecutionBlockConflictError: (
        409,
        "This execution block changed after you reviewed it. "
        "Reload the Skill before unblocking.",
        ErrorCodes.SKILL_EXECUTION_BLOCK_CONFLICT,
    ),
    SkillRuntimePolicyChangedError: (
        409,
        "The organisation's Skill policy changed while this move was being "
        "validated. Run the update again against the current policy.",
        ErrorCodes.SKILL_RUNTIME_POLICY_CHANGED,
    ),
}


def _http_exception_body(
    exc: StarletteHTTPException, request_id: str | None
) -> dict[str, Any]:
    """The `GeneralError` envelope for a raised `HTTPException`.

    The raised detail stays in `detail` for one release, so a client reading
    `body.detail.code` keeps working while it moves to the top-level fields.
    """
    detail: object = exc.detail
    structured = cast(dict[str, Any], detail) if isinstance(detail, dict) else None
    if structured is not None and "code" in structured and "message" in structured:
        # Every raiser of this shape means it as the documented error, and its
        # extra keys (`retry_after_seconds`, `existing_status`) are part of the
        # route's contract, so the dict becomes the body. Most raisers left the
        # numeric category out; fill it here so a direct raise cannot bypass it.
        body = dict(structured)
        body.setdefault(
            "eneo_error_code", default_error_code_for_status(exc.status_code).value
        )
        if request_id:
            body.setdefault("request_id", request_id)
        body["detail"] = detail
        return body

    raised_message = structured.get("message") if structured is not None else detail
    message = (
        raised_message
        if isinstance(raised_message, str)
        else _default_message_for_status(exc.status_code)
    )
    # No status-default `eneo_error_code`: both clients prefer a category's
    # catalog text over the message, which would turn a specific refusal into
    # a generic "Forbidden". A structured refusal without a code (the healthz
    # report) moves to `details`, so nothing lives only in the deprecated copy.
    return GeneralError(
        message=message, request_id=request_id, details=structured, detail=detail
    ).model_dump(exclude_none=True)


def add_exception_handlers(app: FastAPI):
    async def http_exception_handler(request: Request, exc: Exception) -> Response:
        # Registered on Starlette's class, so routing misses (404, 405) answer
        # in the same envelope as a route's own raise.
        http_exc = cast(StarletteHTTPException, exc)
        # The raiser's headers win; otherwise carry the request's correlation
        # id like the canonical handlers do, so the header matches the logs.
        headers = {**(correlation_headers() or {}), **(http_exc.headers or {})}
        if http_exc.status_code in {204, 304}:
            return Response(status_code=http_exc.status_code, headers=headers)
        return JSONResponse(
            status_code=http_exc.status_code,
            content=_http_exception_body(http_exc, extract_request_id(request)),
            headers=headers,
        )

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # FastAPI keeps one server-error handler (the last of 500/Exception).
        # It runs in ServerErrorMiddleware, outside the CORS and trace
        # middlewares, so this handler adds their headers itself.
        error_id = str(uuid.uuid4())[:8]
        logger.error(
            f"Unhandled Exception [error_id={error_id}]",
            extra={
                "error_id": error_id,
                "path": request.url.path,
                "method": request.method,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )

        error_content: dict[str, Any] = {
            "error": "Internal server error",
            "error_id": error_id,
            "message": "An unexpected error occurred. Please try again or contact support with the error_id.",
        }
        if get_settings().is_development:
            error_content["detail"] = {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "path": request.url.path,
                "method": request.method,
            }

        response = JSONResponse(status_code=500, content=error_content)
        trace_id = current_trace_id()
        if trace_id:
            response.headers["X-Trace-Id"] = trace_id
            response.headers["X-Correlation-ID"] = trace_id
        await add_cors_headers(request, response)
        return response

    app.add_exception_handler(Exception, unhandled_exception_handler)

    async def request_validation_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Keep the documented HTTPValidationError shape, but never serialize
        # raw input, validation context or validator-generated messages. Even
        # SecretStr cannot redact input when a required sibling is missing,
        # and a custom validator may embed a secret in its error message.
        validation_exc = cast(RequestValidationError, exc)
        public_messages = {
            "missing": "Field required",
            "string_type": "Input should be a valid string",
            "json_invalid": "Invalid JSON",
        }
        details: list[dict[str, object]] = [
            {
                "loc": error["loc"],
                "type": error["type"],
                "msg": public_messages.get(error["type"], "Invalid value"),
            }
            for error in validation_exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": details},
            headers=correlation_headers(),
        )

    app.add_exception_handler(RequestValidationError, request_validation_error_handler)

    exception_handlers = (
        *EXCEPTION_MAP.items(),
        *DOMAIN_EXCEPTION_MAP.items(),
    )
    for exception, (status_code, error_message, error_code) in exception_handlers:

        def handler(
            request: Request,
            exc: Exception,
            status_code: int = status_code,
            error_message: str | None = error_message,
            error_code: ErrorCodes = error_code,
        ) -> JSONResponse:
            message = error_message or str(exc)
            if not message or not message.strip():
                message = _default_message_for_status(status_code)
            request_id = extract_request_id(request)
            context = _exception_context(status_code=status_code, exc=exc)
            raw_details = getattr(exc, "details", None)
            details: dict[str, object] | None
            if isinstance(raw_details, dict) and raw_details:
                detail_dict = cast(dict[object, object], raw_details)
                details = {str(key): value for key, value in detail_dict.items()}
            else:
                details = None

            if status_code >= 400:
                log_level = logging.WARNING if status_code < 500 else logging.ERROR
                logger.log(
                    log_level,
                    "%s %s → %d: %s",
                    request.method,
                    request.url.path,
                    status_code,
                    message,
                    extra={"details": details, "error_code": error_code},
                )

            return JSONResponse(
                status_code=status_code,
                headers=correlation_headers(),
                content=GeneralError(
                    message=message,
                    eneo_error_code=error_code,
                    code=getattr(exc, "code", None),
                    context=context,
                    request_id=request_id,
                    details=details,
                ).model_dump(exclude_none=True),
            )

        app.add_exception_handler(exception, handler)

    async def integrity_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # Concurrent creates/renames to the same display name both pass the
        # pre-check, then one loses at flush against the active-nickname unique
        # index. Surface that as the same clean 409 the pre-check raises. Other
        # integrity errors are re-raised so the catch-all 500 handler keeps its
        # current behaviour (error_id, trace headers).
        integrity_exc = cast(IntegrityError, exc)
        if not is_active_display_name_violation(integrity_exc):
            raise exc

        request_id = extract_request_id(request)
        logger.warning(
            "%s %s → 409: display name collision (DB index)",
            request.method,
            request.url.path,
            extra={"error_code": ErrorCodes.NAME_COLLISION},
        )
        return JSONResponse(
            status_code=409,
            content=GeneralError(
                message="A model with this display name already exists.",
                eneo_error_code=ErrorCodes.NAME_COLLISION,
                request_id=request_id,
            ).model_dump(exclude_none=True),
        )

    app.add_exception_handler(IntegrityError, integrity_error_handler)

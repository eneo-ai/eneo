import logging
from typing import Protocol, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from eneo.files.file_models import (
    FileInUseError,
    FileOriginalNotFoundError,
)
from eneo.main.exceptions import EXCEPTION_MAP, ErrorCodes, UnauthorizedException
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
from eneo.skills.domain.skill import (
    PublishedSkillDeletionError,
    SkillBlockedForBindingError,
    SkillExecutionBlockConflictError,
    SkillHasActiveAppRunsError,
    SkillHasBindingsError,
    SkillNotPublishedForBindingError,
    SkillSlugConflictError,
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


def _extract_request_id(request: Request) -> str | None:
    request_id = request.headers.get("x-correlation-id") or request.headers.get(
        "x-request-id"
    )
    if request_id:
        return request_id
    return get_request_context().get("correlation_id")


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
    # --- Object content and files ---
    ObjectContentUnavailableError: (503, None, ErrorCodes.RESOURCE_NOT_READY),
    ObjectContentIntegrityError: (503, None, ErrorCodes.RESOURCE_NOT_READY),
    ObjectContentIdempotencyConflictError: (409, None, ErrorCodes.UNIQUE_ERROR),
    ObjectContentStateError: (409, None, ErrorCodes.BAD_REQUEST),
    ObjectContentBusyError: (409, None, ErrorCodes.RESOURCE_NOT_READY),
    FileInUseError: (409, None, ErrorCodes.FILE_IN_USE),
    FileOriginalNotFoundError: (404, None, ErrorCodes.FILE_ORIGINAL_NOT_FOUND),
    ContentTooLargeError: (413, None, ErrorCodes.FILE_TOO_LARGE),
    InvalidContentRangeError: (416, None, ErrorCodes.BAD_REQUEST),
    DeploymentPolicyConflict: (409, None, ErrorCodes.DEPLOYMENT_POLICY_CONFLICT),
    ObjectStoreTargetNotSelectable: (
        409,
        None,
        ErrorCodes.OBJECT_STORE_NOT_SELECTABLE,
    ),
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
}


def add_exception_handlers(app: FastAPI):
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
            request_id = _extract_request_id(request)
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

        request_id = _extract_request_id(request)
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

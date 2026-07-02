import logging
from collections.abc import Mapping, Sequence
from typing import Protocol, TypeGuard, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from eneo.main.exceptions import EXCEPTION_MAP, ErrorCodes, UnauthorizedException
from eneo.main.models import GeneralError
from eneo.main.request_context import get_request_context

# Partial unique indexes that guard active model display names, per
# 20260602_unique_model_display_names. Their names all end in this suffix.
_ACTIVE_NICKNAME_INDEX_SUFFIX = "_active_nickname"
REQUEST_VALIDATION_ERROR_CODE = "request_validation_error"
REQUEST_VALIDATION_ERROR_MESSAGE = "Request validation failed."


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
    if status_code == 410:
        return "Gone."
    if status_code == 409:
        return "Conflict."
    if status_code >= 500:
        return "Something went wrong."
    return "Request failed."


def extract_request_id(request: Request) -> str | None:
    request_id = request.headers.get("x-correlation-id") or request.headers.get(
        "x-request-id"
    )
    if isinstance(request_id, str) and request_id:
        return request_id
    context_request_id = get_request_context().get("correlation_id")
    return (
        context_request_id
        if isinstance(context_request_id, str) and context_request_id
        else None
    )


def _validation_error_location(raw_location: object) -> list[str | int]:
    if not _is_validation_error_sequence(raw_location):
        return []
    return [part for part in raw_location if isinstance(part, (str, int))]


def _is_validation_error_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    )


def _is_validation_error_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _validation_error_entry(error: Mapping[str, object]) -> dict[str, object]:
    entry: dict[str, object] = {}
    location = _validation_error_location(error.get("loc"))
    if location:
        entry["location"] = location

    message = error.get("msg")
    if isinstance(message, str):
        entry["message"] = message

    error_type = error.get("type")
    if isinstance(error_type, str):
        entry["type"] = error_type

    return entry


def validation_error_details(detail: object) -> dict[str, object]:
    errors: list[dict[str, object]] = []
    if _is_validation_error_sequence(detail):
        for item in detail:
            if _is_validation_error_mapping(item):
                entry = _validation_error_entry(item)
                if entry:
                    errors.append(entry)
    elif isinstance(detail, str) and detail.strip():
        errors.append({"message": detail, "type": "value_error"})

    return {"errors": errors}


def validation_error_response_content(
    *, request: Request, detail: object, details: dict[str, object] | None = None
) -> dict[str, object]:
    content = GeneralError(
        message=REQUEST_VALIDATION_ERROR_MESSAGE,
        eneo_error_code=ErrorCodes.VALIDATION_ERROR,
        code=REQUEST_VALIDATION_ERROR_CODE,
        request_id=extract_request_id(request),
        details=details or validation_error_details(detail),
    ).model_dump(exclude_none=True)
    return {str(key): value for key, value in content.items()}


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


def add_exception_handlers(app: FastAPI):
    for exception, (status_code, error_message, error_code) in EXCEPTION_MAP.items():

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

    async def request_validation_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        if not isinstance(exc, RequestValidationError):
            raise exc

        errors = exc.errors()
        details = validation_error_details(errors)
        logger.warning(
            "%s %s → 422: %s",
            request.method,
            request.url.path,
            REQUEST_VALIDATION_ERROR_MESSAGE,
            extra={"details": details, "error_code": ErrorCodes.VALIDATION_ERROR},
        )
        return JSONResponse(
            status_code=422,
            content=validation_error_response_content(
                request=request, detail=errors, details=details
            ),
        )

    app.add_exception_handler(RequestValidationError, request_validation_error_handler)

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

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from intric.main.exceptions import EXCEPTION_MAP, UnauthorizedException
from intric.main.models import GeneralError
from intric.main.request_context import get_request_context


def _default_message_for_status(status_code: int) -> str:
    if status_code == 400:
        return "Bad request."
    if status_code == 401:
        return "Unauthenticated."
    if status_code == 403:
        return "Forbidden: you do not have permission to perform this action."
    if status_code == 404:
        return "Not found."
    if status_code == 409:
        return "Conflict."
    if status_code >= 500:
        return "Something went wrong."
    return "Request failed."


def _extract_request_id(request) -> str | None:
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
    context = getattr(exc, "context", None)
    if isinstance(context, dict):
        result = dict(context)
    else:
        result = {}

    if isinstance(exc, UnauthorizedException):
        result.setdefault("auth_layer", "domain_policy")

    if status_code not in {401, 403}:
        result.pop("auth_layer", None)

    return result or None


def add_exception_handlers(app: FastAPI):
    for exception, (status_code, error_message, error_code) in EXCEPTION_MAP.items():

        def handler(
            request,
            exc,
            status_code=status_code,
            error_message=error_message,
            error_code=error_code,
        ):
            message = error_message or str(exc)
            if not message or not message.strip():
                message = _default_message_for_status(status_code)
            request_id = _extract_request_id(request)
            context = _exception_context(status_code=status_code, exc=exc)
            return JSONResponse(
                status_code=status_code,
                content=GeneralError(
                    message=message,
                    intric_error_code=error_code,
                    code=getattr(exc, "code", None),
                    context=context,
                    request_id=request_id,
                ).model_dump(exclude_none=True),
            )

        app.add_exception_handler(exception, handler)

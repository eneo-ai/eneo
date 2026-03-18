import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from intric.main.exceptions import EXCEPTION_MAP
from intric.main.models import GeneralError

logger = logging.getLogger(__name__)


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
            details = getattr(exc, "details", None)
            if not isinstance(details, dict) or len(details) == 0:
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
                    intric_error_code=error_code,
                    details=details,
                ).model_dump(exclude_none=True),
            )

        app.add_exception_handler(exception, handler)

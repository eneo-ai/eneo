from fastapi import FastAPI
from fastapi.responses import JSONResponse

from intric.main.exceptions import EXCEPTION_MAP
from intric.main.models import GeneralError
from intric.main.logging import get_logger

logger = get_logger(__name__)


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

            # Log authentication failures at INFO level for debugging
            if status_code == 401:
                logger.info(
                    f"[Auth] Authentication failed: {request.method} {request.url.path} - {str(exc)}",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "error_code": error_code,
                        "client_host": request.client.host if request.client else "unknown",
                    }
                )

            return JSONResponse(
                status_code=status_code,
                content=GeneralError(
                    message=message, intric_error_code=error_code
                ).model_dump(),
            )

        app.add_exception_handler(exception, handler)

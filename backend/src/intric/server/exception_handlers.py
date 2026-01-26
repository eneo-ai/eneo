from fastapi import FastAPI
from fastapi.responses import JSONResponse

from intric.main.exceptions import EXCEPTION_MAP
from intric.main.models import GeneralError


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
            return JSONResponse(
                status_code=status_code,
                content=GeneralError(
                    message=message, intric_error_code=error_code
                ).model_dump(),
            )

        app.add_exception_handler(exception, handler)

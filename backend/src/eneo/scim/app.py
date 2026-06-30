from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from eneo.main.logging import get_logger
from eneo.scim.domain.errors import (
    ScimHttpError,
    ScimInvalidFilterError,
    ScimValidationError,
)
from eneo.scim.router import router as scim_router

_SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"
logger = get_logger(__name__)


def _scim_error_json(
    status_code: int, detail: str, scim_type: str | None = None
) -> JSONResponse:
    content: dict[str, object] = {
        "schemas": [_SCIM_ERROR_SCHEMA],
        "status": str(status_code),
        "detail": detail,
    }
    if scim_type:
        content["scimType"] = scim_type
    return JSONResponse(status_code=status_code, content=content)


scim_app = FastAPI(
    title="Eneo SCIM 2.0 API",
    description="RFC 7644 compliant SCIM provisioning API. Authenticate with the tenant SCIM bearer token.",
    docs_url="/docs",
    redoc_url="/redoc",
)

scim_app.include_router(scim_router)


@scim_app.exception_handler(ScimHttpError)
async def scim_http_error_handler(request: Request, exc: ScimHttpError) -> JSONResponse:
    return _scim_error_json(exc.status_code, exc.detail, exc.scim_type)


@scim_app.exception_handler(ScimValidationError)
async def scim_validation_error_handler(
    request: Request, exc: ScimValidationError
) -> JSONResponse:
    return _scim_error_json(400, str(exc), scim_type="invalidValue")


@scim_app.exception_handler(ScimInvalidFilterError)
async def scim_invalid_filter_error_handler(
    request: Request, exc: ScimInvalidFilterError
) -> JSONResponse:
    return _scim_error_json(400, str(exc), scim_type="invalidFilter")


@scim_app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # SCIM clients expect a 4xx SCIM error body (RFC 7644 §3.12), not FastAPI's
    # default 422. Map pydantic/FastAPI request-validation failures to 400 with
    # scimType invalidValue (a required value was missing or an attribute value
    # was incompatible with its type). We summarise the failing locations rather
    # than dumping str(exc), which embeds the full internal error repr.
    details = "; ".join(
        f"{'.'.join(str(loc) for loc in err.get('loc', ()))}: {err.get('msg', '')}"
        for err in exc.errors()
    )
    detail = (
        f"Request validation failed: {details}"
        if details
        else "Request validation failed"
    )
    return _scim_error_json(400, detail, scim_type="invalidValue")


@scim_app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _scim_error_json(exc.status_code, str(exc.detail) if exc.detail else "")


@scim_app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "scim.unhandled_exception",
        extra={"path": request.url.path, "method": request.method},
    )
    return _scim_error_json(500, "Internal server error")

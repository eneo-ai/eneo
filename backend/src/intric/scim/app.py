from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from intric.main.logging import get_logger
from intric.scim.domain.errors import ScimHttpError, ScimValidationError
from intric.scim.router import router as scim_router

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


@scim_app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return _scim_error_json(422, str(exc))


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

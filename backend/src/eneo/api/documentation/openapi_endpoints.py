"""OpenAPI schema endpoint implementation."""

from fastapi import APIRouter, Request

from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)

router = APIRouter()


@router.get(
    "/api-docs",
    tags=["Documentation"],
    summary="Get OpenAPI specification",
    description="Returns the complete OpenAPI 3.0 specification for this API. Compatible with WSO2 API Manager.",
    responses={200: {"description": "OpenAPI specification"}},
    response_model=None,
)
@endpoint_access(
    authentication=Authentication.PUBLIC,
    authorization=Authorization.PUBLIC,
    reason="Published API documentation is intentionally public.",
)
async def get_api_documentation(request: Request):
    """Returns the OpenAPI specification - identical to /openapi.json but documented."""
    return request.app.openapi()

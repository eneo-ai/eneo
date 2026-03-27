"""OpenAPI schema endpoint implementation."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get(
    "/api-docs",
    tags=["Documentation"],
    summary="Get OpenAPI specification",
    description="Returns the complete OpenAPI 3.0 specification for this API. Compatible with WSO2 API Manager."
)
async def get_api_documentation(request: Request):
    """Returns the OpenAPI specification - identical to /openapi.json but documented."""
    return request.app.openapi()
"""Integration tests for X-Trace-Id and CORS exposure on error / non-200 responses.

Spec acceptance criteria this covers:
    "X-Trace-Id is included in HTTP responses and exposed via
     Access-Control-Expose-Headers on all responses, including 4xx and 5xx."

The 500 cases separately exercise an explicit HTTP 500 and an unhandled
exception. Both must retain the typed platform error envelope, support identity,
trace headers, and the manual CORS behavior owned by ``server.main``.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Response

from eneo.flow_packages.api.flow_package_models import (
    FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER,
)
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError


@pytest.mark.integration
@pytest.mark.asyncio
async def test_x_trace_id_present_on_404(client):
    """X-Trace-Id must be set on 4xx responses (TraceIdResponseMiddleware runs
    on every http.response.start, regardless of status code)."""
    response = await client.get("/api/v1/this-route-does-not-exist")
    assert response.status_code == 404

    header_names = {h.lower() for h in response.headers}
    assert "x-trace-id" in header_names, (
        f"X-Trace-Id missing from 404 response headers: {sorted(header_names)}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cors_exposes_both_trace_headers(client, admin_user_api_key):
    """Access-Control-Expose-Headers must list both X-Trace-Id and the legacy
    X-Correlation-ID alias so browser-side JS can read them on every response."""
    response = await client.get(
        "/api/v1/users/me/",
        headers={
            "X-API-Key": admin_user_api_key.key,
            # CORSMiddleware only emits CORS headers when an Origin is present.
            "Origin": "http://example.com",
        },
    )
    assert response.status_code == 200

    expose = response.headers.get("access-control-expose-headers", "").lower()
    assert "x-trace-id" in expose, (
        f"Access-Control-Expose-Headers missing X-Trace-Id: {expose!r}"
    )
    assert "x-correlation-id" in expose, (
        f"Access-Control-Expose-Headers missing X-Correlation-ID: {expose!r}"
    )
    assert FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER.lower() in expose


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cors_exposes_positive_package_omission_header(app):
    from httpx import ASGITransport, AsyncClient

    @app.get("/api/v1/_test_package_omission_header")
    async def _package_omission_header() -> Response:
        return Response(headers={FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER: "2"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test.local") as client:
        response = await client.get(
            "/api/v1/_test_package_omission_header",
            headers={"Origin": "http://example.com"},
        )

    assert response.status_code == 200
    assert response.headers[FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER] == "2"
    expose = response.headers.get("access-control-expose-headers", "").lower()
    assert FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER.lower() in expose


@pytest.mark.integration
@pytest.mark.asyncio
async def test_500_exposes_trace_headers(app):
    """An unhandled 500 retains the typed platform envelope, trace headers,
    support identity, and manual CORS behavior from ``server.main``.

    A throwaway route raises so the catch-all Exception handler runs. We use a
    client with raise_app_exceptions=False because Starlette's
    ServerErrorMiddleware re-raises after sending the 500, which would otherwise
    surface in the test instead of the response.
    """
    from httpx import ASGITransport, AsyncClient

    @app.get("/api/v1/_test_force_500")
    async def _force_500():
        raise RuntimeError("forced error for integration test")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test.local") as client:
        response = await client.get(
            "/api/v1/_test_force_500",
            headers={"Origin": "http://example.com"},
        )

    assert response.status_code == 500
    error = GeneralError.model_validate(response.json())
    assert error.code == "internal_error"
    assert error.eneo_error_code is ErrorCodes.INTERNAL_SERVER_ERROR
    assert error.error_id is not None

    expose = response.headers.get("access-control-expose-headers", "").lower()
    assert "x-trace-id" in expose, (
        f"500 response missing X-Trace-Id in Access-Control-Expose-Headers: {expose!r}"
    )
    assert "x-correlation-id" in expose, (
        f"500 response missing X-Correlation-ID in Access-Control-Expose-Headers: {expose!r}"
    )
    assert FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER.lower() in expose


@pytest.mark.integration
@pytest.mark.asyncio
async def test_explicit_http_500_preserves_error_identity_and_cors(app):
    from httpx import ASGITransport, AsyncClient

    @app.get("/api/v1/_test_explicit_500")
    async def _explicit_500():
        raise HTTPException(status_code=500, detail="must not leak")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test.local") as client:
        response = await client.get(
            "/api/v1/_test_explicit_500",
            headers={
                "Origin": "http://example.com",
                "X-Request-ID": "explicit-http-500",
            },
        )

    assert response.status_code == 500
    error = GeneralError.model_validate(response.json())
    assert error.code == "internal_error"
    assert error.eneo_error_code is ErrorCodes.INTERNAL_SERVER_ERROR
    assert error.request_id == "explicit-http-500"
    assert error.error_id is not None
    assert "must not leak" not in response.text
    assert response.headers["x-trace-id"]
    assert response.headers["x-correlation-id"] == response.headers["x-trace-id"]
    expose = response.headers["access-control-expose-headers"].lower()
    assert "x-trace-id" in expose
    assert "x-correlation-id" in expose

"""Integration tests for trace headers and CORS on successful and error responses.

Spec acceptance criteria this covers:
    "X-Trace-Id is included in HTTP responses and exposed via
     Access-Control-Expose-Headers on all responses, including 4xx and 5xx."
"""

from __future__ import annotations

import pytest


@pytest.fixture
async def allowed_origin(db_container, admin_user):
    origin = "http://example.com"
    async with db_container() as container:
        await container.allowed_origin_repo().add_origin(
            origin=origin, tenant_id=admin_user.tenant_id
        )
    return origin


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
async def test_cors_exposes_both_trace_headers(
    client, admin_user_api_key, allowed_origin
):
    """Access-Control-Expose-Headers must list both X-Trace-Id and the legacy
    X-Correlation-ID alias so browser-side JS can read them on every response."""
    response = await client.get(
        "/api/v1/users/me/",
        headers={
            "X-API-Key": admin_user_api_key.key,
            "Origin": allowed_origin,
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == allowed_origin

    expose = response.headers.get("access-control-expose-headers", "").lower()
    assert "x-trace-id" in expose, (
        f"Access-Control-Expose-Headers missing X-Trace-Id: {expose!r}"
    )
    assert "x-correlation-id" in expose, (
        f"Access-Control-Expose-Headers missing X-Correlation-ID: {expose!r}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("same_origin", [False, True])
async def test_500_exposes_trace_headers(app, allowed_origin, same_origin):
    """An unhandled 500 must still expose the trace headers via CORS and carry
    error_id, exercising the manual CORS block in the Exception handler that
    reuses _TRACE_EXPOSE_HEADERS (server/main.py).

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
    request_origin = "http://test.local" if same_origin else allowed_origin
    async with AsyncClient(transport=transport, base_url="http://test.local") as client:
        response = await client.get(
            "/api/v1/_test_force_500",
            headers={"Origin": request_origin},
        )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == request_origin
    assert "error_id" in response.json(), "error_id must be present on 500 responses"

    expose = response.headers.get("access-control-expose-headers", "").lower()
    assert "x-trace-id" in expose, (
        f"500 response missing X-Trace-Id in Access-Control-Expose-Headers: {expose!r}"
    )
    assert "x-correlation-id" in expose, (
        f"500 response missing X-Correlation-ID in Access-Control-Expose-Headers: {expose!r}"
    )

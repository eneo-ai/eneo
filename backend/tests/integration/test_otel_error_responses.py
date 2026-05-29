"""Integration tests for X-Trace-Id and CORS exposure on error / non-200 responses.

Spec acceptance criteria this covers:
    "X-Trace-Id is included in HTTP responses and exposed via
     Access-Control-Expose-Headers on all responses, including 4xx and 5xx."

We test the 4xx path because triggering a real 500 inside the integration
client requires a deliberately-broken route or service patch, which adds
machinery beyond the scope of this minimal suite. The 4xx case exercises the
same TraceIdResponseMiddleware (X-Trace-Id injection) and the standard
CORSMiddleware (Access-Control-Expose-Headers list) that the 5xx path uses;
the 5xx-only code is the manual CORS block in server.main's error handler,
which is left for a follow-up test paired with a fault-injection route.
"""

from __future__ import annotations

import pytest


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_500_exposes_trace_headers(app):
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
    async with AsyncClient(transport=transport, base_url="http://test.local") as client:
        response = await client.get(
            "/api/v1/_test_force_500",
            headers={"Origin": "http://example.com"},
        )

    assert response.status_code == 500
    assert "error_id" in response.json(), "error_id must be present on 500 responses"

    expose = response.headers.get("access-control-expose-headers", "").lower()
    assert "x-trace-id" in expose, (
        f"500 response missing X-Trace-Id in Access-Control-Expose-Headers: {expose!r}"
    )
    assert "x-correlation-id" in expose, (
        f"500 response missing X-Correlation-ID in Access-Control-Expose-Headers: {expose!r}"
    )

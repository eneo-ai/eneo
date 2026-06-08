"""Verify that all error responses on SCIM routes use the SCIM error schema."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from intric.scim.app import scim_app
from intric.scim.auth import require_scim_auth
from intric.scim.deps import get_scim_user_service
from intric.scim.services.user_service import ScimUserService
from intric.server.main import app
from tests.unittests.scim.conftest import _check_test_token

TEST_TOKEN = "test-scim-token"
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}
SCIM_ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


@pytest.fixture
async def client() -> AsyncClient:
    scim_app.dependency_overrides[require_scim_auth] = _check_test_token
    scim_app.dependency_overrides[get_scim_user_service] = lambda: AsyncMock(
        spec=ScimUserService
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    scim_app.dependency_overrides.clear()


class TestScimErrorSchema:
    async def test_unauthorized_returns_scim_schema(self, client: AsyncClient):
        res = await client.get(
            "/scim/v2/Users", headers={"Authorization": "Bearer wrong-token"}
        )
        assert res.status_code == 401
        body = res.json()
        assert SCIM_ERROR_SCHEMA in body["schemas"]
        assert body["status"] == "401"

    async def test_validation_error_returns_scim_schema(self, client: AsyncClient):
        """SCIM clients expect a 4xx SCIM error body (RFC 7644 §3.12), so
        FastAPI/pydantic request-validation failures must map to 400
        invalidValue rather than the framework default 422."""
        res = await client.post(
            "/scim/v2/Users",
            json={"invalid": "payload"},
            headers=AUTH,
        )
        assert res.status_code == 400
        body = res.json()
        assert SCIM_ERROR_SCHEMA in body["schemas"]
        assert body["status"] == "400"
        assert body["scimType"] == "invalidValue"
        # Detail names the failing attribute (the required userName) instead of
        # dumping the raw RequestValidationError repr.
        assert "userName" in body["detail"]

    async def test_unhandled_error_returns_generic_scim_500(
        self,
        client: AsyncClient,
    ):
        mock_service = AsyncMock(spec=ScimUserService)
        mock_service.list_users.side_effect = RuntimeError("database password leaked")
        scim_app.dependency_overrides[get_scim_user_service] = lambda: mock_service

        res = await client.get("/scim/v2/Users", headers=AUTH)

        assert res.status_code == 500
        body = res.json()
        assert SCIM_ERROR_SCHEMA in body["schemas"]
        assert body["status"] == "500"
        assert body["detail"] == "Internal server error"
        assert "database password leaked" not in body["detail"]

    async def test_non_scim_error_uses_default_format(self, client: AsyncClient):
        # Non-SCIM routes should not use the SCIM error schema format
        res = await client.get("/api/v1/this-route-does-not-exist")
        assert res.status_code == 404
        assert "schemas" not in res.json()

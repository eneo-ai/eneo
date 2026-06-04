"""Integration tests for SCIM authentication.

All SCIM endpoints require a bearer token matched against the tenant's
scim_token_hash column (SHA-256 of the raw token).
"""

import pytest


@pytest.mark.asyncio
@pytest.mark.integration
async def test_missing_bearer_token_returns_401(client):
    """Requests without an Authorization header are rejected with 401."""
    response = await client.get("/scim/v2/ServiceProviderConfig")
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "401"
    assert "urn:ietf:params:scim:api:messages:2.0:Error" in body["schemas"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_wrong_bearer_token_returns_401(client):
    """Requests with an incorrect bearer token are rejected with 401."""
    response = await client.get(
        "/scim/v2/ServiceProviderConfig",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == "401"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_valid_bearer_token_accepted(client, scim_auth_headers):
    """A request with the correct bearer token reaches the endpoint successfully.

    scim_auth_headers stores the SHA-256 hash of the test token in the test
    tenant's scim_token_hash column, then passes the raw token in the header.
    """
    response = await client.get("/scim/v2/ServiceProviderConfig", headers=scim_auth_headers)
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_auth_required_on_users_endpoint(client):
    """Users endpoint rejects unauthenticated requests with 401."""
    response = await client.get("/scim/v2/Users")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_auth_required_on_groups_endpoint(client):
    """Groups endpoint rejects unauthenticated requests with 401."""
    response = await client.get("/scim/v2/Groups")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_auth_error_response_is_scim_format(client):
    """Auth error responses use SCIM error schema, not standard FastAPI error format."""
    response = await client.get("/scim/v2/Users")
    body = response.json()
    assert "schemas" in body
    assert "urn:ietf:params:scim:api:messages:2.0:Error" in body["schemas"]
    assert "status" in body
    assert "detail" in body
    assert "detail" not in body.get("schemas", [])

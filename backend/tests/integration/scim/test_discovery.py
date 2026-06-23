"""Integration tests for SCIM discovery endpoints.

ServiceProviderConfig, Schemas, and ResourceTypes are read-only endpoints that
return static JSON. They are fully functional with the current implementation.
"""

import pytest


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_provider_config_returns_200(client, bypass_scim_auth):
    """GET /scim/v2/ServiceProviderConfig returns 200 with correct schema."""
    response = await client.get("/scim/v2/ServiceProviderConfig")
    assert response.status_code == 200
    body = response.json()
    assert "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig" in body["schemas"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_provider_config_advertises_patch_support(client, bypass_scim_auth):
    """ServiceProviderConfig reports that PATCH is supported."""
    response = await client.get("/scim/v2/ServiceProviderConfig")
    body = response.json()
    assert body["patch"]["supported"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_provider_config_advertises_bulk_support(client, bypass_scim_auth):
    """ServiceProviderConfig reports bulk operations are supported with configured limits."""
    response = await client.get("/scim/v2/ServiceProviderConfig")
    body = response.json()
    assert body["bulk"]["supported"] is True
    assert body["bulk"]["maxOperations"] == 100
    assert body["bulk"]["maxPayloadSize"] == 1_048_576


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_provider_config_reports_filter_support(client, bypass_scim_auth):
    """ServiceProviderConfig reports that filtering is supported."""
    response = await client.get("/scim/v2/ServiceProviderConfig")
    body = response.json()
    assert body["filter"]["supported"] is True
    assert body["filter"]["maxResults"] == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_service_provider_config_reports_no_password_change(client, bypass_scim_auth):
    """ServiceProviderConfig reports changePassword is not supported (SSO-only tenants)."""
    response = await client.get("/scim/v2/ServiceProviderConfig")
    body = response.json()
    assert body["changePassword"]["supported"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_schemas_returns_user_and_group(client, bypass_scim_auth):
    """GET /scim/v2/Schemas returns schema definitions for User and Group."""
    response = await client.get("/scim/v2/Schemas")
    assert response.status_code == 200
    body = response.json()
    assert body["totalResults"] == 2
    schema_ids = {s["id"] for s in body["Resources"]}
    assert "urn:ietf:params:scim:schemas:core:2.0:User" in schema_ids
    assert "urn:ietf:params:scim:schemas:core:2.0:Group" in schema_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_resource_types_returns_user_and_group(client, bypass_scim_auth):
    """GET /scim/v2/ResourceTypes returns User and Group resource type definitions."""
    response = await client.get("/scim/v2/ResourceTypes")
    assert response.status_code == 200
    body = response.json()
    assert body["totalResults"] == 2
    names = {r["name"] for r in body["Resources"]}
    assert "User" in names
    assert "Group" in names


@pytest.mark.asyncio
@pytest.mark.integration
async def test_resource_types_have_correct_endpoints(client, bypass_scim_auth):
    """ResourceTypes list the correct SCIM endpoints for User and Group."""
    response = await client.get("/scim/v2/ResourceTypes")
    body = response.json()
    by_name = {r["name"]: r for r in body["Resources"]}
    assert by_name["User"]["endpoint"] == "/Users"
    assert by_name["Group"]["endpoint"] == "/Groups"

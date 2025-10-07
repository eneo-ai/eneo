"""
Contract tests for Tenant Credentials API endpoints.

These tests define the expected behavior of the API endpoints before implementation.
Following TDD principles, these tests MUST FAIL initially.

Endpoints tested:
- PUT /admin/tenants/{id}/credentials/{provider} - Set tenant credential
- DELETE /admin/tenants/{id}/credentials/{provider} - Delete tenant credential
- GET /admin/tenants/{id}/credentials - List tenant credentials
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4


# =============================================================================
# T005 - PUT /admin/tenants/{id}/credentials/{provider} Tests
# =============================================================================

@pytest.mark.contract
def test_set_tenant_credential_openai(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - OpenAI

    Given: A valid OpenAI API key
    When: Setting the credential for a tenant
    Then: Returns 200 OK with masked key
    """
    response = client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        json={"api_key": "sk-test-1234567890"},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "openai"
    assert data["masked_key"] == "...890"
    assert data["tenant_id"] == str(test_tenant.id)
    # API key should not be returned
    assert "api_key" not in data


@pytest.mark.contract
def test_set_tenant_credential_azure(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - Azure OpenAI

    Given: Valid Azure OpenAI credentials with all 4 required fields
    When: Setting the credential for a tenant
    Then: Returns 200 OK with masked key
    """
    response = client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/azure",
        json={
            "api_key": "azure-key-1234567890",
            "api_base": "https://my-resource.openai.azure.com",
            "api_version": "2024-02-15-preview",
            "deployment_name": "gpt-4-deployment"
        },
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "azure"
    assert data["masked_key"] == "...890"
    assert data["tenant_id"] == str(test_tenant.id)
    # Sensitive fields should not be returned
    assert "api_key" not in data
    assert "api_base" not in data


@pytest.mark.contract
def test_set_tenant_credential_anthropic(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - Anthropic

    Given: A valid Anthropic API key
    When: Setting the credential for a tenant
    Then: Returns 200 OK with masked key
    """
    response = client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/anthropic",
        json={"api_key": "sk-ant-1234567890"},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "anthropic"
    assert data["masked_key"] == "...890"
    assert data["tenant_id"] == str(test_tenant.id)


@pytest.mark.contract
def test_set_tenant_credential_update_existing(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - Update existing

    Given: An existing credential for a provider
    When: Setting a new credential for the same provider
    Then: Returns 200 OK and updates the credential
    """
    # Set initial credential
    client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        json={"api_key": "sk-test-old-key-123"},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    # Update with new credential
    response = client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        json={"api_key": "sk-test-new-key-789"},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["masked_key"] == "...789"  # Should reflect new key


@pytest.mark.contract
def test_set_tenant_credential_invalid_provider(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - Invalid provider

    Given: An invalid provider name
    When: Attempting to set credentials
    Then: Returns 422 Unprocessable Entity
    """
    response = client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/invalid_provider",
        json={"api_key": "some-key"},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 422
    data = response.json()
    assert "detail" in data


@pytest.mark.contract
def test_set_tenant_credential_missing_api_key(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - Missing api_key

    Given: A request without api_key field
    When: Attempting to set credentials
    Then: Returns 400 Bad Request
    """
    response = client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        json={},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "api_key" in data["detail"].lower()


@pytest.mark.contract
def test_set_tenant_credential_azure_missing_required_fields(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - Azure missing fields

    Given: Azure credentials without required fields (api_base, api_version, deployment_name)
    When: Attempting to set credentials
    Then: Returns 400 Bad Request
    """
    response = client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/azure",
        json={"api_key": "azure-key-123"},  # Missing api_base, api_version, deployment_name
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 400
    data = response.json()
    assert "detail" in data


@pytest.mark.contract
def test_set_tenant_credential_no_auth(
    client: TestClient,
    test_tenant
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - No authentication

    Given: A request without authentication token
    When: Attempting to set credentials
    Then: Returns 403 Forbidden
    """
    response = client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        json={"api_key": "sk-test-123"}
    )

    assert response.status_code == 403


@pytest.mark.contract
def test_set_tenant_credential_tenant_not_found(
    client: TestClient,
    super_admin_token: str
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - Tenant not found

    Given: A non-existent tenant ID
    When: Attempting to set credentials
    Then: Returns 404 Not Found
    """
    non_existent_id = str(uuid4())
    response = client.put(
        f"/admin/tenants/{non_existent_id}/credentials/openai",
        json={"api_key": "sk-test-123"},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 404


@pytest.mark.contract
def test_set_tenant_credential_empty_api_key(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: PUT /admin/tenants/{id}/credentials/{provider} - Empty api_key

    Given: A request with empty api_key
    When: Attempting to set credentials
    Then: Returns 400 Bad Request
    """
    response = client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        json={"api_key": ""},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 400


# =============================================================================
# T006 - DELETE /admin/tenants/{id}/credentials/{provider} Tests
# =============================================================================

@pytest.mark.contract
def test_delete_tenant_credential(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: DELETE /admin/tenants/{id}/credentials/{provider} - Success

    Given: An existing credential
    When: Deleting the credential
    Then: Returns 200 OK
    """
    # Set up credential first
    client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        json={"api_key": "sk-test-123"},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    # Delete it
    response = client.delete(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


@pytest.mark.contract
def test_delete_tenant_credential_not_found(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: DELETE /admin/tenants/{id}/credentials/{provider} - Not found

    Given: A non-existent credential
    When: Attempting to delete it
    Then: Returns 404 Not Found
    """
    response = client.delete(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 404


@pytest.mark.contract
def test_delete_tenant_credential_no_auth(
    client: TestClient,
    test_tenant
):
    """
    Contract: DELETE /admin/tenants/{id}/credentials/{provider} - No authentication

    Given: A request without authentication token
    When: Attempting to delete credentials
    Then: Returns 403 Forbidden
    """
    response = client.delete(
        f"/admin/tenants/{test_tenant.id}/credentials/openai"
    )

    assert response.status_code == 403


@pytest.mark.contract
def test_delete_tenant_credential_tenant_not_found(
    client: TestClient,
    super_admin_token: str
):
    """
    Contract: DELETE /admin/tenants/{id}/credentials/{provider} - Tenant not found

    Given: A non-existent tenant ID
    When: Attempting to delete credentials
    Then: Returns 404 Not Found
    """
    non_existent_id = str(uuid4())
    response = client.delete(
        f"/admin/tenants/{non_existent_id}/credentials/openai",
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 404


@pytest.mark.contract
def test_delete_tenant_credential_invalid_provider(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: DELETE /admin/tenants/{id}/credentials/{provider} - Invalid provider

    Given: An invalid provider name
    When: Attempting to delete credentials
    Then: Returns 422 Unprocessable Entity
    """
    response = client.delete(
        f"/admin/tenants/{test_tenant.id}/credentials/invalid_provider",
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 422


# =============================================================================
# T007 - GET /admin/tenants/{id}/credentials Tests
# =============================================================================

@pytest.mark.contract
def test_list_tenant_credentials(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: GET /admin/tenants/{id}/credentials - List credentials

    Given: Multiple credentials set for a tenant
    When: Requesting the credentials list
    Then: Returns 200 OK with all credentials (keys masked)
    """
    # Set up multiple credentials
    client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/openai",
        json={"api_key": "sk-test-openai-123"},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )
    client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/anthropic",
        json={"api_key": "sk-ant-anthropic-456"},
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    # List credentials
    response = client.get(
        f"/admin/tenants/{test_tenant.id}/credentials",
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2

    # Check that keys are masked
    providers = {cred["provider"] for cred in data}
    assert "openai" in providers
    assert "anthropic" in providers

    for cred in data:
        assert "masked_key" in cred
        assert "api_key" not in cred
        assert cred["tenant_id"] == str(test_tenant.id)


@pytest.mark.contract
def test_list_tenant_credentials_empty(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: GET /admin/tenants/{id}/credentials - Empty list

    Given: A tenant with no credentials
    When: Requesting the credentials list
    Then: Returns 200 OK with empty list
    """
    response = client.get(
        f"/admin/tenants/{test_tenant.id}/credentials",
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.contract
def test_list_tenant_credentials_no_auth(
    client: TestClient,
    test_tenant
):
    """
    Contract: GET /admin/tenants/{id}/credentials - No authentication

    Given: A request without authentication token
    When: Attempting to list credentials
    Then: Returns 403 Forbidden
    """
    response = client.get(
        f"/admin/tenants/{test_tenant.id}/credentials"
    )

    assert response.status_code == 403


@pytest.mark.contract
def test_list_tenant_credentials_tenant_not_found(
    client: TestClient,
    super_admin_token: str
):
    """
    Contract: GET /admin/tenants/{id}/credentials - Tenant not found

    Given: A non-existent tenant ID
    When: Attempting to list credentials
    Then: Returns 404 Not Found
    """
    non_existent_id = str(uuid4())
    response = client.get(
        f"/admin/tenants/{non_existent_id}/credentials",
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 404


@pytest.mark.contract
def test_list_tenant_credentials_azure_includes_metadata(
    client: TestClient,
    super_admin_token: str,
    test_tenant
):
    """
    Contract: GET /admin/tenants/{id}/credentials - Azure metadata

    Given: Azure credentials with additional metadata fields
    When: Listing credentials
    Then: Returns masked key and indicates additional fields exist (without revealing values)
    """
    # Set Azure credentials
    client.put(
        f"/admin/tenants/{test_tenant.id}/credentials/azure",
        json={
            "api_key": "azure-key-1234567890",
            "api_base": "https://my-resource.openai.azure.com",
            "api_version": "2024-02-15-preview",
            "deployment_name": "gpt-4-deployment"
        },
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    # List credentials
    response = client.get(
        f"/admin/tenants/{test_tenant.id}/credentials",
        headers={"Authorization": f"Bearer {super_admin_token}"}
    )

    assert response.status_code == 200
    data = response.json()
    azure_cred = next(c for c in data if c["provider"] == "azure")

    # Should show masked key but NOT reveal sensitive fields
    assert azure_cred["masked_key"] == "...890"
    assert "api_key" not in azure_cred
    assert "api_base" not in azure_cred
    # May include metadata count or indicator
    assert azure_cred["tenant_id"] == str(test_tenant.id)

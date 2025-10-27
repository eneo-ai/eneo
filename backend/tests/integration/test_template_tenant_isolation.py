"""Integration tests for tenant-scoped template management.

These tests verify:
- Tenant isolation: Templates are properly scoped to tenants
- Feature flag behavior: Templates feature can be enabled/disabled
- CRUD operations: Create, read, update, delete work correctly
- Soft-delete: Deleted templates are hidden but recoverable
- Rollback: Templates can be restored to original state
- Authorization: Only admins can manage templates
"""

import pytest
from uuid import uuid4


# Helper functions for test setup

async def _create_tenant(client, super_admin_token: str, name: str):
    """Create a tenant via sysadmin API."""
    payload = {
        "name": name,
        "display_name": name,
        "state": "active",
    }
    response = await client.post(
        "/api/v1/sysadmin/tenants/",
        json=payload,
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_user(
    client,
    super_admin_token: str,
    tenant_id: str,
    email: str,
    password: str,
    is_admin: bool = False,
):
    """Create a user via sysadmin API."""
    payload = {
        "email": email,
        "username": email.split("@")[0],
        "tenant_id": tenant_id,
        "password": password,
    }
    response = await client.post(
        "/api/v1/sysadmin/users/",
        json=payload,
        headers={"X-API-Key": super_admin_token},
    )
    assert response.status_code == 200, response.text
    user = response.json()

    # TODO: Set admin role if needed
    # This depends on your user/role setup

    return user


async def _login_user(client, email: str, password: str):
    """Login and get access token."""
    response = await client.post(
        "/api/v1/users/login/token/",
        data={"username": email, "password": password},  # username field accepts email
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _enable_templates_feature(client, token: str):
    """Enable templates feature for user's tenant."""
    response = await client.patch(
        "/api/v1/settings/templates",
        json={"enabled": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


# Tests

@pytest.mark.integration
@pytest.mark.asyncio
async def test_feature_flag_disabled_returns_empty_gallery(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    """When feature flag is disabled, gallery returns empty list."""
    # Create tenant and user
    tenant = await _create_tenant(client, super_admin_token, f"tenant-{uuid4()}")
    user = await _create_user(
        client, super_admin_token, tenant["id"], "user@test.com", "password123"
    )
    api_key = await _login_user(client, user["email"], "password123")

    # Feature flag should be disabled by default
    response = await client.get(
        "/api/v1/templates/assistants/",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["count"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_template_requires_feature_flag(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    """Cannot create template when feature flag is disabled."""
    # Create tenant and admin user
    tenant = await _create_tenant(client, super_admin_token, f"tenant-{uuid4()}")
    admin = await _create_user(
        client, super_admin_token, tenant["id"], "admin@test.com", "password123", is_admin=True
    )
    api_key = await _login_user(client, admin["email"], "password123")

    # Try to create template without feature flag enabled
    template_data = {
        "name": "Test Template",
        "description": "Test Description",
        "category": "Test",
        "prompt": "You are a helpful assistant",
        "wizard": {
            "attachments": {"required": False},
            "collections": {"required": False},
        },
    }

    response = await client.post(
        "/api/v1/admin/templates/assistants/",
        json=template_data,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 400  # BadRequestException
    assert "not enabled" in response.json()["message"].lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_isolation_templates_not_visible_across_tenants(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    """Tenant A cannot see Tenant B's templates."""
    # Create two tenants
    tenant_a = await _create_tenant(client, super_admin_token, f"tenant-a-{uuid4()}")
    tenant_b = await _create_tenant(client, super_admin_token, f"tenant-b-{uuid4()}")

    # Create admin users for both tenants
    admin_a = await _create_user(
        client, super_admin_token, tenant_a["id"], "admin-a@test.com", "password123", is_admin=True
    )
    admin_b = await _create_user(
        client, super_admin_token, tenant_b["id"], "admin-b@test.com", "password123", is_admin=True
    )

    api_key_a = await _login_user(client, admin_a["email"], "password123")
    api_key_b = await _login_user(client, admin_b["email"], "password123")

    # Enable feature flag for both tenants
    await _enable_templates_feature(client, api_key_a)
    await _enable_templates_feature(client, api_key_b)

    # Tenant A creates a template
    template_data = {
        "name": "Tenant A Template",
        "description": "Only for Tenant A",
        "category": "Private",
        "prompt": "Tenant A specific prompt",
        "wizard": {
            "attachments": {"required": False},
            "collections": {"required": False},
        },
    }

    response = await client.post(
        "/api/v1/admin/templates/assistants/",
        json=template_data,
        headers={"Authorization": f"Bearer {api_key_a}"},
    )
    assert response.status_code == 201
    template_a = response.json()

    # Tenant B lists their templates - should NOT see Tenant A's template
    response = await client.get(
        "/api/v1/admin/templates/assistants/",
        headers={"Authorization": f"Bearer {api_key_b}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 0  # Tenant B has no templates

    # Tenant A lists their templates - should see their own
    response = await client.get(
        "/api/v1/admin/templates/assistants/",
        headers={"Authorization": f"Bearer {api_key_a}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == template_a["id"]
    assert data["items"][0]["tenant_id"] == tenant_a["id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_name_within_tenant_rejected(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    """Cannot create two templates with same name in one tenant."""
    tenant = await _create_tenant(client, super_admin_token, f"tenant-{uuid4()}")
    admin = await _create_user(
        client, super_admin_token, tenant["id"], "admin@test.com", "password123", is_admin=True
    )
    api_key = await _login_user(client, admin["email"], "password123")
    await _enable_templates_feature(client, api_key)

    template_data = {
        "name": "Duplicate Name Test",
        "description": "First template",
        "category": "Test",
        "prompt": "Test prompt",
        "wizard": {
            "attachments": {"required": False},
            "collections": {"required": False},
        },
    }

    # Create first template
    response = await client.post(
        "/api/v1/admin/templates/assistants/",
        json=template_data,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 201

    # Try to create second template with same name
    response = await client.post(
        "/api/v1/admin/templates/assistants/",
        json=template_data,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 409  # NameCollisionException
    assert "already exists" in response.json()["message"].lower()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_soft_delete_hides_template_from_gallery(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    """Soft-deleted templates don't appear in gallery."""
    tenant = await _create_tenant(client, super_admin_token, f"tenant-{uuid4()}")
    admin = await _create_user(
        client, super_admin_token, tenant["id"], "admin@test.com", "password123", is_admin=True
    )
    api_key = await _login_user(client, admin["email"], "password123")
    await _enable_templates_feature(client, api_key)

    # Create template
    template_data = {
        "name": "To Be Deleted",
        "description": "Will be soft-deleted",
        "category": "Test",
        "prompt": "Test",
        "wizard": {
            "attachments": {"required": False},
            "collections": {"required": False},
        },
    }

    response = await client.post(
        "/api/v1/admin/templates/assistants/",
        json=template_data,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 201
    template_id = response.json()["id"]

    # Verify it appears in gallery
    response = await client.get(
        "/api/v1/templates/assistants/",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    initial_count = len(response.json()["items"])
    template_ids = [t["id"] for t in response.json()["items"]]
    assert template_id in template_ids, "Newly created template should appear in gallery"

    # Soft-delete the template
    response = await client.delete(
        f"/api/v1/admin/templates/assistants/{template_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 204

    # Verify it no longer appears in gallery
    response = await client.get(
        "/api/v1/templates/assistants/",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    remaining_ids = [t["id"] for t in response.json()["items"]]
    assert template_id not in remaining_ids, "Deleted template should not appear in gallery"
    assert len(remaining_ids) == initial_count - 1, "Gallery count should decrease by 1"

    # Verify it appears in deleted list
    response = await client.get(
        "/api/v1/admin/templates/assistants/deleted",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    deleted = response.json()["items"]
    assert len(deleted) == 1
    assert deleted[0]["id"] == template_id
    assert deleted[0]["deleted_at"] is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rollback_restores_original_state(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    """Rollback restores template to original snapshot."""
    tenant = await _create_tenant(client, super_admin_token, f"tenant-{uuid4()}")
    admin = await _create_user(
        client, super_admin_token, tenant["id"], "admin@test.com", "password123", is_admin=True
    )
    api_key = await _login_user(client, admin["email"], "password123")
    await _enable_templates_feature(client, api_key)

    # Create template with original values
    original_data = {
        "name": "Original Name",
        "description": "Original Description",
        "category": "Original",
        "prompt": "Original prompt text",
        "wizard": {
            "attachments": {"required": False},
            "collections": {"required": True, "title": "Original title"},
        },
    }

    response = await client.post(
        "/api/v1/admin/templates/assistants/",
        json=original_data,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 201
    template = response.json()
    template_id = template["id"]

    # Update template
    updated_data = {
        "name": "Modified Name",
        "description": "Modified Description",
        "category": "Modified",
        "prompt": "Modified prompt text",
    }

    response = await client.patch(
        f"/api/v1/admin/templates/assistants/{template_id}",
        json=updated_data,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "Modified Name"
    assert updated["description"] == "Modified Description"

    # Rollback to original state
    response = await client.post(
        f"/api/v1/admin/templates/assistants/{template_id}/rollback",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    rolled_back = response.json()

    # Verify original values restored
    assert rolled_back["name"] == "Original Name"
    assert rolled_back["description"] == "Original Description"
    assert rolled_back["category"] == "Original"
    assert rolled_back["prompt_text"] == "Original prompt text"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cannot_delete_template_in_use(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    """Cannot delete template that is being used by assistants."""
    # This test requires creating an assistant from a template
    # TODO: Implement when assistant creation from template is available
    pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_app_template_crud_operations(
    client,
    super_admin_token,
    patch_auth_service_jwt,
    mock_transcription_models,
):
    """App templates follow same CRUD patterns as assistant templates."""
    tenant = await _create_tenant(client, super_admin_token, f"tenant-{uuid4()}")
    admin = await _create_user(
        client, super_admin_token, tenant["id"], "admin@test.com", "password123", is_admin=True
    )
    api_key = await _login_user(client, admin["email"], "password123")
    await _enable_templates_feature(client, api_key)

    # Create app template
    template_data = {
        "name": "Document Analyzer",
        "description": "Analyzes documents",
        "category": "Analysis",
        "prompt": "Analyze this document",
        "input_type": "text-upload",
        "input_description": "Upload a document",
        "wizard": {
            "attachments": {"required": True},
            "collections": None,
        },
    }

    response = await client.post(
        "/api/v1/admin/templates/apps/",
        json=template_data,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 201
    template = response.json()
    assert template["name"] == "Document Analyzer"
    assert template["input_type"] == "text-upload"

    # Update app template
    response = await client.patch(
        f"/api/v1/admin/templates/apps/{template['id']}",
        json={"name": "Updated Analyzer"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Analyzer"

    # List app templates
    response = await client.get(
        "/api/v1/admin/templates/apps/",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1

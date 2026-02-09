"""
Integration tests for sysadmin AI models CRUD endpoints.

Tests the system-wide AI model management endpoints that require super admin API key:
- POST /sysadmin/completion-models/create
- POST /sysadmin/completion-models/{id}/metadata
- DELETE /sysadmin/completion-models/{id}
- POST /sysadmin/embedding-models/create
- POST /sysadmin/embedding-models/{id}/metadata
- DELETE /sysadmin/embedding-models/{id}
"""
import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import CompletionModels, EmbeddingModels


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_model_success(client, super_admin_token, db_container):
    """Test creating a new completion model with valid data."""
    model_data = {
        "name": "gpt-4-test",
        "nickname": "GPT-4 Test",
        "family": "openai",
        "token_limit": 8000,
        "is_deprecated": False,
        "stability": "stable",
        "hosting": "usa",
        "open_source": False,
        "description": "Test model for integration testing",
        "org": "OpenAI",
        "vision": True,
        "reasoning": False,
        "base_url": "https://api.openai.com/v1",
        "litellm_model_name": "gpt-4",
    }

    response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers={"X-API-Key": super_admin_token},
        json=model_data,
    )

    assert response.status_code == 200
    data = response.json()

    # Verify response structure (CompletionModelSparse)
    assert data["name"] == "gpt-4-test"
    assert data["nickname"] == "GPT-4 Test"
    assert data["family"] == "openai"
    assert data["token_limit"] == 8000
    assert data["vision"] is True
    assert data["reasoning"] is False
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data

    # Verify tenant-specific fields are NOT in response (Sparse model)
    assert "is_org_enabled" not in data
    assert "is_org_default" not in data
    assert "can_access" not in data
    assert "is_locked" not in data
    assert "security_classification" not in data

    # Verify model was created in database
    async with db_container() as container:
        session = container.session()
        stmt = sa.select(CompletionModels).where(CompletionModels.name == "gpt-4-test")
        result = await session.execute(stmt)
        db_model = result.scalar_one_or_none()

        assert db_model is not None
        assert db_model.name == "gpt-4-test"
        assert db_model.nickname == "GPT-4 Test"
        assert db_model.token_limit == 8000


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_model_without_auth(client):
    """Test that creating a completion model without authentication fails."""
    model_data = {
        "name": "test-model",
        "nickname": "Test Model",
        "family": "openai",
        "token_limit": 8000,
        "is_deprecated": False,
        "stability": "stable",
        "hosting": "usa",
        "vision": False,
        "reasoning": False,
    }

    response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        json=model_data,
    )

    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_model_with_invalid_auth(client):
    """Test that creating a completion model with invalid API key fails."""
    model_data = {
        "name": "test-model",
        "nickname": "Test Model",
        "family": "openai",
        "token_limit": 8000,
        "is_deprecated": False,
        "stability": "stable",
        "hosting": "usa",
        "vision": False,
        "reasoning": False,
    }

    response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers={"X-API-Key": "invalid-key"},
        json=model_data,
    )

    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_completion_model_metadata(client, super_admin_token, db_container):
    """Test updating an existing completion model's metadata."""
    # First create a model
    create_data = {
        "name": "gpt-3.5-turbo",
        "nickname": "GPT-3.5 Turbo",
        "family": "openai",
        "token_limit": 4000,
        "is_deprecated": False,
        "stability": "stable",
        "hosting": "usa",
        "vision": False,
        "reasoning": False,
    }

    create_response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers={"X-API-Key": super_admin_token},
        json=create_data,
    )
    assert create_response.status_code == 200
    model_id = create_response.json()["id"]

    # Update the model
    update_data = {
        "nickname": "GPT-3.5 Turbo Updated",
        "description": "Updated description",
        "is_deprecated": True,
        "token_limit": 16000,
    }

    response = await client.put(
        f"/api/v1/sysadmin/completion-models/{model_id}/metadata",
        headers={"X-API-Key": super_admin_token},
        json=update_data,
    )

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == model_id
    assert data["nickname"] == "GPT-3.5 Turbo Updated"
    assert data["description"] == "Updated description"
    assert data["is_deprecated"] is True
    assert data["token_limit"] == 16000

    # Verify in database
    async with db_container() as container:
        session = container.session()
        stmt = sa.select(CompletionModels).where(CompletionModels.id == model_id)
        result = await session.execute(stmt)
        db_model = result.scalar_one()

        assert db_model.nickname == "GPT-3.5 Turbo Updated"
        assert db_model.description == "Updated description"
        assert db_model.is_deprecated is True
        assert db_model.token_limit == 16000


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_nonexistent_completion_model(client, super_admin_token):
    """Test that updating a non-existent model returns 404."""
    from uuid import uuid4

    fake_id = str(uuid4())
    update_data = {
        "nickname": "Should Fail",
        "description": "This should not work",
    }

    response = await client.put(
        f"/api/v1/sysadmin/completion-models/{fake_id}/metadata",
        headers={"X-API-Key": super_admin_token},
        json=update_data,
    )

    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_completion_model(client, super_admin_token, db_container):
    """Test deleting a completion model."""
    # First create a model
    create_data = {
        "name": "model-to-delete",
        "nickname": "Model to Delete",
        "family": "openai",
        "token_limit": 8000,
        "is_deprecated": False,
        "stability": "stable",
        "hosting": "usa",
        "vision": False,
        "reasoning": False,
    }

    create_response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers={"X-API-Key": super_admin_token},
        json=create_data,
    )
    assert create_response.status_code == 200
    model_id = create_response.json()["id"]

    # Delete the model
    response = await client.delete(
        f"/api/v1/sysadmin/completion-models/{model_id}",
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200

    # Verify model was deleted from database
    async with db_container() as container:
        session = container.session()
        stmt = sa.select(CompletionModels).where(CompletionModels.id == model_id)
        result = await session.execute(stmt)
        db_model = result.scalar_one_or_none()

        assert db_model is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_nonexistent_completion_model(client, super_admin_token):
    """Test that deleting a non-existent model succeeds (idempotent delete)."""
    from uuid import uuid4

    fake_id = str(uuid4())

    response = await client.delete(
        f"/api/v1/sysadmin/completion-models/{fake_id}",
        headers={"X-API-Key": super_admin_token},
    )

    # Note: Current implementation returns 200 even for non-existent models (idempotent)
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_model_with_duplicate_name(client, super_admin_token):
    """Test that duplicate model names are allowed (unique constraint removed)."""
    model_data = {
        "name": "duplicate-name-test",
        "nickname": "First Model",
        "family": "openai",
        "token_limit": 8000,
        "is_deprecated": False,
        "stability": "stable",
        "hosting": "usa",
        "vision": False,
        "reasoning": False,
    }

    # Create first model
    response1 = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers={"X-API-Key": super_admin_token},
        json=model_data,
    )
    assert response1.status_code == 200

    # Create second model with same name (should succeed)
    model_data["nickname"] = "Second Model"
    response2 = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers={"X-API-Key": super_admin_token},
        json=model_data,
    )
    assert response2.status_code == 200

    # Verify they have different IDs
    assert response1.json()["id"] != response2.json()["id"]


# Embedding Models Tests


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_embedding_model_success(client, super_admin_token, db_container):
    """Test creating a new embedding model with valid data."""
    model_data = {
        "name": "text-embedding-ada-002",
        "family": "openai",
        "is_deprecated": False,
        "open_source": False,
        "dimensions": 1536,
        "max_input": 8191,
        "max_batch_size": 100,
        "stability": "stable",
        "hosting": "usa",
        "description": "Test embedding model",
        "org": "OpenAI",
        "litellm_model_name": "text-embedding-ada-002",
    }

    response = await client.post(
        "/api/v1/sysadmin/embedding-models/create",
        headers={"X-API-Key": super_admin_token},
        json=model_data,
    )

    assert response.status_code == 200
    data = response.json()

    # Verify response structure (EmbeddingModelSparse)
    assert data["name"] == "text-embedding-ada-002"
    assert data["family"] == "openai"
    assert data["dimensions"] == 1536
    assert data["max_input"] == 8191
    assert data["max_batch_size"] == 100
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data

    # Verify tenant-specific fields are NOT in response (Sparse model)
    assert "is_org_enabled" not in data
    assert "can_access" not in data
    assert "is_locked" not in data

    # Verify model was created in database
    async with db_container() as container:
        session = container.session()
        stmt = sa.select(EmbeddingModels).where(
            EmbeddingModels.name == "text-embedding-ada-002"
        )
        result = await session.execute(stmt)
        db_model = result.scalar_one_or_none()

        assert db_model is not None
        assert db_model.name == "text-embedding-ada-002"
        assert db_model.dimensions == 1536


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_embedding_model_without_auth(client):
    """Test that creating an embedding model without authentication fails."""
    model_data = {
        "name": "test-embedding",
        "family": "openai",
        "is_deprecated": False,
        "open_source": False,
        "stability": "stable",
        "hosting": "usa",
    }

    response = await client.post(
        "/api/v1/sysadmin/embedding-models/create",
        json=model_data,
    )

    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_embedding_model_metadata(client, super_admin_token, db_container):
    """Test updating an existing embedding model's metadata."""
    # First create a model
    create_data = {
        "name": "text-embedding-3-small",
        "family": "openai",
        "is_deprecated": False,
        "open_source": False,
        "dimensions": 1536,
        "stability": "stable",
        "hosting": "usa",
    }

    create_response = await client.post(
        "/api/v1/sysadmin/embedding-models/create",
        headers={"X-API-Key": super_admin_token},
        json=create_data,
    )
    assert create_response.status_code == 200
    model_id = create_response.json()["id"]

    # Update the model
    update_data = {
        "description": "Updated embedding model description",
        "is_deprecated": True,
        "dimensions": 512,
    }

    response = await client.put(
        f"/api/v1/sysadmin/embedding-models/{model_id}/metadata",
        headers={"X-API-Key": super_admin_token},
        json=update_data,
    )

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == model_id
    assert data["description"] == "Updated embedding model description"
    assert data["is_deprecated"] is True
    assert data["dimensions"] == 512

    # Verify in database
    async with db_container() as container:
        session = container.session()
        stmt = sa.select(EmbeddingModels).where(EmbeddingModels.id == model_id)
        result = await session.execute(stmt)
        db_model = result.scalar_one()

        assert db_model.description == "Updated embedding model description"
        assert db_model.is_deprecated is True
        assert db_model.dimensions == 512


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_nonexistent_embedding_model(client, super_admin_token):
    """Test that updating a non-existent embedding model returns 404."""
    from uuid import uuid4

    fake_id = str(uuid4())
    update_data = {
        "description": "Should Fail",
    }

    response = await client.put(
        f"/api/v1/sysadmin/embedding-models/{fake_id}/metadata",
        headers={"X-API-Key": super_admin_token},
        json=update_data,
    )

    assert response.status_code == 404


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_embedding_model(client, super_admin_token, db_container):
    """Test deleting an embedding model."""
    # First create a model
    create_data = {
        "name": "embedding-to-delete",
        "family": "openai",
        "is_deprecated": False,
        "open_source": False,
        "stability": "stable",
        "hosting": "usa",
    }

    create_response = await client.post(
        "/api/v1/sysadmin/embedding-models/create",
        headers={"X-API-Key": super_admin_token},
        json=create_data,
    )
    assert create_response.status_code == 200
    model_id = create_response.json()["id"]

    # Delete the model
    response = await client.delete(
        f"/api/v1/sysadmin/embedding-models/{model_id}",
        headers={"X-API-Key": super_admin_token},
    )

    assert response.status_code == 200

    # Verify model was deleted from database
    async with db_container() as container:
        session = container.session()
        stmt = sa.select(EmbeddingModels).where(EmbeddingModels.id == model_id)
        result = await session.execute(stmt)
        db_model = result.scalar_one_or_none()

        assert db_model is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_nonexistent_embedding_model(client, super_admin_token):
    """Test that deleting a non-existent embedding model succeeds (idempotent delete)."""
    from uuid import uuid4

    fake_id = str(uuid4())

    response = await client.delete(
        f"/api/v1/sysadmin/embedding-models/{fake_id}",
        headers={"X-API-Key": super_admin_token},
    )

    # Note: Current implementation returns 200 even for non-existent models (idempotent)
    assert response.status_code == 200


# Validation Tests


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_model_missing_required_fields(client, super_admin_token):
    """Test that creating a model with missing required fields fails."""
    incomplete_data = {
        "name": "incomplete-model",
        # Missing many required fields like family, token_limit, etc.
    }

    response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers={"X-API-Key": super_admin_token},
        json=incomplete_data,
    )

    assert response.status_code == 422  # Unprocessable Entity


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_completion_model_accepts_custom_family(client, super_admin_token):
    """Test that creating a model with custom family string is accepted.

    With per-tenant model architecture, family is Union[CompletionModelFamily, str]
    to allow tenant-specific models with custom family values.
    """
    custom_family_data = {
        "name": "custom-family-model",
        "nickname": "Custom Family",
        "family": "custom_provider",  # Custom family string (now allowed)
        "token_limit": 8000,
        "is_deprecated": False,
        "stability": "stable",
        "hosting": "usa",
        "vision": False,
        "reasoning": False,
    }

    response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers={"X-API-Key": super_admin_token},
        json=custom_family_data,
    )

    assert response.status_code == 200  # Now accepts custom family strings


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_embedding_model_invalid_batch_size(client, super_admin_token):
    """Test that creating an embedding model with invalid batch size fails."""
    invalid_data = {
        "name": "invalid-batch-size",
        "family": "openai",
        "is_deprecated": False,
        "open_source": False,
        "stability": "stable",
        "hosting": "usa",
        "max_batch_size": 500,  # Exceeds max of 256
    }

    response = await client.post(
        "/api/v1/sysadmin/embedding-models/create",
        headers={"X-API-Key": super_admin_token},
        json=invalid_data,
    )

    assert response.status_code == 422  # Validation error


@pytest.mark.integration
@pytest.mark.asyncio
async def test_partial_update_completion_model(client, super_admin_token):
    """Test that partial updates work (only update specified fields)."""
    # Create a model
    create_data = {
        "name": "partial-update-test",
        "nickname": "Original Nickname",
        "family": "openai",
        "token_limit": 8000,
        "is_deprecated": False,
        "stability": "stable",
        "hosting": "usa",
        "description": "Original description",
        "vision": False,
        "reasoning": False,
    }

    create_response = await client.post(
        "/api/v1/sysadmin/completion-models/create",
        headers={"X-API-Key": super_admin_token},
        json=create_data,
    )
    assert create_response.status_code == 200
    model_id = create_response.json()["id"]

    # Update only the description
    update_data = {
        "description": "Updated description only",
    }

    response = await client.put(
        f"/api/v1/sysadmin/completion-models/{model_id}/metadata",
        headers={"X-API-Key": super_admin_token},
        json=update_data,
    )

    assert response.status_code == 200
    data = response.json()

    # Verify only description changed, other fields unchanged
    assert data["description"] == "Updated description only"
    assert data["nickname"] == "Original Nickname"  # Unchanged
    assert data["token_limit"] == 8000  # Unchanged

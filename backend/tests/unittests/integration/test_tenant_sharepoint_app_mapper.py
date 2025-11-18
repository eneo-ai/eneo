"""Unit tests for TenantSharePointAppMapper - encryption/decryption.

Tests the automatic encryption and decryption of client secrets when converting
between domain entities and database models.
"""

from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
from intric.integration.infrastructure.mappers.tenant_sharepoint_app_mapper import (
    TenantSharePointAppMapper,
)


@pytest.fixture
def mock_encryption_service():
    """Create a mock EncryptionService."""
    service = MagicMock()
    # Mock encrypt to add prefix
    service.encrypt.side_effect = lambda value: f"enc:fernet:v1:{value}:encrypted"
    # Mock decrypt to remove prefix
    service.decrypt.side_effect = lambda value: value.replace("enc:fernet:v1:", "").replace(":encrypted", "")
    return service


@pytest.fixture
def mapper(mock_encryption_service):
    """Create a TenantSharePointAppMapper with mocked encryption."""
    return TenantSharePointAppMapper(encryption_service=mock_encryption_service)


@pytest.fixture
def sample_entity():
    """Create a sample TenantSharePointApp entity."""
    return TenantSharePointApp(
        id=uuid4(),
        tenant_id=uuid4(),
        client_id="azure-client-id-123",
        client_secret="azure-client-secret-456",
        tenant_domain="contoso.onmicrosoft.com",
        is_active=True,
        certificate_path=None,
        created_by=uuid4(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


@pytest.fixture
def sample_db_model(sample_entity):
    """Create a sample TenantSharePointAppDBModel."""
    db_model = MagicMock()
    db_model.id = sample_entity.id
    db_model.tenant_id = sample_entity.tenant_id
    db_model.client_id = sample_entity.client_id
    db_model.client_secret_encrypted = "enc:fernet:v1:azure-client-secret-456:encrypted"
    db_model.tenant_domain = sample_entity.tenant_domain
    db_model.is_active = sample_entity.is_active
    db_model.certificate_path = sample_entity.certificate_path
    db_model.created_by = sample_entity.created_by
    db_model.created_at = sample_entity.created_at
    db_model.updated_at = sample_entity.updated_at
    return db_model


def test_to_db_dict_encrypts_client_secret(mapper, mock_encryption_service, sample_entity):
    """to_db_dict() encrypts client_secret before database storage."""
    db_dict = mapper.to_db_dict(sample_entity)

    # Verify encryption service was called
    mock_encryption_service.encrypt.assert_called_once_with("azure-client-secret-456")

    # Verify encrypted value is in db_dict
    assert db_dict["client_secret_encrypted"] == "enc:fernet:v1:azure-client-secret-456:encrypted"

    # Verify plaintext secret is NOT in db_dict
    assert "client_secret" not in db_dict


def test_to_db_dict_encrypted_value_differs_from_plaintext(mapper, sample_entity):
    """Encrypted value differs from plaintext."""
    db_dict = mapper.to_db_dict(sample_entity)

    encrypted_value = db_dict["client_secret_encrypted"]

    # Encrypted value should not equal plaintext
    assert encrypted_value != sample_entity.client_secret


def test_to_db_dict_has_correct_format(mapper, mock_encryption_service, sample_entity):
    """Encrypted value has expected format prefix."""
    db_dict = mapper.to_db_dict(sample_entity)

    encrypted_value = db_dict["client_secret_encrypted"]

    # Verify format (in this mock: "enc:fernet:v1:...")
    assert encrypted_value.startswith("enc:fernet:v1:")


def test_to_db_dict_includes_all_fields(mapper, sample_entity):
    """to_db_dict() includes all entity fields."""
    db_dict = mapper.to_db_dict(sample_entity)

    # Verify all expected fields
    assert db_dict["id"] == sample_entity.id
    assert db_dict["tenant_id"] == sample_entity.tenant_id
    assert db_dict["client_id"] == sample_entity.client_id
    assert "client_secret_encrypted" in db_dict
    assert db_dict["tenant_domain"] == sample_entity.tenant_domain
    assert db_dict["is_active"] == sample_entity.is_active
    assert db_dict["certificate_path"] == sample_entity.certificate_path
    assert db_dict["created_by"] == sample_entity.created_by


def test_to_db_dict_includes_timestamps_when_present(mapper, sample_entity):
    """to_db_dict() includes timestamps if they exist."""
    db_dict = mapper.to_db_dict(sample_entity)

    assert "created_at" in db_dict
    assert "updated_at" in db_dict
    assert db_dict["created_at"] == sample_entity.created_at
    assert db_dict["updated_at"] == sample_entity.updated_at


def test_to_db_dict_excludes_timestamps_when_none(mapper, sample_entity):
    """to_db_dict() excludes timestamps if they are None."""
    # Create entity without timestamps (new entity)
    sample_entity.created_at = None
    sample_entity.updated_at = None

    db_dict = mapper.to_db_dict(sample_entity)

    # Timestamps should NOT be in dict (let DB use defaults)
    assert "created_at" not in db_dict
    assert "updated_at" not in db_dict


def test_to_entity_decrypts_client_secret(mapper, mock_encryption_service, sample_db_model):
    """to_entity() decrypts client_secret after database retrieval."""
    entity = mapper.to_entity(sample_db_model)

    # Verify decryption service was called
    mock_encryption_service.decrypt.assert_called_once_with(
        "enc:fernet:v1:azure-client-secret-456:encrypted"
    )

    # Verify decrypted secret is in entity
    assert entity.client_secret == "azure-client-secret-456"


def test_to_entity_returns_correct_type(mapper, sample_db_model):
    """to_entity() returns TenantSharePointApp instance."""
    entity = mapper.to_entity(sample_db_model)

    assert isinstance(entity, TenantSharePointApp)


def test_to_entity_includes_all_fields(mapper, sample_db_model):
    """to_entity() includes all database fields."""
    entity = mapper.to_entity(sample_db_model)

    assert entity.id == sample_db_model.id
    assert entity.tenant_id == sample_db_model.tenant_id
    assert entity.client_id == sample_db_model.client_id
    assert entity.client_secret == "azure-client-secret-456"  # Decrypted
    assert entity.tenant_domain == sample_db_model.tenant_domain
    assert entity.is_active == sample_db_model.is_active
    assert entity.certificate_path == sample_db_model.certificate_path
    assert entity.created_by == sample_db_model.created_by
    assert entity.created_at == sample_db_model.created_at
    assert entity.updated_at == sample_db_model.updated_at


def test_encryption_decryption_roundtrip(mapper, mock_encryption_service, sample_entity):
    """Entity → DB Dict → Entity preserves data integrity."""
    # Convert entity to DB dict (encrypts)
    db_dict = mapper.to_db_dict(sample_entity)

    # Simulate DB model (would normally be created by SQLAlchemy)
    db_model = MagicMock()
    db_model.id = db_dict["id"]
    db_model.tenant_id = db_dict["tenant_id"]
    db_model.client_id = db_dict["client_id"]
    db_model.client_secret_encrypted = db_dict["client_secret_encrypted"]
    db_model.tenant_domain = db_dict["tenant_domain"]
    db_model.is_active = db_dict["is_active"]
    db_model.certificate_path = db_dict["certificate_path"]
    db_model.created_by = db_dict["created_by"]
    db_model.created_at = db_dict.get("created_at")
    db_model.updated_at = db_dict.get("updated_at")

    # Convert back to entity (decrypts)
    restored_entity = mapper.to_entity(db_model)

    # Verify all data preserved
    assert restored_entity.id == sample_entity.id
    assert restored_entity.tenant_id == sample_entity.tenant_id
    assert restored_entity.client_id == sample_entity.client_id
    assert restored_entity.client_secret == sample_entity.client_secret  # Critical: secret restored
    assert restored_entity.tenant_domain == sample_entity.tenant_domain
    assert restored_entity.is_active == sample_entity.is_active


def test_empty_string_client_secret_handled(mapper, mock_encryption_service):
    """Empty string client_secret is handled correctly."""
    entity = TenantSharePointApp(
        id=uuid4(),
        tenant_id=uuid4(),
        client_id="client-123",
        client_secret="",  # Empty string
        tenant_domain="contoso.onmicrosoft.com",
        is_active=True,
        certificate_path=None,
        created_by=uuid4(),
        created_at=None,
        updated_at=None,
    )

    mapper.to_db_dict(entity)

    # Should still call encrypt (even for empty string)
    mock_encryption_service.encrypt.assert_called_once_with("")


def test_certificate_path_preserved(mapper):
    """Certificate path is preserved through mapping."""
    entity = TenantSharePointApp(
        id=uuid4(),
        tenant_id=uuid4(),
        client_id="client-123",
        client_secret="secret-456",
        tenant_domain="contoso.onmicrosoft.com",
        is_active=True,
        certificate_path="/path/to/cert.pem",
        created_by=uuid4(),
        created_at=None,
        updated_at=None,
    )

    db_dict = mapper.to_db_dict(entity)

    assert db_dict["certificate_path"] == "/path/to/cert.pem"


def test_inactive_app_preserved(mapper):
    """is_active=False is preserved through mapping."""
    entity = TenantSharePointApp(
        id=uuid4(),
        tenant_id=uuid4(),
        client_id="client-123",
        client_secret="secret-456",
        tenant_domain="contoso.onmicrosoft.com",
        is_active=False,  # Inactive
        certificate_path=None,
        created_by=uuid4(),
        created_at=None,
        updated_at=None,
    )

    db_dict = mapper.to_db_dict(entity)

    assert db_dict["is_active"] is False


def test_to_entities_converts_multiple_models(mapper, sample_db_model):
    """to_entities() converts list of DB models to entities."""
    # Create multiple DB models
    db_model_1 = sample_db_model
    db_model_2 = MagicMock()
    db_model_2.id = uuid4()
    db_model_2.tenant_id = uuid4()
    db_model_2.client_id = "client-2"
    db_model_2.client_secret_encrypted = "enc:fernet:v1:secret-2:encrypted"
    db_model_2.tenant_domain = "tenant2.onmicrosoft.com"
    db_model_2.is_active = True
    db_model_2.certificate_path = None
    db_model_2.created_by = uuid4()
    db_model_2.created_at = datetime.utcnow()
    db_model_2.updated_at = datetime.utcnow()

    # Convert list
    entities = mapper.to_entities([db_model_1, db_model_2])

    # Verify
    assert len(entities) == 2
    assert all(isinstance(e, TenantSharePointApp) for e in entities)
    assert entities[0].id == db_model_1.id
    assert entities[1].id == db_model_2.id


def test_to_entities_empty_list(mapper):
    """to_entities() handles empty list."""
    entities = mapper.to_entities([])

    assert entities == []


def test_encryption_service_called_with_correct_value(mapper, mock_encryption_service, sample_entity):
    """Encryption service is called with the exact plaintext secret."""
    mapper.to_db_dict(sample_entity)

    # Verify encryption was called with exact value
    mock_encryption_service.encrypt.assert_called_once_with("azure-client-secret-456")


def test_decryption_service_called_with_correct_value(mapper, mock_encryption_service, sample_db_model):
    """Decryption service is called with the exact encrypted value."""
    mapper.to_entity(sample_db_model)

    # Verify decryption was called with exact encrypted value
    mock_encryption_service.decrypt.assert_called_once_with(
        "enc:fernet:v1:azure-client-secret-456:encrypted"
    )

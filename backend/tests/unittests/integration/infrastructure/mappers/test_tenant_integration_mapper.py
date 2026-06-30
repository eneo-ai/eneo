import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.infrastructure.mappers.tenant_integration_mapper import (
    TenantIntegrationMapper,
)


class TestTenantIntegrationMapper(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.mapper = TenantIntegrationMapper()

        # Sample tenant integration data
        self.tenant_integration_id = uuid4()
        self.tenant_id = uuid4()

        # Create mock integration
        self.integration_mock = MagicMock()
        self.integration_mock.id = uuid4()
        self.integration_mock.name = "Test Integration"
        self.integration_mock.description = "Test Description"
        self.integration_mock.integration_type = "confluence"

    def test_to_db_dict(self):
        """Test mapping from domain entity to DB dictionary."""
        # Create a domain entity
        tenant_integration = TenantIntegration(
            id=self.tenant_integration_id,
            tenant_id=self.tenant_id,
            integration=self.integration_mock,
        )

        # Map to DB dictionary
        db_dict = self.mapper.to_db_dict(tenant_integration)

        # Assertions
        self.assertEqual(db_dict["tenant_id"], self.tenant_id)
        self.assertEqual(db_dict["integration_id"], self.integration_mock.id)

        # Ensure ID is not in the dictionary (as it should be handled by SQLAlchemy)
        self.assertNotIn("id", db_dict)

    @patch(
        "eneo.integration.domain.factories.tenant_integration_factory.TenantIntegrationFactory.create_entity"  # noqa
    )
    def test_to_entity(self, mock_create_entity):
        """Test mapping from DB model to domain entity using factory."""
        # Create a mock DB model
        db_model = MagicMock()
        db_model.id = self.tenant_integration_id
        db_model.tenant_id = self.tenant_id
        db_model.integration = self.integration_mock

        # Create a mock entity to be returned by the factory
        mock_entity = TenantIntegration(
            id=self.tenant_integration_id,
            tenant_id=self.tenant_id,
            integration=self.integration_mock,
        )
        mock_create_entity.return_value = mock_entity

        # Map to entity
        entity = self.mapper.to_entity(db_model)

        # Assert factory was called with db_model
        mock_create_entity.assert_called_once_with(record=db_model)

        # Assert returned entity is what we expect
        self.assertEqual(entity, mock_entity)

    @patch(
        "eneo.integration.domain.factories.tenant_integration_factory.TenantIntegrationFactory.create_entities"  # noqa
    )
    def test_to_entities(self, mock_create_entities):
        """Test mapping from DB models to domain entities using factory."""
        # Create mock DB models
        db_models = [MagicMock() for _ in range(3)]

        # Create mock entities to be returned by the factory
        mock_entities = [
            TenantIntegration(
                id=uuid4(), tenant_id=uuid4(), integration=self.integration_mock
            )
            for _ in range(3)
        ]
        mock_create_entities.return_value = mock_entities

        # Map to entities
        entities = self.mapper.to_entities(db_models)

        # Assert factory was called with db_models
        mock_create_entities.assert_called_once_with(records=db_models)

        # Assert returned entities are what we expect
        self.assertEqual(entities, mock_entities)


if __name__ == "__main__":
    unittest.main()

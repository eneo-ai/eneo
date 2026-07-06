import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from eneo.integration.domain.entities.integration import Integration
from eneo.integration.infrastructure.mappers.integration_mapper import (
    IntegrationMapper,
)


class TestIntegrationMapper(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.mapper = IntegrationMapper()

        # Sample integration data
        self.integration_id = uuid4()
        self.integration_name = "Test Integration"
        self.integration_description = "Test Description"
        self.integration_type = "confluence"

    def test_to_db_dict(self):
        """Test mapping from domain entity to DB dictionary."""
        # Create a domain entity
        integration = Integration(
            id=self.integration_id,
            name=self.integration_name,
            description=self.integration_description,
            integration_type=self.integration_type,
        )

        # Map to DB dictionary
        db_dict = self.mapper.to_db_dict(integration)

        # Assertions
        self.assertEqual(db_dict["name"], self.integration_name)
        self.assertEqual(db_dict["description"], self.integration_description)
        self.assertEqual(db_dict["integration_type"], self.integration_type)

        # Ensure ID is not in the dictionary (as it should be handled by SQLAlchemy)
        self.assertNotIn("id", db_dict)

    @patch(
        "eneo.integration.domain.factories.integration_factory.IntegrationFactory.create_entity"  # noqa
    )
    def test_to_entity(self, mock_create_entity):
        """Test mapping from DB model to domain entity using factory."""
        # Create a mock DB model
        db_model = MagicMock()
        db_model.id = self.integration_id
        db_model.name = self.integration_name
        db_model.description = self.integration_description
        db_model.integration_type = self.integration_type

        # Create a mock entity to be returned by the factory
        mock_entity = Integration(
            id=self.integration_id,
            name=self.integration_name,
            description=self.integration_description,
            integration_type=self.integration_type,
        )
        mock_create_entity.return_value = mock_entity

        # Map to entity
        entity = self.mapper.to_entity(db_model)

        # Assert factory was called with db_model
        mock_create_entity.assert_called_once_with(record=db_model)

        # Assert returned entity is what we expect
        self.assertEqual(entity, mock_entity)

    @patch(
        "eneo.integration.domain.factories.integration_factory.IntegrationFactory.create_entities"  # noqa
    )
    def test_to_entities(self, mock_create_entities):
        """Test mapping from DB models to domain entities using factory."""
        # Create mock DB models
        db_models = [MagicMock() for _ in range(3)]

        # Create mock entities to be returned by the factory
        mock_entities = [
            Integration(
                id=uuid4(),
                name=f"Test Integration {i}",
                description=f"Test Description {i}",
                integration_type="confluence" if i % 2 == 0 else "sharepoint",
            )
            for i in range(3)
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

import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from eneo.integration.domain.entities.user_integration import UserIntegration
from eneo.integration.infrastructure.mappers.user_integration_mapper import (
    UserIntegrationMapper,
)


class TestUserIntegrationMapper(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.mapper = UserIntegrationMapper()

        # Sample user integration data
        self.user_integration_id = uuid4()
        self.user_id = uuid4()
        self.authenticated = True

        # Create mock tenant integration
        self.tenant_integration_mock = MagicMock()
        self.tenant_integration_mock.id = uuid4()
        self.tenant_integration_mock.tenant_id = uuid4()

    def test_to_db_dict(self):
        """Test mapping from domain entity to DB dictionary."""
        # Create a domain entity
        user_integration = UserIntegration(
            id=self.user_integration_id,
            user_id=self.user_id,
            tenant_integration=self.tenant_integration_mock,
            authenticated=self.authenticated,
        )

        # Map to DB dictionary
        db_dict = self.mapper.to_db_dict(user_integration)

        # Assertions
        self.assertEqual(db_dict["user_id"], self.user_id)
        self.assertEqual(db_dict["tenant_id"], self.tenant_integration_mock.tenant_id)
        self.assertEqual(
            db_dict["tenant_integration_id"], self.tenant_integration_mock.id
        )
        self.assertEqual(db_dict["authenticated"], self.authenticated)

        # Ensure ID is not in the dictionary (as it should be handled by SQLAlchemy)
        self.assertNotIn("id", db_dict)

    @patch(
        "eneo.integration.domain.factories.user_integration_factory.UserIntegrationFactory.create_entity"  # noqa
    )
    def test_to_entity(self, mock_create_entity):
        """Test mapping from DB model to domain entity using factory."""
        # Create a mock DB model
        db_model = MagicMock()
        db_model.id = self.user_integration_id
        db_model.user_id = self.user_id
        db_model.tenant_integration = self.tenant_integration_mock
        db_model.authenticated = self.authenticated

        # Create a mock entity to be returned by the factory
        mock_entity = UserIntegration(
            id=self.user_integration_id,
            user_id=self.user_id,
            tenant_integration=self.tenant_integration_mock,
            authenticated=self.authenticated,
        )
        mock_create_entity.return_value = mock_entity

        # Map to entity
        entity = self.mapper.to_entity(db_model)

        # Assert factory was called with db_model
        mock_create_entity.assert_called_once_with(record=db_model)

        # Assert returned entity is what we expect
        self.assertEqual(entity, mock_entity)

    @patch(
        "eneo.integration.domain.factories.user_integration_factory.UserIntegrationFactory.create_entities"  # noqa
    )
    def test_to_entities(self, mock_create_entities):
        """Test mapping from DB models to domain entities using factory."""
        # Create mock DB models
        db_models = [MagicMock() for _ in range(3)]

        # Create mock entities to be returned by the factory
        mock_entities = [
            UserIntegration(
                id=uuid4(),
                user_id=uuid4(),
                tenant_integration=self.tenant_integration_mock,
                authenticated=bool(i % 2),  # Alternate between True and False
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

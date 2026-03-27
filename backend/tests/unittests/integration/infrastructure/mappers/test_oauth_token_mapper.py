import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from eneo.integration.domain.entities.oauth_token import ConfluenceToken
from eneo.integration.infrastructure.mappers.oauth_token_mapper import (
    OauthTokenMapper,
)
from eneo.integration.presentation.models import IntegrationType


class TestOauthTokenMapper(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.mapper = OauthTokenMapper()

        # Sample OAuth token data
        self.token_id = uuid4()
        self.access_token = "test_access_token"
        self.refresh_token = "test_refresh_token"
        self.token_type = IntegrationType.Confluence
        self.resources = [{"id": "cloud123", "url": "https://example.atlassian.com"}]

        # Create mock user integration
        self.user_integration_mock = MagicMock()
        self.user_integration_mock.id = uuid4()

    def test_to_db_dict(self):
        """Test mapping from domain entity to DB dictionary."""
        # Create a domain entity (using ConfluenceToken as a concrete implementation)
        token = ConfluenceToken(
            id=self.token_id,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            token_type=self.token_type,
            user_integration=self.user_integration_mock,
            resources=self.resources,
        )

        # Map to DB dictionary
        db_dict = self.mapper.to_db_dict(token)

        # Assertions
        self.assertEqual(db_dict["access_token"], self.access_token)
        self.assertEqual(db_dict["refresh_token"], self.refresh_token)
        self.assertEqual(db_dict["token_type"], self.token_type.value)
        self.assertEqual(db_dict["user_integration_id"], self.user_integration_mock.id)
        self.assertEqual(db_dict["resources"], self.resources)

        # Ensure ID is not in the dictionary (as it should be handled by SQLAlchemy)
        self.assertNotIn("id", db_dict)

    @patch(
        "eneo.integration.domain.factories.oauth_token_factory.OauthTokenFactory.create_entity"
    )
    def test_to_entity(self, mock_create_entity):
        """Test mapping from DB model to domain entity using factory."""
        # Create a mock DB model
        db_model = MagicMock()
        db_model.id = self.token_id
        db_model.access_token = self.access_token
        db_model.refresh_token = self.refresh_token
        db_model.token_type = self.token_type.value
        db_model.user_integration = self.user_integration_mock
        db_model.resources = self.resources

        # Create a mock entity to be returned by the factory
        mock_entity = ConfluenceToken(
            id=self.token_id,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            token_type=self.token_type,
            user_integration=self.user_integration_mock,
            resources=self.resources,
        )
        mock_create_entity.return_value = mock_entity

        # Map to entity
        entity = self.mapper.to_entity(db_model)

        # Assert factory was called with db_model
        mock_create_entity.assert_called_once_with(record=db_model)

        # Assert returned entity is what we expect
        self.assertEqual(entity, mock_entity)

    def test_to_entities_not_implemented(self):
        """Test that to_entities is not implemented (returns None)."""
        # Note: In the implementation, this method is simply defined as 'pass'
        db_models = [MagicMock() for _ in range(3)]

        # Call the method
        result = self.mapper.to_entities(db_models)

        # Assert it returns None (as it's not implemented)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from intric.integration.domain.entities.oauth_token import (
    ConfluenceToken,
    SharePointToken,
)
from intric.integration.domain.factories.oauth_token_factory import OauthTokenFactory
from intric.integration.presentation.models import IntegrationType


class TestOauthTokenFactory(unittest.TestCase):
    def setUp(self):
        # Create a mock user integration to use in tests
        self.user_integration_mock = MagicMock()
        self.user_integration_mock.id = uuid4()
        self.user_integration_mock.user_id = uuid4()
        self.user_integration_mock.authenticated = True
        self.user_integration_mock.auth_type = "user_oauth"
        self.user_integration_mock.tenant_app_id = None
        self.user_integration_mock.created_at = None
        self.user_integration_mock.updated_at = None
        self.user_integration_mock.tenant_integration.id = uuid4()
        self.user_integration_mock.tenant_integration.tenant_id = uuid4()
        self.user_integration_mock.tenant_integration.integration.id = uuid4()
        self.user_integration_mock.tenant_integration.integration.name = (
            "Test Integration"
        )
        self.user_integration_mock.tenant_integration.integration.description = (
            "Test Description"
        )
        self.user_integration_mock.tenant_integration.integration.integration_type = (
            IntegrationType.Confluence.value
        )

        # Create base token data to use for both types
        self.token_id = uuid4()
        self.access_token = "test_access_token"
        self.refresh_token = "test_refresh_token"

    def test_create_confluence_token(self):
        # Arrange
        confluence_resources = [
            {"id": "cloud123", "url": "https://example.atlassian.com"}
        ]
        db_record = MagicMock()
        db_record.id = self.token_id
        db_record.access_token = self.access_token
        db_record.refresh_token = self.refresh_token
        db_record.token_type = IntegrationType.Confluence.value
        db_record.user_integration = self.user_integration_mock
        db_record.resources = confluence_resources

        # Act
        token = OauthTokenFactory.create_entity(db_record)

        # Assert
        self.assertIsInstance(token, ConfluenceToken)
        self.assertEqual(token.id, self.token_id)
        self.assertEqual(token.access_token, self.access_token)
        self.assertEqual(token.refresh_token, self.refresh_token)
        self.assertEqual(token.token_type, IntegrationType.Confluence)
        self.assertEqual(token.user_integration.id, self.user_integration_mock.id)
        self.assertEqual(token.resources, confluence_resources)

        # Test specific properties of ConfluenceToken
        self.assertTrue(token.is_confluence)
        self.assertEqual(token.cloud_id, "cloud123")
        self.assertEqual(
            token.base_url, f"https://api.atlassian.com/ex/confluence/{token.cloud_id}"
        )
        self.assertEqual(token.base_web_url, "https://example.atlassian.com/wiki")

    def test_create_sharepoint_token(self):
        # Arrange
        sharepoint_resources = [
            {
                "id": "sites,tenant123,site456",
                "webUrl": "https://tenant.sharepoint.com/sites/site456",
            }
        ]
        db_record = MagicMock()
        db_record.id = self.token_id
        db_record.access_token = self.access_token
        db_record.refresh_token = self.refresh_token
        db_record.token_type = IntegrationType.Sharepoint.value
        db_record.user_integration = self.user_integration_mock
        db_record.resources = sharepoint_resources

        # Act
        token = OauthTokenFactory.create_entity(db_record)

        # Assert
        self.assertIsInstance(token, SharePointToken)
        self.assertEqual(token.id, self.token_id)
        self.assertEqual(token.access_token, self.access_token)
        self.assertEqual(token.refresh_token, self.refresh_token)
        self.assertEqual(token.token_type, IntegrationType.Sharepoint)
        self.assertEqual(token.user_integration.id, self.user_integration_mock.id)
        self.assertEqual(token.resources, sharepoint_resources)

        # Test specific properties of SharePointToken
        self.assertTrue(token.is_sharepoint)
        self.assertEqual(token.base_url, "https://graph.microsoft.com")
        self.assertEqual(token.base_site_id, "sites,tenant123,site456")

    def test_create_token_with_unknown_type(self):
        # Arrange
        db_record = MagicMock()
        db_record.token_type = "unknown_type"

        # Act & Assert
        with self.assertRaises(ValueError):
            OauthTokenFactory.create_entity(db_record)


if __name__ == "__main__":
    unittest.main()

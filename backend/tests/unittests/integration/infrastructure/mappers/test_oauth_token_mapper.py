import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet

from eneo.integration.domain.entities.oauth_token import ConfluenceToken
from eneo.integration.infrastructure.mappers.oauth_token_mapper import (
    OauthTokenMapper,
)
from eneo.integration.presentation.models import IntegrationType
from eneo.settings.encryption_service import EncryptionService


class TestOauthTokenMapper(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.inactive_encryption = EncryptionService(None)
        self.active_encryption = EncryptionService(Fernet.generate_key().decode())
        # Default mapper has encryption disabled (legacy plaintext behaviour)
        self.mapper = OauthTokenMapper(encryption_service=self.inactive_encryption)

        # Sample OAuth token data
        self.token_id = uuid4()
        self.access_token = "test_access_token"
        self.refresh_token = "test_refresh_token"
        self.token_type = IntegrationType.Confluence
        self.resources = [{"id": "cloud123", "url": "https://example.atlassian.com"}]

        # Create mock user integration
        self.user_integration_mock = MagicMock()
        self.user_integration_mock.id = uuid4()

    def _make_token(self) -> ConfluenceToken:
        return ConfluenceToken(
            id=self.token_id,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            token_type=self.token_type,
            user_integration=self.user_integration_mock,
            resources=self.resources,
        )

    def test_to_db_dict_without_encryption_stores_plaintext(self):
        """Without a key configured, tokens are stored verbatim (legacy behaviour)."""
        db_dict = self.mapper.to_db_dict(self._make_token())

        self.assertEqual(db_dict["access_token"], self.access_token)
        self.assertEqual(db_dict["refresh_token"], self.refresh_token)
        self.assertEqual(db_dict["token_type"], self.token_type.value)
        self.assertEqual(db_dict["user_integration_id"], self.user_integration_mock.id)
        self.assertEqual(db_dict["resources"], self.resources)
        # Ensure ID is not in the dictionary (handled by SQLAlchemy)
        self.assertNotIn("id", db_dict)

    def test_to_db_dict_with_encryption_encrypts_tokens(self):
        """With a key configured, access/refresh tokens are encrypted at rest."""
        mapper = OauthTokenMapper(encryption_service=self.active_encryption)

        db_dict = mapper.to_db_dict(self._make_token())

        self.assertTrue(db_dict["access_token"].startswith("enc:fernet:v1:"))
        self.assertTrue(db_dict["refresh_token"].startswith("enc:fernet:v1:"))
        self.assertNotEqual(db_dict["access_token"], self.access_token)
        self.assertEqual(
            self.active_encryption.decrypt(db_dict["access_token"]), self.access_token
        )
        self.assertEqual(
            self.active_encryption.decrypt(db_dict["refresh_token"]), self.refresh_token
        )

    def test_encrypts_large_graph_token_above_api_key_limit(self):
        """A >10KB Graph access token must encrypt, not hit the API-key length cap."""
        mapper = OauthTokenMapper(encryption_service=self.active_encryption)
        big_token = ConfluenceToken(
            id=self.token_id,
            access_token="A" * 20000,  # 20KB, well over EncryptionService default 10KB
            refresh_token=self.refresh_token,
            token_type=self.token_type,
            user_integration=self.user_integration_mock,
            resources=self.resources,
        )

        db_dict = mapper.to_db_dict(big_token)

        self.assertTrue(db_dict["access_token"].startswith("enc:fernet:v1:"))
        self.assertEqual(
            self.active_encryption.decrypt(db_dict["access_token"]), "A" * 20000
        )

    def test_encrypt_decrypt_round_trip(self):
        """A token written with encryption reads back as the original plaintext."""
        mapper = OauthTokenMapper(encryption_service=self.active_encryption)
        db_dict = mapper.to_db_dict(self._make_token())

        db_model = MagicMock()
        db_model.id = self.token_id
        db_model.access_token = db_dict["access_token"]
        db_model.refresh_token = db_dict["refresh_token"]
        db_model.token_type = self.token_type.value
        db_model.user_integration = self.user_integration_mock
        db_model.resources = self.resources
        db_model.created_at = None
        db_model.updated_at = None

        entity = mapper.to_entity(db_model)

        self.assertEqual(entity.access_token, self.access_token)
        self.assertEqual(entity.refresh_token, self.refresh_token)

    def test_to_entity_reads_legacy_plaintext_when_encryption_active(self):
        """Rows stored before encryption (no prefix) are read through unchanged."""
        mapper = OauthTokenMapper(encryption_service=self.active_encryption)

        db_model = MagicMock()
        db_model.id = self.token_id
        db_model.access_token = self.access_token  # legacy plaintext, no prefix
        db_model.refresh_token = self.refresh_token
        db_model.token_type = self.token_type.value
        db_model.user_integration = self.user_integration_mock
        db_model.resources = self.resources
        db_model.created_at = None
        db_model.updated_at = None

        entity = mapper.to_entity(db_model)

        self.assertEqual(entity.access_token, self.access_token)
        self.assertEqual(entity.refresh_token, self.refresh_token)

    @patch(
        "eneo.integration.domain.factories.oauth_token_factory.OauthTokenFactory.create_entity"
    )
    def test_to_entity_passes_decrypted_tokens_to_factory(self, mock_create_entity):
        """The mapper hands decrypted credentials to the factory."""
        db_model = MagicMock()
        db_model.id = self.token_id
        db_model.access_token = self.access_token
        db_model.refresh_token = self.refresh_token
        db_model.token_type = self.token_type.value
        db_model.user_integration = self.user_integration_mock
        db_model.resources = self.resources

        mock_entity = self._make_token()
        mock_create_entity.return_value = mock_entity

        entity = self.mapper.to_entity(db_model)

        mock_create_entity.assert_called_once_with(
            record=db_model,
            access_token=self.access_token,
            refresh_token=self.refresh_token,
        )
        self.assertEqual(entity, mock_entity)

    def test_to_entities_maps_each_db_model(self):
        """Test mapping a list of DB models to domain entities."""
        db_models = [MagicMock() for _ in range(3)]
        mapped_entities = [MagicMock() for _ in range(3)]

        with patch.object(
            self.mapper, "to_entity", side_effect=mapped_entities
        ) as mock_to_entity:
            result = self.mapper.to_entities(db_models)

        self.assertEqual(result, mapped_entities)
        self.assertEqual(mock_to_entity.call_count, len(db_models))
        for db_model in db_models:
            mock_to_entity.assert_any_call(db_model)


if __name__ == "__main__":
    unittest.main()

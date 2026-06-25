from typing import Any, Dict, Sequence

from typing_extensions import override

from intric.base.base_entity import EntityMapper
from intric.database.tables.integration_table import (
    OauthToken as OauthTokenDBModel,
)
from intric.integration.domain.entities.oauth_token import OauthToken
from intric.integration.domain.factories.oauth_token_factory import (
    OauthTokenFactory,
)
from intric.settings.encryption_service import EncryptionService


class OauthTokenMapper(EntityMapper[OauthToken, OauthTokenDBModel]):
    """Mapper for OAuth tokens with encryption at rest.

    Access and refresh tokens are encrypted on write when an encryption key is
    configured. Reads transparently decrypt versioned values and pass legacy
    plaintext rows through unchanged; those get re-encrypted on the next write
    (lazy migration), so no separate backfill is required and deployments without
    an ``ENCRYPTION_KEY`` keep working as before.
    """

    def __init__(self, encryption_service: EncryptionService) -> None:
        super().__init__()
        self.encryption_service = encryption_service

    def _encrypt(self, value: str) -> str:
        if value and self.encryption_service.is_active():
            return self.encryption_service.encrypt(value)
        return value

    def _decrypt(self, value: str) -> str:
        if value and self.encryption_service.is_encrypted(value):
            return self.encryption_service.decrypt(value)
        return value

    @override
    def to_db_dict(self, entity: OauthToken) -> Dict[str, Any]:
        return {
            "access_token": self._encrypt(entity.access_token),
            "refresh_token": self._encrypt(entity.refresh_token),
            "token_type": entity.token_type.value,
            "user_integration_id": entity.user_integration.id,
            "resources": entity.resources,
        }

    @override
    def to_entity(self, db_model: OauthTokenDBModel) -> OauthToken:
        return OauthTokenFactory.create_entity(
            record=db_model,
            access_token=self._decrypt(db_model.access_token),
            refresh_token=self._decrypt(db_model.refresh_token),
        )

    @override
    def to_entities(self, db_models: Sequence[OauthTokenDBModel]) -> list[OauthToken]:
        return [self.to_entity(db_model) for db_model in db_models]

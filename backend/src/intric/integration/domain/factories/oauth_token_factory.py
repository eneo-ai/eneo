from typing import TYPE_CHECKING

from intric.integration.domain.entities.oauth_token import (
    ConfluenceToken,
    SharePointToken,
)
from intric.integration.presentation.models import IntegrationType

if TYPE_CHECKING:
    from intric.database.tables.integration_table import (
        OauthToken as OauthTokenDBModel,
    )


class OauthTokenFactory:
    @classmethod
    def create_entity(self, record: "OauthTokenDBModel"):
        if IntegrationType(record.token_type).is_confluence:
            return ConfluenceToken(
                access_token=record.access_token,
                refresh_token=record.refresh_token,
                token_type=IntegrationType(record.token_type),
                user_integration=record.user_integration,
                id=record.id,
                resources=record.resources,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        elif IntegrationType(record.token_type).is_sharepoint:
            return SharePointToken(
                access_token=record.access_token,
                refresh_token=record.refresh_token,
                token_type=IntegrationType(record.token_type),
                user_integration=record.user_integration,
                id=record.id,
                resources=record.resources,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        else:
            raise ValueError("Unknown token type")

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from intric.integration.domain.entities.oauth_token import (
    ConfluenceToken,
    SharePointToken,
)
from intric.integration.domain.factories.user_integration_factory import (
    UserIntegrationFactory,
)
from intric.integration.infrastructure.content_service.types import OAuthResource
from intric.integration.presentation.models import IntegrationType

if TYPE_CHECKING:
    from intric.database.tables.integration_table import (
        OauthToken as OauthTokenDBModel,
    )


class OauthTokenFactory:
    @staticmethod
    def create_entity(record: "OauthTokenDBModel"):
        user_integration = UserIntegrationFactory.create_entity(record.user_integration)
        raw_resources = cast(list[dict[str, Any]] | None, record.resources)
        resources = (
            [cast(OAuthResource, resource) for resource in raw_resources]
            if raw_resources is not None
            else None
        )
        token_type = IntegrationType(record.token_type)
        token_id = cast(UUID, record.id)
        created_at = cast(datetime | None, record.created_at)
        updated_at = cast(datetime | None, record.updated_at)

        if token_type.is_confluence:
            return ConfluenceToken(
                access_token=cast(str, record.access_token),
                refresh_token=cast(str, record.refresh_token),
                token_type=token_type,
                user_integration=user_integration,
                id=token_id,
                resources=resources,
                created_at=created_at,
                updated_at=updated_at,
            )
        elif token_type.is_sharepoint:
            return SharePointToken(
                access_token=cast(str, record.access_token),
                refresh_token=cast(str, record.refresh_token),
                token_type=token_type,
                user_integration=user_integration,
                id=token_id,
                resources=resources,
                created_at=created_at,
                updated_at=updated_at,
            )
        else:
            raise ValueError("Unknown token type")

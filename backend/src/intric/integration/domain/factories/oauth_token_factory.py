from typing import TYPE_CHECKING, Any, cast

from intric.integration.domain.entities.oauth_token import (
    ConfluenceToken,
    OauthToken,
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
    def create_entity(record: "OauthTokenDBModel") -> OauthToken:
        user_integration = UserIntegrationFactory.create_entity(record.user_integration)
        # resources comes from a JSON column; build typed list of OAuthResource
        raw_resources = record.resources
        resources: list[OAuthResource] | None = None
        if isinstance(raw_resources, list):
            raw_list: list[dict[str, Any]] = cast(list[dict[str, Any]], raw_resources)
            resources = [OAuthResource(**r) for r in raw_list]
        token_type = IntegrationType(record.token_type)

        if token_type.is_confluence:
            return ConfluenceToken(
                access_token=record.access_token,
                refresh_token=record.refresh_token,
                token_type=token_type,
                user_integration=user_integration,
                id=record.id,
                resources=resources,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        elif token_type.is_sharepoint:
            return SharePointToken(
                access_token=record.access_token,
                refresh_token=record.refresh_token,
                token_type=token_type,
                user_integration=user_integration,
                id=record.id,
                resources=resources,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        else:
            raise ValueError("Unknown token type")

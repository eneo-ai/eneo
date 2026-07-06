from typing import TYPE_CHECKING, Any, cast

from eneo.integration.domain.entities.oauth_token import (
    ConfluenceToken,
    OauthToken,
    SharePointToken,
)
from eneo.integration.domain.factories.user_integration_factory import (
    UserIntegrationFactory,
)
from eneo.integration.domain.value_objects import IntegrationType, OAuthResource

if TYPE_CHECKING:
    from eneo.database.tables.integration_table import (
        OauthToken as OauthTokenDBModel,
    )


class OauthTokenFactory:
    @staticmethod
    def create_entity(
        record: "OauthTokenDBModel",
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
    ) -> OauthToken:
        # The mapper decrypts the stored credentials and passes them in; fall back to
        # the raw columns when called without overrides.
        resolved_access_token = (
            access_token if access_token is not None else record.access_token
        )
        resolved_refresh_token = (
            refresh_token if refresh_token is not None else record.refresh_token
        )
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
                access_token=resolved_access_token,
                refresh_token=resolved_refresh_token,
                token_type=token_type,
                user_integration=user_integration,
                id=record.id,
                resources=resources,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        elif token_type.is_sharepoint:
            return SharePointToken(
                access_token=resolved_access_token,
                refresh_token=resolved_refresh_token,
                token_type=token_type,
                user_integration=user_integration,
                id=record.id,
                resources=resources,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        else:
            raise ValueError("Unknown token type")

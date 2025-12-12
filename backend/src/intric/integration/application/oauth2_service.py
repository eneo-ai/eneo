from typing import TYPE_CHECKING

from intric.integration.domain.entities.oauth_token import OauthToken
from intric.integration.domain.entities.user_integration import UserIntegration
from intric.integration.presentation.models import IntegrationType
from intric.main.exceptions import BadRequestException

if TYPE_CHECKING:
    from uuid import UUID

    from intric.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from intric.integration.domain.repositories.tenant_integration_repo import (
        TenantIntegrationRepository,
    )
    from intric.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from intric.integration.infrastructure.auth_service.confluence_auth_service import (
        ConfluenceAuthService,
    )
    from intric.integration.infrastructure.auth_service.sharepoint_auth_service import (
        SharepointAuthService,
    )


class Oauth2Service:
    def __init__(
        self,
        confluence_auth_service: "ConfluenceAuthService",
        tenant_integration_repo: "TenantIntegrationRepository",
        user_integration_repo: "UserIntegrationRepository",
        oauth_token_repo: "OauthTokenRepository",
        sharepoint_auth_service: "SharepointAuthService",
    ):
        self.confluence_auth_service = confluence_auth_service
        self.tenant_integration_repo = tenant_integration_repo
        self.user_integration_repo = user_integration_repo
        self.oauth_token_repo = oauth_token_repo
        self.sharepoint_auth_service = sharepoint_auth_service

        self._auth_mapper = {
            IntegrationType.Confluence.value: self.confluence_auth_service,
            IntegrationType.Sharepoint.value: self.sharepoint_auth_service,
        }

    async def start_auth(
        self,
        tenant_integration_id: "UUID",
        state: str | None = None,
    ) -> dict:
        tenant_integration = await self.tenant_integration_repo.one(
            id=tenant_integration_id
        )
        integration_type = tenant_integration.integration_type

        if integration_type not in self._auth_mapper:
            raise BadRequestException("Invalid integration type")

        auth_service = self._auth_mapper[integration_type]
        if integration_type == IntegrationType.Sharepoint.value:
            return await auth_service.gen_auth_url(state, tenant_id=tenant_integration.tenant_id)
        else:
            return getattr(auth_service, "gen_auth_url")(state)

    async def auth_integration(
        self,
        user_id: "UUID",
        tenant_integration_id: "UUID",
        auth_code: str,
    ) -> UserIntegration:
        tenant_integration = await self.tenant_integration_repo.one(
            id=tenant_integration_id
        )

        authenticated_integration = await self.user_integration_repo.one_or_none(
            user_id=user_id,
            tenant_integration_id=tenant_integration.id,
            authenticated=True,
        )
        if authenticated_integration:
            return authenticated_integration

        authenticated_integration = await self.user_integration_repo.add(
            obj=UserIntegration(
                user_id=user_id,
                tenant_integration=tenant_integration,
                authenticated=True,
            )
        )

        await self._fetch_token(
            auth_code=auth_code, authenticated_integration=authenticated_integration
        )

        return authenticated_integration

    async def _fetch_token(
        self,
        auth_code: str,
        authenticated_integration: "UserIntegration",
    ) -> None:
        integration_type = authenticated_integration.integration_type
        if integration_type not in self._auth_mapper:
            raise BadRequestException("Invalid integration type")
        service = self._auth_mapper[integration_type]

        # Pass tenant_id for SharePoint to use tenant-specific configuration
        if integration_type == IntegrationType.Sharepoint.value:
            token_result = await service.exchange_token(
                auth_code, tenant_id=authenticated_integration.tenant_integration.tenant_id
            )
        else:
            token_result = await getattr(service, "exchange_token")(auth_code)

        access_token = token_result.get("access_token")
        resource_data = await getattr(service, "get_resources")(access_token)

        # NOTE: build unified factory interface to construct a new entity
        # so that we do not need to manually handle the creation of entities in
        # application service which violates the domain separation
        token = OauthToken(
            access_token=access_token,
            refresh_token=token_result["refresh_token"],
            token_type=IntegrationType(integration_type),
            user_integration=authenticated_integration,
            resources=resource_data,
        )
        await self.oauth_token_repo.add(obj=token)

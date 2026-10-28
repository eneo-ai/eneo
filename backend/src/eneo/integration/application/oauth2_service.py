import secrets
from typing import TYPE_CHECKING

import httpx

from eneo.integration.domain.entities.oauth_token import OauthToken
from eneo.integration.domain.entities.user_integration import UserIntegration
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.auth_service.base_auth_service import (
    TokenResponse,
    token_exchange_rejection,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    loggable_token_reason,
)
from eneo.integration.infrastructure.oauth_state_store import OauthStateStore
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from uuid import UUID

    import redis.asyncio as redis

    from eneo.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from eneo.integration.domain.repositories.tenant_integration_repo import (
        TenantIntegrationRepository,
    )
    from eneo.integration.domain.repositories.user_integration_repo import (
        UserIntegrationRepository,
    )
    from eneo.integration.infrastructure.auth_service.confluence_auth_service import (
        ConfluenceAuthService,
    )
    from eneo.integration.infrastructure.auth_service.sharepoint_auth_service import (
        SharepointAuthService,
    )
    from eneo.users.user import UserInDB

logger = get_logger(__name__)

# CSRF state for the per-user OAuth flow, bound to the initiating user and
# tenant integration. Plain JSON: it carries ids only, never a secret.
_OAUTH_STATE_PREFIX = "integration:oauth_state:"
_EXPIRED_STATE = (
    "Invalid or expired OAuth state. Please restart the authentication flow."
)


class Oauth2Service:
    def __init__(
        self,
        confluence_auth_service: "ConfluenceAuthService",
        tenant_integration_repo: "TenantIntegrationRepository",
        user_integration_repo: "UserIntegrationRepository",
        oauth_token_repo: "OauthTokenRepository",
        sharepoint_auth_service: "SharepointAuthService",
        redis_client: "redis.Redis",
        user: "UserInDB",
    ) -> None:
        super().__init__()
        self.confluence_auth_service = confluence_auth_service
        self.tenant_integration_repo = tenant_integration_repo
        self.user_integration_repo = user_integration_repo
        self.oauth_token_repo = oauth_token_repo
        self.sharepoint_auth_service = sharepoint_auth_service
        self.redis_client = redis_client
        self.user = user
        self._state_store = OauthStateStore(redis_client, prefix=_OAUTH_STATE_PREFIX)

        self._auth_mapper = {
            IntegrationType.Confluence.value: self.confluence_auth_service,
            IntegrationType.Sharepoint.value: self.sharepoint_auth_service,
        }

    async def start_auth(
        self,
        tenant_integration_id: "UUID",
        redirect_uri: str | None = None,
    ) -> dict[str, str]:
        tenant_integration = await self.tenant_integration_repo.one(
            id=tenant_integration_id, tenant_id=self.user.tenant_id
        )
        integration_type = tenant_integration.integration_type

        if integration_type not in self._auth_mapper:
            raise BadRequestException("Invalid integration type")

        try:
            redirect_uri = get_settings().integration_callback_uri(redirect_uri)
        except ValueError as exc:
            raise BadRequestException(str(exc)) from exc

        # Backend-generated, single-use state bound to this user + integration.
        state = secrets.token_urlsafe(32)
        await self._state_store.store(
            state,
            {
                "user_id": str(self.user.id),
                "tenant_integration_id": str(tenant_integration_id),
                "redirect_uri": redirect_uri,
            },
        )

        if integration_type == IntegrationType.Sharepoint.value:
            result = await self.sharepoint_auth_service.gen_auth_url(
                state, tenant_id=tenant_integration.tenant_id, redirect_uri=redirect_uri
            )
        elif integration_type == IntegrationType.Confluence.value:
            result = await self.confluence_auth_service.gen_auth_url(
                state, redirect_uri=redirect_uri
            )
        else:
            raise BadRequestException("Invalid integration type")

        return {"auth_url": result["auth_url"], "state": state}

    async def auth_integration(
        self,
        tenant_integration_id: "UUID",
        auth_code: str,
        state: str,
    ) -> UserIntegration:
        # CSRF: the state must have been issued by us to THIS user for THIS
        # integration. The binding is checked before the state is spent.
        stored = await self._state_store.peek(state)
        if stored is None:
            # Drop an unreadable state; an unknown one is already gone.
            await self._state_store.pop(state)
            raise BadRequestException(_EXPIRED_STATE)
        if stored.get("user_id") != str(self.user.id) or stored.get(
            "tenant_integration_id"
        ) != str(tenant_integration_id):
            logger.warning(
                "Rejected OAuth callback with mismatched state binding (user=%s, "
                "tenant_integration=%s)",
                self.user.id,
                tenant_integration_id,
            )
            raise BadRequestException("OAuth state does not match the request.")
        stored = await self._state_store.pop(state)
        if stored is None:
            raise BadRequestException(_EXPIRED_STATE)

        tenant_integration = await self.tenant_integration_repo.one(
            id=tenant_integration_id, tenant_id=self.user.tenant_id
        )

        authenticated_integration = await self.user_integration_repo.one_or_none(
            user_id=self.user.id,
            tenant_integration_id=tenant_integration.id,
            authenticated=True,
        )
        if authenticated_integration:
            return authenticated_integration

        authenticated_integration = await self.user_integration_repo.add(
            obj=UserIntegration(
                user_id=self.user.id,
                tenant_integration=tenant_integration,
                authenticated=True,
            )
        )

        await self._fetch_token(
            auth_code=auth_code,
            authenticated_integration=authenticated_integration,
            redirect_uri=stored.get("redirect_uri"),
        )

        return authenticated_integration

    async def _fetch_token(
        self,
        auth_code: str,
        authenticated_integration: "UserIntegration",
        redirect_uri: str | None = None,
    ) -> None:
        integration_type = authenticated_integration.integration_type
        if integration_type == IntegrationType.Sharepoint.value:
            token_result = await self._exchange(
                self.sharepoint_auth_service.exchange_token(
                    auth_code,
                    tenant_id=authenticated_integration.tenant_integration.tenant_id,
                    redirect_uri=redirect_uri,
                )
            )
            if token_result is None:
                raise BadRequestException("Failed to exchange SharePoint auth code")
            access_token = token_result["access_token"]
            resource_data = await self.sharepoint_auth_service.get_resources(
                access_token
            )
        elif integration_type == IntegrationType.Confluence.value:
            token_result = await self._exchange(
                self.confluence_auth_service.exchange_token(
                    auth_code, redirect_uri=redirect_uri
                )
            )
            if token_result is None:
                raise BadRequestException("Failed to exchange Confluence auth code")
            access_token = token_result["access_token"]
            resource_data = await self.confluence_auth_service.get_resources(
                access_token
            )
        else:
            raise BadRequestException("Invalid integration type")

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

    @staticmethod
    async def _exchange(
        exchange: "Awaitable[TokenResponse | None]",
    ) -> "TokenResponse | None":
        """The token response; a refused code or app is the caller's 400, not
        a 500."""
        try:
            return await exchange
        except httpx.HTTPStatusError as exc:
            rejection = token_exchange_rejection(exc)
            if rejection is None:
                raise
            logger.warning(
                "OAuth code exchange refused with HTTP %s: %s",
                exc.response.status_code,
                loggable_token_reason(exc),
            )
            raise rejection from exc

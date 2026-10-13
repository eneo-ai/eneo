import asyncio
from time import monotonic
from typing import TYPE_CHECKING, Optional

from eneo.main.logging import get_logger
from eneo.worker.redis.lease import redis_lease

if TYPE_CHECKING:
    from uuid import UUID

    import redis.asyncio as aioredis

    from eneo.integration.domain.entities.oauth_token import OauthToken
    from eneo.integration.domain.repositories.oauth_token_repo import (
        OauthTokenRepository,
    )
    from eneo.integration.infrastructure.auth_service.confluence_auth_service import (
        ConfluenceAuthService,
    )
    from eneo.integration.infrastructure.auth_service.sharepoint_auth_service import (
        SharepointAuthService,
    )

logger = get_logger(__name__)

_REFRESH_LEASE_PREFIX = "integration:oauth_token_refresh:"
# A refresh is one token-endpoint round trip; the TTL only bounds a crashed
# holder, the watchdog keeps a live one.
_REFRESH_LEASE_TTL_SECONDS = 60
_REFRESH_LEASE_WAIT_SECONDS = 30.0
_REFRESH_LEASE_POLL_SECONDS = 0.2


class OauthTokenService:
    # Process-wide locks to avoid concurrent refreshes for the same token.
    _refresh_locks: dict[str, asyncio.Lock] = {}
    _refresh_locks_guard = asyncio.Lock()

    def __init__(
        self,
        oauth_token_repo: "OauthTokenRepository",
        confluence_auth_service: "ConfluenceAuthService",
        sharepoint_auth_service: "SharepointAuthService",
        redis_client: Optional["aioredis.Redis"] = None,
    ) -> None:
        super().__init__()
        self.oauth_token_repo = oauth_token_repo
        self.confluence_auth_service = confluence_auth_service
        self.sharepoint_auth_service = sharepoint_auth_service
        self.redis_client = redis_client

    @classmethod
    async def _get_refresh_lock(cls, token_id: "UUID") -> asyncio.Lock:
        token_key = str(token_id)
        async with cls._refresh_locks_guard:
            lock = cls._refresh_locks.get(token_key)
            if lock is None:
                lock = asyncio.Lock()
                cls._refresh_locks[token_key] = lock
            return lock

    async def get_oauth_token_by_user_integration(
        self,
        user_integration_id: "UUID",
    ) -> Optional["OauthToken"]:
        """Get OAuth token for a specific user integration.

        Args:
            user_integration_id: The ID of the user integration

        Returns:
            The OAuth token if found, None otherwise
        """
        return await self.oauth_token_repo.one_or_none(
            user_integration_id=user_integration_id
        )

    async def refresh_and_update_token(
        self,
        token_id: "UUID",
    ) -> "OauthToken":
        """Refresh ``token_id`` once across processes and persist the result.

        Workers and API processes serialise on a Redis lease keyed by the token.
        A caller that had to wait re-reads the row afterwards and reuses a token
        another holder refreshed in the meantime (visible once that holder's
        transaction has committed) instead of spending a second refresh.
        """
        lock = await self._get_refresh_lock(token_id)
        async with lock:
            token = await self.oauth_token_repo.one(id=token_id)
            if self.redis_client is None:
                return await self._refresh_and_store(token)

            waited = False
            deadline = monotonic() + _REFRESH_LEASE_WAIT_SECONDS
            lease_key = f"{_REFRESH_LEASE_PREFIX}{token_id}"
            while True:
                async with redis_lease(
                    self.redis_client,
                    lease_key,
                    ttl_seconds=_REFRESH_LEASE_TTL_SECONDS,
                    log_lock_key=False,
                ) as acquired:
                    if acquired:
                        if waited:
                            fresh = await self.oauth_token_repo.one_fresh(token.id)
                            if fresh.access_token != token.access_token:
                                logger.debug(
                                    "Reusing OAuth token %s refreshed by another holder",
                                    token_id,
                                )
                                return fresh
                            token = fresh
                        return await self._refresh_and_store(token)
                if monotonic() >= deadline:
                    logger.warning(
                        "Refresh lease for OAuth token %s not acquired within %ss; "
                        "refreshing without it",
                        token_id,
                        _REFRESH_LEASE_WAIT_SECONDS,
                    )
                    return await self._refresh_and_store(token)
                waited = True
                await asyncio.sleep(_REFRESH_LEASE_POLL_SECONDS)

    async def _refresh_and_store(self, token: "OauthToken") -> "OauthToken":
        if token.token_type.is_confluence:
            token_result = await self.confluence_auth_service.refresh_access_token(
                refresh_token=token.refresh_token
            )
        elif token.token_type.is_sharepoint:
            # Get tenant_id from the user_integration to use tenant-specific configuration
            assert token.user_integration is not None
            assert token.user_integration.tenant_integration is not None
            tenant_id = token.user_integration.tenant_integration.tenant_id
            token_result = await self.sharepoint_auth_service.refresh_access_token(
                refresh_token=token.refresh_token, tenant_id=tenant_id
            )
        else:
            raise ValueError("Unknown integration type")

        assert token_result is not None
        token.access_token = token_result["access_token"]
        # Some providers/flows omit refresh_token on refresh (no rotation);
        # keep the existing one instead of overwriting it with None.
        new_refresh_token = token_result.get("refresh_token")
        if new_refresh_token:
            token.refresh_token = new_refresh_token

        return await self.oauth_token_repo.update(obj=token)

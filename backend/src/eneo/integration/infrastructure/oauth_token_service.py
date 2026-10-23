import asyncio
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from time import monotonic
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from redis.exceptions import RedisError

from eneo.database.database import sessionmanager
from eneo.database.tables.integration_table import OauthToken as OauthTokenDBModel
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
    from eneo.integration.infrastructure.mappers.oauth_token_mapper import (
        OauthTokenMapper,
    )

logger = get_logger(__name__)

_REFRESH_LEASE_PREFIX = "integration:oauth_token_refresh:"
# A refresh is one token-endpoint round trip; the TTL only bounds a crashed
# holder, the watchdog keeps a live one.
_REFRESH_LEASE_TTL_SECONDS = 60
_REFRESH_LEASE_WAIT_SECONDS = 30.0
_REFRESH_LEASE_POLL_SECONDS = 0.2
_TOKEN_WRITE_LOCK_TIMEOUT = "2s"


class OauthTokenService:
    # Process-wide locks to avoid concurrent refreshes for the same token. An
    # entry lives only while a caller holds or waits for it, so the table does
    # not grow with every token the process has ever refreshed.
    _refresh_locks: dict[str, tuple[asyncio.Lock, int]] = {}
    _refresh_locks_guard = asyncio.Lock()

    def __init__(
        self,
        oauth_token_repo: "OauthTokenRepository",
        confluence_auth_service: "ConfluenceAuthService",
        sharepoint_auth_service: "SharepointAuthService",
        redis_client: Optional["aioredis.Redis"] = None,
        token_mapper: Optional["OauthTokenMapper"] = None,
    ) -> None:
        super().__init__()
        self.oauth_token_repo = oauth_token_repo
        self.confluence_auth_service = confluence_auth_service
        self.sharepoint_auth_service = sharepoint_auth_service
        self.redis_client = redis_client
        self.token_mapper = token_mapper

    @classmethod
    @asynccontextmanager
    async def _refresh_lock(cls, token_id: "UUID") -> AsyncGenerator[None, None]:
        token_key = str(token_id)
        async with cls._refresh_locks_guard:
            lock, holders = cls._refresh_locks.get(token_key, (asyncio.Lock(), 0))
            cls._refresh_locks[token_key] = (lock, holders + 1)
        try:
            async with lock:
                yield
        finally:
            async with cls._refresh_locks_guard:
                lock, holders = cls._refresh_locks[token_key]
                if holders == 1:
                    del cls._refresh_locks[token_key]
                else:
                    cls._refresh_locks[token_key] = (lock, holders - 1)

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
        The refreshed token is committed before the lease is released, and the
        row is re-read once the lease is held, so a caller that queued behind
        another refresh, or that took the lease right after one was released,
        reuses the new token instead of refreshing with a refresh token the
        provider has already retired (Atlassian revokes the whole family).
        """
        async with self._refresh_lock(token_id):
            token = await self.oauth_token_repo.one(id=token_id)
            if self.redis_client is None:
                return await self._refresh_unless_changed(token)

            deadline = monotonic() + _REFRESH_LEASE_WAIT_SECONDS
            lease_key = f"{_REFRESH_LEASE_PREFIX}{token_id}"
            while True:
                async with AsyncExitStack() as stack:
                    try:
                        acquired = await stack.enter_async_context(
                            redis_lease(
                                self.redis_client,
                                lease_key,
                                ttl_seconds=_REFRESH_LEASE_TTL_SECONDS,
                                log_lock_key=False,
                            )
                        )
                    except (RedisError, OSError) as exc:
                        # A Redis outage must not take user integrations down
                        # with it; the process lock still serialises this host.
                        logger.warning(
                            "Redis unavailable for the refresh lease of OAuth token "
                            "%s (%s); refreshing under the process lock only",
                            token_id,
                            exc,
                        )
                        return await self._refresh_unless_changed(token)
                    if acquired:
                        return await self._refresh_unless_changed(token)
                if monotonic() >= deadline:
                    logger.warning(
                        "Refresh lease for OAuth token %s not acquired within %ss; "
                        "refreshing without it",
                        token_id,
                        _REFRESH_LEASE_WAIT_SECONDS,
                    )
                    return await self._refresh_unless_changed(token)
                await asyncio.sleep(_REFRESH_LEASE_POLL_SECONDS)

    async def _refresh_unless_changed(self, token: "OauthToken") -> "OauthToken":
        """Refresh ``token`` unless the row no longer holds the token first read."""
        fresh = await self.oauth_token_repo.one_fresh(token.id)
        if fresh.access_token != token.access_token:
            logger.debug("Reusing OAuth token %s refreshed by another holder", token.id)
            return fresh
        return await self._refresh_and_store(token)

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

        return await self._store(token)

    async def _store(self, token: "OauthToken") -> "OauthToken":
        """Persist the refreshed token so it is visible when the lease is released.

        The caller's transaction can be a whole sync job and commits long after
        the lease is gone; a waiter reading the row in between would refresh
        again with the superseded refresh token, which revokes the family for
        providers that rotate it, and a rollback of the job would discard the
        rotation. The row is therefore written on its own connection, and the
        caller's session re-reads it so later lookups there see it too.

        Without a mapper, or when the row cannot be locked shortly (the
        caller's own transaction already updated it), the write falls back to
        the caller's transaction. That reopens the window above until the
        caller commits: a holder taking the lease in between sees the old row
        and refreshes a second time. The fallback is logged so a double refresh
        can be traced to it.
        """
        if self.token_mapper is not None:
            columns = self.token_mapper.to_db_dict(token)
            try:
                async with sessionmanager.session() as session, session.begin():
                    await session.execute(
                        sa.text(
                            f"SET LOCAL lock_timeout = '{_TOKEN_WRITE_LOCK_TIMEOUT}'"
                        )
                    )
                    await session.execute(
                        sa.update(OauthTokenDBModel)
                        .where(OauthTokenDBModel.id == token.id)
                        .values(
                            access_token=columns["access_token"],
                            refresh_token=columns["refresh_token"],
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "Could not persist refreshed OAuth token %s on its own "
                    "connection (%s); storing it in the current transaction "
                    "instead. Until that commits, another refresh of this token "
                    "cannot see the rotation and will refresh again",
                    token.id,
                    type(exc).__name__,
                )
            else:
                return await self.oauth_token_repo.one_fresh(token.id)
        return await self.oauth_token_repo.update(obj=token)

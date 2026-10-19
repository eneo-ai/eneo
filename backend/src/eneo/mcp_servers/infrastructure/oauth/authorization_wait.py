"""Pausing a turn while the user authorizes an OAuth MCP server.

When a tool call needs an authorization the user has not given, the
streaming turn tells the client (a connect action appears on the step) and
waits here, the way it waits for a tool approval. The callback endpoint
marks the connection in Redis when the popup completes; the waiter polls
for that mark and the turn resumes with a fresh token. Without the mark
within the timeout, the call proceeds and answers with the remedy.

Redis carries the signal because the request that waits and the request
that completes the popup land on arbitrary workers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Optional
from uuid import UUID

import redis.asyncio as aioredis

from eneo.main.config import get_settings
from eneo.main.logging import get_logger

logger = get_logger(__name__)

CONNECTED_MARK_TTL_SECONDS = 300
POLL_INTERVAL_SECONDS = 0.5


def connected_key(user_id: UUID, server_id: UUID) -> str:
    return (
        f"eneo:{get_settings().environment}:mcp:oauth:connected:{user_id}:{server_id}"
    )


class MCPOAuthAuthorizationWaiter:
    def __init__(
        self,
        redis_client: Optional[aioredis.Redis],
        *,
        timeout_seconds: Optional[float] = None,
        poll_seconds: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(get_settings().mcp_oauth_authorization_wait_seconds)
        )
        self._poll = poll_seconds

    @property
    def available(self) -> bool:
        return self._redis is not None and self._timeout > 0

    async def mark_connected(self, user_id: UUID, server_id: UUID) -> None:
        """Called when the user's authorization at ``server_id`` completed."""
        if self._redis is None:
            return
        try:
            await self._redis.set(
                connected_key(user_id, server_id), "1", ex=CONNECTED_MARK_TTL_SECONDS
            )
        except Exception as exc:  # pragma: no cover - Redis outage
            logger.warning("Could not mark MCP OAuth connection in Redis: %s", exc)

    async def wait(self, user_id: UUID, server_ids: Iterable[UUID]) -> set[UUID]:
        """Wait until every server is marked connected, or the timeout passes.

        Returns the servers that were marked. Marks are consumed so a later
        turn cannot mistake an old authorization for a new one.
        """
        pending = list(dict.fromkeys(server_ids))
        if not pending or not self.available or self._redis is None:
            return set()
        connected: set[UUID] = set()
        deadline = asyncio.get_running_loop().time() + self._timeout
        while pending:
            keys = [connected_key(user_id, sid) for sid in pending]
            try:
                values: list[object] = list(await self._redis.mget(keys))
            except Exception as exc:  # pragma: no cover - Redis outage
                logger.warning("MCP OAuth authorization wait aborted: %s", exc)
                break
            hits = [sid for sid, value in zip(pending, values) if value]
            if hits:
                connected.update(hits)
                pending = [sid for sid in pending if sid not in connected]
                try:
                    await self._redis.delete(
                        *[connected_key(user_id, sid) for sid in hits]
                    )
                except Exception:  # pragma: no cover - best effort
                    pass
            if not pending:
                break
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(self._poll, remaining))
        return connected

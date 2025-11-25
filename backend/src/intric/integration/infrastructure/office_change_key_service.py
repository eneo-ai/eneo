"""Office ChangeKey validation service using Redis.

ChangeKey is Microsoft's equivalent of ETag - it changes whenever an item
is modified. By comparing ChangeKeys we can detect if an item has actually
changed between webhook notifications, preventing duplicate processing.

Single Redis key per item: office_change_key:{integration_id}:{item_id}
"""

from uuid import UUID

import redis.asyncio as redis

from intric.main.logging import get_logger

logger = get_logger(__name__)


class OfficeChangeKeyService:
    """Service for validating Office item ChangeKeys using Redis cache."""

    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        # TTL for ChangeKey entries (7 days)
        self.changekey_ttl_seconds = 7 * 24 * 60 * 60

    def _get_changekey_key(self, integration_knowledge_id: UUID, item_id: str) -> str:
        """Generate Redis key for storing ChangeKey.

        Key format: office_change_key:{integration_id}:{item_id}
        """
        return f"office_change_key:{integration_knowledge_id}:{item_id}"

    async def should_process(
        self, integration_knowledge_id: UUID, item_id: str, change_key: str
    ) -> bool:
        """Determine if a webhook notification should be processed.

        Returns True if:
        - This is the first notification for this item (no cached ChangeKey)
        - The ChangeKey has changed (item was modified)

        Returns False if:
        - The ChangeKey is identical to cached value (duplicate/no actual change)

        Args:
            integration_knowledge_id: The integration knowledge ID
            item_id: The Office item ID (eventId, fileId, etc.)
            change_key: The ChangeKey from the webhook notification

        Returns:
            True if the notification should be processed, False otherwise
        """
        key = self._get_changekey_key(integration_knowledge_id, item_id)
        logger.info(f"Checking ChangeKey for item {item_id} using Redis key: {key}")

        cached_change_key_bytes = await self.redis_client.get(key)

        if cached_change_key_bytes is None:
            # No previous ChangeKey cached - this is new or first time seeing it
            logger.info(
                f"No cached ChangeKey for item {item_id}; processing (first time). "
                f"Redis key: {key}"
            )
            return True

        # Decode bytes to string for comparison
        cached_change_key = cached_change_key_bytes.decode('utf-8') if isinstance(cached_change_key_bytes, bytes) else cached_change_key_bytes

        # Compare ChangeKeys
        if cached_change_key == change_key:
            logger.info(
                f"ChangeKey for item {item_id} unchanged ({change_key}); skipping duplicate. "
                f"Redis key: {key}"
            )
            return False

        # ChangeKey is different - item was modified
        logger.info(
            f"ChangeKey for item {item_id} changed (old={cached_change_key}, new={change_key}); processing. "
            f"Redis key: {key}"
        )
        return True

    async def update_change_key(
        self, integration_knowledge_id: UUID, item_id: str, change_key: str
    ) -> None:
        """Update the cached ChangeKey for an item after processing.

        Should be called after successfully processing a changed item.

        Args:
            integration_knowledge_id: The integration knowledge ID
            item_id: The Office item ID
            change_key: The new ChangeKey value
        """
        key = self._get_changekey_key(integration_knowledge_id, item_id)
        await self.redis_client.setex(key, self.changekey_ttl_seconds, change_key)
        logger.info(
            f"Updated cached ChangeKey for item {item_id} to {change_key}. "
            f"Redis key: {key}, TTL: {self.changekey_ttl_seconds}s"
        )

    async def invalidate_change_key(
        self, integration_knowledge_id: UUID, item_id: str
    ) -> None:
        """Delete the cached ChangeKey for an item.

        Should be called when an item is deleted or when we need to reprocess it.

        Args:
            integration_knowledge_id: The integration knowledge ID
            item_id: The Office item ID
        """
        key = self._get_changekey_key(integration_knowledge_id, item_id)
        await self.redis_client.delete(key)
        logger.info(f"Invalidated ChangeKey cache for item {item_id}. Redis key: {key}")

    async def clear_integration_cache(self, integration_knowledge_id: UUID) -> None:
        """Clear all cached ChangeKeys for an integration.

        Args:
            integration_knowledge_id: The integration knowledge ID
        """
        pattern = f"office_change_key:{integration_knowledge_id}:*"
        keys = await self.redis_client.keys(pattern)
        if keys:
            await self.redis_client.delete(*keys)
            logger.info(
                f"Cleared {len(keys)} cached ChangeKeys for integration {integration_knowledge_id}. "
                f"Pattern: {pattern}"
            )
        else:
            logger.info(
                f"No cached ChangeKeys found for integration {integration_knowledge_id}. "
                f"Pattern: {pattern}"
            )

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis_client.close()

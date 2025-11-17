"""Service for managing audit category configuration."""

import logging
from uuid import UUID

from intric.audit.domain.category_mappings import (
    CATEGORY_DESCRIPTIONS,
    CATEGORY_MAPPINGS,
)
from intric.audit.domain.repositories.audit_config_repository import (
    AuditConfigRepository,
)
from intric.audit.schemas.audit_config_schemas import (
    AuditConfigResponse,
    CategoryConfig,
    CategoryUpdate,
)
from intric.worker.redis import get_redis

logger = logging.getLogger(__name__)


class AuditConfigService:
    """Service for managing audit category configuration with Redis caching."""

    def __init__(self, repository: AuditConfigRepository):
        self.repository = repository
        self.redis = get_redis()
        self.cache_ttl = 60  # 60 seconds TTL as per spec

    def _cache_key(self, tenant_id: UUID, category: str) -> str:
        """Generate Redis cache key for a tenant-category pair."""
        return f"audit_config:{tenant_id}:{category}"

    async def is_category_enabled(self, tenant_id: UUID, category: str) -> bool:
        """
        Check if a category is enabled for logging (with Redis caching).

        This is called on every audit log creation, so performance is critical.
        Uses Redis cache with 60s TTL and <1ms lookup time.

        Args:
            tenant_id: Tenant identifier
            category: Category name

        Returns:
            True if category is enabled, False otherwise.
            Defaults to True if no configuration exists (backward compatible).
        """
        cache_key = self._cache_key(tenant_id, category)

        try:
            # Try Redis cache first (fast path, <0.5ms)
            cached = await self.redis.get(cache_key)
            if cached is not None:
                return cached.decode("utf-8") == "true"
        except Exception as e:
            # Graceful degradation: If Redis unavailable, fall through to database
            logger.warning(
                f"Redis cache unavailable for {cache_key}, falling back to database: {e}"
            )

        # Cache miss or Redis unavailable - query database (slow path, ~5-10ms)
        try:
            config = await self.repository.find_by_tenant_and_category(tenant_id, category)

            if config is None:
                # No config found - default to enabled for backward compatibility
                enabled = True
            else:
                enabled = config[1]

            # Cache the result in Redis for 60 seconds
            try:
                await self.redis.set(
                    cache_key, "true" if enabled else "false", ex=self.cache_ttl
                )
            except Exception as e:
                logger.warning(f"Failed to cache audit config for {cache_key}: {e}")

            return enabled

        except Exception as e:
            logger.error(
                f"Failed to check audit category enabled status for "
                f"tenant={tenant_id}, category={category}: {e}"
            )
            # On error, default to enabled (fail-safe - don't lose audit logs)
            return True

    async def get_config(self, tenant_id: UUID) -> AuditConfigResponse:
        """
        Get all audit category configurations for a tenant with metadata.

        Enriches configuration with:
        - Category descriptions from CATEGORY_DESCRIPTIONS
        - Action counts from CATEGORY_MAPPINGS
        - Example actions (first 3) for each category

        Args:
            tenant_id: Tenant identifier

        Returns:
            AuditConfigResponse with all 7 categories and metadata
        """
        # Fetch current config from database
        configs = await self.repository.find_by_tenant(tenant_id)
        config_dict = {category: enabled for category, enabled in configs}

        # All 7 categories in order
        all_categories = [
            "admin_actions",
            "user_actions",
            "security_events",
            "file_operations",
            "integration_events",
            "system_actions",
            "audit_access",
        ]

        # Build enriched category configs
        category_configs = []
        for category in all_categories:
            # Get enabled state (default to True if not found)
            enabled = config_dict.get(category, True)

            # Get actions for this category (keys are already string values)
            actions_in_category = [
                action
                for action, cat in CATEGORY_MAPPINGS.items()
                if cat == category
            ]

            category_configs.append(
                CategoryConfig(
                    category=category,
                    enabled=enabled,
                    description=CATEGORY_DESCRIPTIONS[category],
                    action_count=len(actions_in_category),
                    example_actions=actions_in_category[:3],  # First 3 examples
                )
            )

        return AuditConfigResponse(categories=category_configs)

    async def update_config(
        self, tenant_id: UUID, updates: list[CategoryUpdate]
    ) -> AuditConfigResponse:
        """
        Update audit category configurations for a tenant.

        Performs upsert for each category and invalidates Redis cache immediately.

        Args:
            tenant_id: Tenant identifier
            updates: List of category updates

        Returns:
            Updated AuditConfigResponse
        """
        for update in updates:
            # Update database
            await self.repository.update(tenant_id, update.category, update.enabled)

            # Invalidate cache immediately (critical for multi-worker consistency)
            cache_key = self._cache_key(tenant_id, update.category)
            try:
                await self.redis.delete(cache_key)
                logger.info(f"Invalidated cache for {cache_key}")
            except Exception as e:
                logger.warning(f"Failed to invalidate cache for {cache_key}: {e}")

        # Return updated config
        return await self.get_config(tenant_id)

"""Service for managing audit category and action configuration."""

import logging
from uuid import UUID

from intric.audit.domain.action_metadata import get_action_metadata
from intric.audit.domain.category_mappings import (
    CATEGORY_DESCRIPTIONS,
    CATEGORY_MAPPINGS,
    get_category_for_action,
)
from intric.audit.domain.repositories.audit_config_repository import (
    AuditConfigRepository,
)
from intric.audit.schemas.audit_config_schemas import (
    ActionConfig,
    ActionConfigResponse,
    ActionUpdate,
    AuditConfigResponse,
    CategoryConfig,
    CategoryUpdate,
)
from intric.worker.redis import get_redis

logger = logging.getLogger(__name__)

# Cache TTL for audit configuration (in seconds)
AUDIT_CONFIG_CACHE_TTL = 60
"""
Cache TTL Reasoning:
- 60 seconds provides a good balance between performance and consistency
- Audit config changes are infrequent (typically changed during initial setup or quarterly reviews)
- 60s window is acceptable for configuration propagation across workers
- Short enough to not cause confusion during testing/configuration
- Long enough to reduce database load significantly (every audit log checks config)
- At 1000 req/s, this reduces DB queries from 60,000/min to 7 queries/min per category
"""


class AuditConfigService:
    """Service for managing audit category configuration with Redis caching."""

    def __init__(self, repository: AuditConfigRepository):
        self.repository = repository
        self.redis = get_redis()
        self.cache_ttl = AUDIT_CONFIG_CACHE_TTL

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

    # ========================================================================
    # ACTION-LEVEL CONFIGURATION METHODS (Using JSONB action_overrides)
    # ========================================================================

    def _action_cache_key(self, tenant_id: UUID, action: str) -> str:
        """Generate Redis cache key for a tenant-action pair."""
        return f"audit_action:{tenant_id}:{action}"

    async def is_action_enabled(self, tenant_id: UUID, action: str) -> bool:
        """
        Check if a specific action is enabled for logging (3-level check).

        Checks in order:
        1. Category enabled? (If no, return False)
        2. Action override in JSONB? (If yes, use override value)
        3. Default to category enabled status

        Args:
            tenant_id: Tenant identifier
            action: Action type value (e.g., "user_created")

        Returns:
            True if action should be logged, False otherwise.
        """
        # Get category for this action
        category = get_category_for_action(action)

        # Check cache first
        cache_key = self._action_cache_key(tenant_id, action)
        try:
            cached = await self.redis.get(cache_key)
            if cached is not None:
                return cached.decode("utf-8") == "true"
        except Exception as e:
            logger.warning(f"Redis cache unavailable for {cache_key}: {e}")

        try:
            # Fetch category config (includes action_overrides JSONB)
            config = await self.repository.find_by_tenant_and_category(tenant_id, category)

            if config is None:
                # No config - default to True (backward compatible)
                enabled = True
            else:
                category_enabled = config[1]  # enabled boolean
                action_overrides = config[2] if len(config) > 2 else {}  # action_overrides JSONB

                # If category is disabled, action is disabled
                if not category_enabled:
                    enabled = False
                # If category is enabled, check action override
                elif action in action_overrides:
                    # Action has explicit override
                    enabled = action_overrides[action]
                else:
                    # No override, use category setting
                    enabled = True

            # Cache result
            try:
                await self.redis.set(
                    cache_key, "true" if enabled else "false", ex=self.cache_ttl
                )
            except Exception as e:
                logger.warning(f"Failed to cache action config {cache_key}: {e}")

            return enabled

        except Exception as e:
            logger.error(
                f"Failed to check action enabled for tenant={tenant_id}, action={action}: {e}"
            )
            # Fail-safe: log the action if we can't determine state
            return True

    async def get_action_config(self, tenant_id: UUID) -> ActionConfigResponse:
        """
        Get all 65 actions with their enabled status for the modal UI.

        Returns actions grouped by category with metadata.

        OPTIMIZATION: Uses batch query to fetch all category configs in a single DB call,
        then determines action status locally. Avoids 65 individual is_action_enabled calls.

        Args:
            tenant_id: Tenant identifier

        Returns:
            ActionConfigResponse with all actions
        """
        # Batch fetch all category configs in a single query
        all_configs = await self.repository.find_all_by_tenant(tenant_id)

        # Build local lookup dict: {category: (enabled, action_overrides)}
        config_dict = {
            category: (enabled, overrides)
            for category, enabled, overrides in all_configs
        }

        # Build list of all actions with their enabled status
        action_configs = []

        for action_value, category in CATEGORY_MAPPINGS.items():
            # Determine if action is enabled using local dict (avoids 65 async calls)
            if category not in config_dict:
                # No config = default enabled
                enabled = True
            else:
                category_enabled, action_overrides = config_dict[category]

                if not category_enabled:
                    # Category disabled → action disabled
                    enabled = False
                elif action_value in action_overrides:
                    # Action has explicit override
                    enabled = action_overrides[action_value]
                else:
                    # No override, use category setting (default True)
                    enabled = True

            # Get Swedish metadata
            metadata = get_action_metadata(action_value)

            action_configs.append(
                ActionConfig(
                    action=action_value,
                    enabled=enabled,
                    category=category,
                    name_sv=metadata["name_sv"],
                    description_sv=metadata["description_sv"],
                )
            )

        # Sort by category then action name
        action_configs.sort(key=lambda x: (x.category, x.action))

        return ActionConfigResponse(actions=action_configs)

    async def update_action_config(
        self, tenant_id: UUID, updates: list[ActionUpdate]
    ) -> ActionConfigResponse:
        """
        Update action overrides for a tenant.

        Stores action overrides in the JSONB action_overrides column.
        When an action is toggled, it's added to action_overrides.

        Args:
            tenant_id: Tenant identifier
            updates: List of actions to enable/disable

        Returns:
            Updated ActionConfigResponse
        """
        # Group updates by category (since we update JSONB per category)
        updates_by_category: dict[str, dict[str, bool]] = {}

        for update in updates:
            category = get_category_for_action(update.action)
            if category not in updates_by_category:
                updates_by_category[category] = {}
            updates_by_category[category][update.action] = update.enabled

        # Update each category's action_overrides
        for category, action_overrides in updates_by_category.items():
            # Fetch current config
            config = await self.repository.find_by_tenant_and_category(tenant_id, category)

            if config is None:
                # If no category config exists, create it first
                await self.repository.update(tenant_id, category, True)
                current_overrides = {}
            else:
                current_overrides = config[2] if len(config) > 2 else {}

            # Merge new overrides with existing ones
            updated_overrides = {**current_overrides, **action_overrides}

            # Update in database with new overrides
            await self.repository.update(
                tenant_id, category, True, updated_overrides
            )

            # Invalidate all action caches for this category
            for action in action_overrides.keys():
                cache_key = self._action_cache_key(tenant_id, action)
                try:
                    await self.redis.delete(cache_key)
                except Exception as e:
                    logger.warning(f"Failed to invalidate cache {cache_key}: {e}")

        # Return updated config
        return await self.get_action_config(tenant_id)
